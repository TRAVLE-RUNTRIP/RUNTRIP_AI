"""규칙 점수 기준선. 비교 기준이자, 모델이 실패하면 서비스에서 대신 쓰는 점수예요.
사용: python baseline.py → results/baseline.json"""
import json, time
import numpy as np
import config as C
from metrics import all_metrics

W_SIM, W_TASTE, W_DIST = 0.5, 0.3, 0.2   # TODO: valid 셋으로 가중치만 가볍게 조정


def rule_scores(d):
    allowed = np.zeros((len(C.TASTES), len(C.CATEGORIES)), bool)
    for ti, t in enumerate(C.TASTES):
        for c in C.TASTE_TO_CATEGORIES[t]:
            allowed[ti, C.CATEGORIES.index(c)] = True
    ok_cat = (d["tastes"] @ allowed) > 0
    taste_hit = np.take_along_axis(ok_cat, np.clip(d["cat_idx"], 0, None), 1).astype(np.float32)
    near = 1 - np.clip(d["dist_norm"], 0, 1)
    return W_SIM * d["sim_max"] + W_TASTE * taste_hit + W_DIST * near


def main():
    d = dict(np.load(C.FEAT_DIR / "test.npz"))
    t0 = time.perf_counter()
    for i in range(200):
        rule_scores({k: v[i % len(v):i % len(v) + 1] for k, v in d.items()})
    ms = (time.perf_counter() - t0) / 200 * 1000
    res = {"model": "baseline", **all_metrics(rule_scores(d), d), "infer_ms": ms}
    C.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (C.RESULT_DIR / "baseline.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(res)


if __name__ == "__main__":
    main()
