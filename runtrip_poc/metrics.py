"""평가 지표 (numpy, 프레임워크 무관). 모든 후보·기준선이 같은 함수로 평가돼요."""
import numpy as np
import config as C


def _topk(scores, mask, k):
    s = np.where(mask > 0, scores, -np.inf)
    return np.argsort(-s, axis=1)[:, :k]


def ndcg_at_k(scores, rel, mask, k=C.TOP_K):
    """상위 k개 순서 정확도. gain = 2^rel - 1, 쿼리별 평균"""
    top = _topk(scores, mask, k)
    disc = 1.0 / np.log2(np.arange(2, k + 2))
    gain = (2 ** np.take_along_axis(rel, top, 1) - 1) * np.take_along_axis(mask, top, 1)
    dcg = (gain * disc).sum(1)
    ideal = -np.sort(-np.where(mask > 0, rel, 0), axis=1)[:, :k]
    idcg = ((2 ** ideal - 1) * disc).sum(1)
    ok = idcg > 0
    return float((dcg[ok] / idcg[ok]).mean())


def hit_rate_at_k(scores, rel, mask, k=C.TOP_K):
    """상위 k개 안에 관련도 3(최고) 장소가 하나라도 있는가 (관련도 3이 있는 쿼리만)"""
    top = _topk(scores, mask, k)
    has3 = ((rel == C.REL_MAX) & (mask > 0)).any(1)
    hit = (np.take_along_axis(rel, top, 1) == C.REL_MAX).any(1)
    return float(hit[has3].mean()) if has3.any() else float("nan")


def taste_match_rate(scores, mask, cat_idx, tastes, k=C.TOP_K):
    """추천 상위 k개 중 카테고리가 페르소나 취향과 맞는 비율"""
    allowed = np.zeros((len(C.TASTES), len(C.CATEGORIES)), bool)
    for ti, t in enumerate(C.TASTES):
        for c in C.TASTE_TO_CATEGORIES[t]:
            allowed[ti, C.CATEGORIES.index(c)] = True
    ok_cat = (tastes @ allowed) > 0                    # (Q, n_categories) 쿼리별 허용 카테고리
    top = _topk(scores, mask, k)
    top_cat = np.take_along_axis(cat_idx, top, 1)
    match = np.take_along_axis(ok_cat, np.clip(top_cat, 0, None), 1) & (top_cat >= 0)
    return float(match.mean())


def all_metrics(scores, d):
    return {
        "ndcg@5": ndcg_at_k(scores, d["rel"], d["mask"]),
        "hit@5": hit_rate_at_k(scores, d["rel"], d["mask"]),
        "taste_match": taste_match_rate(scores, d["mask"], d["cat_idx"], d["tastes"]),
    }
