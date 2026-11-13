"""server/data/recommend_model.pt(+ .json) → recommend_model.npz (AI 서버가 torch 없이 numpy로 읽는 가중치)

모델은 poc/model.py Scorer(피처 10 → 64 → 32 → 1, ReLU)라 numpy 행렬곱 몇 줄로 같은 값이 나온다.
torch를 서버 이미지에 넣지 않으려고(수백 MB) 가중치만 꺼내 둔다. 취향 가산점은 학습 설정 json의 pref_bonus.
사용 (torch가 있는 .venv에서): python server/export_model.py
data/features.npz가 있으면 torch와 numpy 점수가 같은지 전부 비교한다.
"""
import json, sys
from pathlib import Path

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "poc"))
sys.path.insert(0, str(ROOT))
from model import Scorer  # noqa: E402
from server.scoring import mlp_logit  # noqa: E402

SRC = Path(__file__).parent / "data" / "recommend_model.pt"
OUT = SRC.with_suffix(".npz")


def main():
    ckpt = torch.load(SRC)
    bonus = json.loads(SRC.with_suffix(".json").read_text(encoding="utf-8"))["args"]["pref_bonus"]
    sd = {k: v.numpy() for k, v in ckpt["state_dict"].items()}
    w = {"W1": sd["net.0.weight"], "b1": sd["net.0.bias"], "W2": sd["net.3.weight"], "b2": sd["net.3.bias"],
         "W3": sd["net.5.weight"], "b3": sd["net.5.bias"], "pref_bonus": np.float32(bonus)}
    np.savez(OUT, **w)
    print(f"{OUT} 저장 (피처 {ckpt['d']}개, 취향 가산점 {bonus})")

    feats = ROOT / "data" / "features.npz"
    if feats.exists():
        X = np.load(feats)["X"]
        model = Scorer(ckpt["d"], ckpt["dropout"])
        model.load_state_dict(ckpt["state_dict"])
        model.eval()
        with torch.no_grad():
            ref = model(torch.from_numpy(X)).numpy()
        diff = float(np.abs(mlp_logit(dict(np.load(OUT)), X) - ref).max())
        print(f"torch와 numpy 점수 비교: {X.shape[0]}개 쿼리, 최대 차이 {diff:.2e}")
        assert diff < 1e-5


if __name__ == "__main__":
    main()
