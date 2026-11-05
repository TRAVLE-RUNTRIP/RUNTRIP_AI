"""평가 지표(NDCG@5, HitRate@5, 취향 일치율) + 규칙 기준선. numpy만 사용해 모델·기준선에 공통으로 쓴다.

실행: python poc/evaluate.py          → 규칙 기준선 valid 성능
      python poc/evaluate.py --test   → test 성능 (튜닝이 끝난 뒤 한 번만)
"""
import argparse
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent.parent / "data"
K = 5
HIT_MIN_REL = 2              # HitRate: 상위 K개 안에 이 점수 이상 장소가 있으면 적중
EXCLUDE_NO_POSITIVE = True   # 2점 이상 장소가 없는 쿼리는 HitRate에서 제외 (팀 확정 필요)
SPLITS = ["train", "valid", "test"]

# 피처 열 번호 (features.FEATURES 순서)
SIM, CAT_TOUR, CAT_NATURE, CAT_ETC, NIGHT_SPOT, DETOUR, IS_NIGHT, PREF_NIGHT, PREF_TOUR, PREF_NATURE = range(10)

# 규칙 기준선 가중치 (팀 확정 필요, 정한 뒤에는 바꾸지 않기)
W_MATCH, W_DETOUR = 0.3, 0.3


def topk_idx(scores, mask, k=K):
    return np.argsort(-np.where(mask, scores, -np.inf), axis=1)[:, :k]


def ndcg_at_k(scores, rel, mask, k=K):
    gains = np.where(mask, 2.0 ** rel - 1, 0.0)
    disc = 1 / np.log2(np.arange(k) + 2)
    dcg = (np.take_along_axis(gains, topk_idx(scores, mask, k), 1) * disc).sum(1)
    ideal = (-np.sort(-gains, axis=1)[:, :k] * disc).sum(1)
    ok = ideal > 0  # 전부 0점인 쿼리는 순서를 평가할 수 없어 제외
    return float((dcg[ok] / ideal[ok]).mean())


def hit_at_k(scores, rel, mask, k=K):
    top_rel = np.take_along_axis(np.where(mask, rel, 0), topk_idx(scores, mask, k), 1)
    hit = (top_rel >= HIT_MIN_REL).any(1)
    if EXCLUDE_NO_POSITIVE:
        hit = hit[((rel >= HIT_MIN_REL) & mask).any(1)]
    return float(hit.mean())


def pref_match(X):
    """후보가 고른 취향에 맞는지: 야경은 night_spot, 나머지는 카테고리 기준"""
    return ((X[..., PREF_NIGHT] * X[..., NIGHT_SPOT]
             + X[..., PREF_TOUR] * X[..., CAT_TOUR]
             + X[..., PREF_NATURE] * X[..., CAT_NATURE]) > 0)


def pref_match_at_k(scores, X, mask, k=K):
    idx = topk_idx(scores, mask, k)
    picked = np.take_along_axis(mask, idx, 1)  # 후보가 K개보다 적으면 빈자리 제외
    return float(np.take_along_axis(pref_match(X), idx, 1)[picked].mean())


def rule_baseline(X):
    return X[..., SIM] + W_MATCH * pref_match(X) - W_DETOUR * X[..., DETOUR]


def evaluate(scores, X, rel, mask):
    return {
        "NDCG@5": ndcg_at_k(scores, rel, mask),
        "HitRate@5": hit_at_k(scores, rel, mask),
        "취향일치율@5": pref_match_at_k(scores, X, mask),
    }


def load(split_name):
    d = np.load(DATA / "features.npz")
    s = d["split"] == SPLITS.index(split_name)
    return d["X"][s], d["rel"][s], d["mask"][s]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    split_name = "test" if ap.parse_args().test else "valid"
    X, rel, mask = load(split_name)
    result = evaluate(rule_baseline(X), X, rel, mask)
    print(f"규칙 기준선 ({split_name}, 쿼리 {len(X)}건):", {k: round(v, 4) for k, v in result.items()})
