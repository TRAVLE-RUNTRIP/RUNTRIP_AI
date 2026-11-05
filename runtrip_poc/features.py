"""피처 생성: (쿼리, 후보 장소) → 피처 벡터.
사용: python features.py [--embedder kure|dummy]
출력: features/{train,valid,test}.npz
  X    (Q, 20, d)  모델 입력
  rel  (Q, 20)     관련도 0~3
  mask (Q, 20)     실제 후보=1, 패딩=0
  sim_max, dist_norm, cat_idx (Q, 20) / tastes (Q, T)   ← 규칙 기준선·취향 일치율용 원본 값
"""
import argparse
import hashlib
import numpy as np
import config as C
from common import read_jsonl, haversine_km

FEATURE_NAMES = (
    ["sim_max", "sim_mean"]
    + [f"cat={c}" for c in C.CATEGORIES]
    + ["dist_norm", "target_km_norm"]
    + [f"time={t}" for t in C.TIMES]
    + [f"taste={t}" for t in C.TASTES]
)


# ---------------- 임베딩 ----------------
class KureEmbedder:
    """KURE-v1(고정, 학습 안 함)으로 문장을 벡터로. 결과는 L2 정규화돼서 내적 = 코사인 유사도."""
    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(C.EMBED_MODEL)

    def encode(self, texts):
        return self.model.encode(texts, batch_size=32, normalize_embeddings=True,
                                 show_progress_bar=True).astype(np.float32)


class DummyEmbedder:
    """KURE 없이 파이프라인만 점검할 때 쓰는 가짜 임베딩 (같은 문장 → 같은 벡터)."""
    def encode(self, texts):
        out = []
        for t in texts:
            seed = int(hashlib.md5(t.encode("utf-8")).hexdigest()[:8], 16)  # 실행마다 같은 값
            rng = np.random.default_rng(seed)
            v = rng.normal(size=64)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)


def taste_place_similarity(places, embedder):
    """장소 개요 × 취향 문장 유사도 표. 반환: {place_id: np.array(len(TASTES))}
    실서비스에서는 이 값을 밤마다 배치로 미리 계산해 DB에 저장해요."""
    ids = [p["place_id"] for p in places]
    texts = [p.get("overview") or p["name"] for p in places]
    place_vec = embedder.encode(texts)                                   # (P, D)
    taste_vec = embedder.encode([C.TASTE_SENTENCES[t] for t in C.TASTES])  # (T, D)
    sims = place_vec @ taste_vec.T                                       # (P, T)
    return dict(zip(ids, sims))


# ---------------- 피처 ----------------
def build_split(queries, place_by_id, sim_by_id):
    Q, N, d = len(queries), C.N_CANDIDATES, len(FEATURE_NAMES)
    X = np.zeros((Q, N, d), np.float32)
    rel = np.zeros((Q, N), np.float32)
    mask = np.zeros((Q, N), np.float32)
    sim_max = np.zeros((Q, N), np.float32)
    dist_norm = np.zeros((Q, N), np.float32)
    cat_idx = np.full((Q, N), -1, np.int64)
    tastes = np.zeros((Q, len(C.TASTES)), np.float32)

    for qi, q in enumerate(queries):
        p = q["persona"]
        taste_ix = [C.TASTES.index(t) for t in p["tastes"]]
        tastes[qi, taste_ix] = 1
        radius = p["distance_km"] / 3            # 후보 검색 반경 ≈ 목표 거리의 1/3
        for ci, cand in enumerate(q["candidates"][:N]):
            pl = place_by_id[cand["place_id"]]
            s = sim_by_id[pl["place_id"]][taste_ix] if C.USE_EMBEDDING else np.zeros(len(taste_ix))
            dk = haversine_km(q["origin"]["lat"], q["origin"]["lng"], pl["lat"], pl["lng"])
            f = np.zeros(d, np.float32)
            f[0], f[1] = s.max(), s.mean()
            c = C.CATEGORIES.index(pl["category"]) if pl["category"] in C.CATEGORIES else C.CATEGORIES.index("기타")
            f[2 + c] = 1
            o = 2 + len(C.CATEGORIES)
            f[o] = min(dk / radius, 2.0)
            f[o + 1] = p["distance_km"] / max(C.TARGET_KMS)
            f[o + 2 + C.TIMES.index(p["time"])] = 1
            f[o + 2 + len(C.TIMES) + np.array(taste_ix)] = 1
            X[qi, ci], rel[qi, ci], mask[qi, ci] = f, cand["rel"], 1
            sim_max[qi, ci], dist_norm[qi, ci], cat_idx[qi, ci] = f[0], f[o], c
    return dict(X=X, rel=rel, mask=mask, sim_max=sim_max, dist_norm=dist_norm,
                cat_idx=cat_idx, tastes=tastes)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedder", choices=["kure", "dummy"], default="kure")
    args = ap.parse_args()

    places = read_jsonl(C.DATA_DIR / "places.jsonl")
    place_by_id = {p["place_id"]: p for p in places}
    embedder = KureEmbedder() if args.embedder == "kure" else DummyEmbedder()
    sim_by_id = taste_place_similarity(places, embedder)

    C.FEAT_DIR.mkdir(parents=True, exist_ok=True)
    for name in ["train", "valid", "test"]:
        qs = read_jsonl(C.DATA_DIR / "split" / f"{name}.jsonl")
        arr = build_split(qs, place_by_id, sim_by_id)
        np.savez_compressed(C.FEAT_DIR / f"{name}.npz", **arr)
        print(f"{name:5s}: X {arr['X'].shape}")
    print("피처:", FEATURE_NAMES)


if __name__ == "__main__":
    main()
