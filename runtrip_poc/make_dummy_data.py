"""Gemini·TourAPI 없이 파이프라인 전체를 미리 돌려 보는 가짜 데이터.
숨은 규칙 + 잡음으로 관련도를 만들어서, 모델이 기준선을 이길 수 있는지 흐름만 확인해요.
사용: python make_dummy_data.py --n 600"""
import argparse, random
import config as C
from common import write_jsonl, haversine_km
from data_gen import ORIGINS, sample_persona

OVERVIEW = {
    "관광지": "야경이 아름다운 전망 명소", "문화시설": "역사와 문화가 있는 박물관",
    "공원·자연": "나무와 물길이 있는 조용한 공원", "쇼핑": "상점이 모인 거리",
    "음식점": "현지 음식점", "기타": "기타 장소",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    args = ap.parse_args()
    rng = random.Random(0)

    places = []
    for i in range(400):
        lat0, lng0 = rng.choice(list(ORIGINS.values()))
        cat = rng.choice(C.CATEGORIES)
        places.append({"place_id": f"p{i:04d}", "name": f"장소{i}", "category": cat,
                       "lat": lat0 + rng.uniform(-0.03, 0.03), "lng": lng0 + rng.uniform(-0.03, 0.03),
                       "overview": OVERVIEW[cat] + f" {i}"})
    write_jsonl(C.DATA_DIR / "places.jsonl", places)

    queries = []
    while len(queries) < args.n:
        region, origin = rng.choice(list(ORIGINS.items()))
        persona = sample_persona(rng)
        near = sorted(places, key=lambda p: haversine_km(*origin, p["lat"], p["lng"]))[:60]
        cands = rng.sample(near, C.N_CANDIDATES)
        ok = {c for t in persona["tastes"] for c in C.TASTE_TO_CATEGORIES[t]}
        rows = []
        for p in cands:
            d = haversine_km(*origin, p["lat"], p["lng"]) / (persona["distance_km"] / 3)
            score = 2.0 * (p["category"] in ok) + (1 - min(d, 1)) \
                + 0.8 * (persona["time"] == "night" and p["category"] == "관광지") + rng.gauss(0, 0.6)
            rows.append({"place_id": p["place_id"], "rel": int(max(0, min(3, round(score))))})
        queries.append({"query_id": f"q{len(queries):05d}", "region": region, "persona": persona,
                        "origin": {"lat": origin[0], "lng": origin[1]}, "candidates": rows})
    write_jsonl(C.DATA_DIR / "queries.jsonl", queries)
    print(f"가짜 데이터: 장소 {len(places)}개, 쿼리 {len(queries)}건")


if __name__ == "__main__":
    main()
