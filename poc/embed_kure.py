"""KURE-v1로 장소 개요·취향 문장을 임베딩해 data/kure/에 저장 (1회 실행)

필요: pip install sentence-transformers  (첫 실행 시 모델 약 2.3GB 다운로드)
출력: place_ids.json, place_vecs.npy (장소 수 × 1024), pref_vecs.npy (3 × 1024, PREFS 순서)
"""
import csv, json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer

DATA = Path(__file__).parent.parent / "data"
OUT = DATA / "kure"
PREFS = ["야경", "관광 명소", "자연·공원"]
# 버튼 → KURE에 넣을 문장 (Notion '장소 추천 동작 원리' 2장 초안, 팀 확정 필요)
PREF_QUERY = {
    "야경": "밤에 조명과 야경이 아름다운 곳",
    "관광 명소": "유명한 랜드마크와 볼거리가 많은 관광 명소",
    "자연·공원": "나무, 물, 숲이 있는 자연 속 산책로와 공원",
}


def main():
    with (DATA / "places.csv").open(encoding="utf-8-sig") as f:
        places = [p for p in csv.DictReader(f) if p["overview"].strip()]
    model = SentenceTransformer("nlpai-lab/KURE-v1")
    place_vecs = model.encode([f"{p['title']}. {p['overview']}" for p in places],
                              batch_size=32, normalize_embeddings=True, show_progress_bar=True)
    pref_vecs = model.encode([PREF_QUERY[p] for p in PREFS], normalize_embeddings=True)

    OUT.mkdir(exist_ok=True)
    (OUT / "place_ids.json").write_text(json.dumps([p["place_id"] for p in places]), encoding="utf-8")
    np.save(OUT / "place_vecs.npy", place_vecs.astype(np.float32))
    np.save(OUT / "pref_vecs.npy", pref_vecs.astype(np.float32))
    print(f"장소 {len(places)}곳, 취향 문장 {len(PREFS)}개 임베딩 → {OUT}")


if __name__ == "__main__":
    main()
