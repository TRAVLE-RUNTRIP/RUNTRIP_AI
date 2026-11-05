"""queries.jsonl + labels.jsonl + places.csv + KURE 벡터 → 학습용 패딩 배열 data/features.npz

후보 수가 쿼리마다 달라서(5~20개) MAX_CANDS로 패딩하고 mask(실제 후보=True)를 함께 저장한다.
"""
import argparse, csv, json
from pathlib import Path

import numpy as np

DATA = Path(__file__).parent.parent / "data"
MAX_CANDS = 20
PREFS = ["야경", "관광 명소", "자연·공원"]
CATS = ["관광 명소", "자연·공원", "기타"]
FEATURES = [
    "kure_sim",                                    # 고른 취향 문장과의 코사인 유사도 중 max
    "cat_관광명소", "cat_자연공원", "cat_기타",       # 카테고리 one-hot
    "night_spot",                                  # 서울시 야경명소 여부
    "detour_ratio",                                # detour_km / target_km (라벨의 거리 감점 기준과 같은 척도)
    "is_night",                                    # 시간대
    "pref_야경", "pref_관광명소", "pref_자연공원",    # 사용자가 고른 취향 (multi-hot)
]
SPLITS = ["train", "valid", "test"]


def load_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l]


def load_kure_sims(kure_dir):
    """장소별 취향 3개와의 코사인 유사도 (벡터가 정규화돼 있어 내적 = 코사인)"""
    place_ids = json.loads((kure_dir / "place_ids.json").read_text(encoding="utf-8"))
    sims = np.load(kure_dir / "place_vecs.npy") @ np.load(kure_dir / "pref_vecs.npy").T
    return dict(zip(place_ids, sims))


def build(kure_dir):
    with (DATA / "places.csv").open(encoding="utf-8-sig") as f:
        places = {p["place_id"]: p for p in csv.DictReader(f)}
    queries = load_jsonl(DATA / "queries.jsonl")
    labels = {r["query_id"]: r["labels"] for r in load_jsonl(DATA / "labels.jsonl")}
    split_of = {pid: i for i, s in enumerate(SPLITS)
                for pid in json.loads((DATA / "split.json").read_text(encoding="utf-8"))[s]}
    sims = load_kure_sims(kure_dir)

    n, d = len(queries), len(FEATURES)
    X = np.zeros((n, MAX_CANDS, d), np.float32)
    rel = np.zeros((n, MAX_CANDS), np.int64)
    mask = np.zeros((n, MAX_CANDS), bool)
    place_ids = np.full((n, MAX_CANDS), "", dtype=object)
    for qi, q in enumerate(queries):
        pref_idx = [PREFS.index(p) for p in q["prefs"]]
        pref_hot = [float(p in q["prefs"]) for p in PREFS]
        for j, c in enumerate(q["candidates"]):
            p = places[c["place_id"]]
            X[qi, j] = [
                sims[c["place_id"]][pref_idx].max(),
                *[float(p["category"] == cat) for cat in CATS],
                float(p["night_spot"]),
                c["detour_km"] / q["target_km"],
                float(q["time_slot"] == "night"),
                *pref_hot,
            ]
            rel[qi, j] = labels[q["query_id"]][c["place_id"]]
            mask[qi, j] = True
            place_ids[qi, j] = c["place_id"]

    split = np.array([split_of[q["persona_id"]] for q in queries])
    out = DATA / "features.npz"
    np.savez(out, X=X, rel=rel, mask=mask, split=split, place_ids=place_ids.astype(str),
             query_ids=np.array([q["query_id"] for q in queries]), feature_names=np.array(FEATURES))
    print(f"features.npz: 쿼리 {n}건 × 후보 최대 {MAX_CANDS} × 피처 {d}개 → {out}")
    print("분할:", {s: int((split == i).sum()) for i, s in enumerate(SPLITS)})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--kure-dir", type=Path, default=DATA / "kure")
    build(ap.parse_args().kure_dir)
