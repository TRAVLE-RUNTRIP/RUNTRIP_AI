"""data/kure/(embed_kure.py 결과) + data/places.csv → server/data/places_serving.csv

AI 서버가 읽는 장소 정보: 카테고리, night_spot, 취향 3개와의 KURE 유사도.
규칙 점수와 MLP 모두 KURE 벡터 대신 유사도 숫자만 쓰므로(PoC 문서 5장) 1024차원 벡터는 서버에 두지 않는다.
사용: python poc/embed_kure.py → python server/build_serving.py
"""
import csv, json, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from poc.features import PREFS  # noqa: E402

KURE = ROOT / "data" / "kure"
OUT = Path(__file__).parent / "data" / "places_serving.csv"


def main():
    with (ROOT / "data" / "places.csv").open(encoding="utf-8-sig") as f:
        places = {p["place_id"]: p for p in csv.DictReader(f)}
    ids = json.loads((KURE / "place_ids.json").read_text(encoding="utf-8"))
    sims = np.load(KURE / "place_vecs.npy") @ np.load(KURE / "pref_vecs.npy").T   # features.load_kure_sims와 같은 계산
    missing = set(places) - set(ids)
    if missing:
        raise SystemExit(f"KURE 벡터가 없는 장소 {len(missing)}곳: places.csv가 바뀌었으면 embed_kure.py를 다시 실행하세요")

    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["place_id", "category", "night_spot", *[f"sim_{p}" for p in PREFS]])
        for pid, s in zip(ids, sims):
            p = places[pid]
            w.writerow([pid, p["category"], p["night_spot"], *[f"{x:.9g}" for x in s]])   # 9자리 = float32 그대로 복원
    print(f"장소 {len(ids)}곳 → {OUT}")


if __name__ == "__main__":
    main()
