"""Gemini로 합성 학습 데이터 생성 (쿼리 1건 = 페르소나 + 후보 20개 + 장소별 관련도 0~3).
사용: GEMINI_API_KEY=... python data_gen.py --n 2000
입력: data/places.jsonl (TourAPI 서울 장소: place_id, name, category, lat, lng, overview)
출력: data/queries.jsonl, data/review_sample.csv (사람 검수용)
주의: 무료 등급은 입력이 Google 제품 개선에 쓰일 수 있어요. 합성 데이터라 괜찮지만 실제 사용자 정보는 넣지 않아요.
"""
import argparse, csv, json, os, random, time
import config as C
from common import read_jsonl, write_jsonl, haversine_km

# PoC 데이터 생성 지역 (출발 좌표)
# 음식점 제외 후 3km 반경(1km) 장소 수: 시청 53, 동대문 30 / 여의도 7, 서울숲 5, 잠실 6
# → TourAPI 장소가 도심에 몰려 있어 PoC는 도심 2곳으로 진행.
#   외곽(한강·공원·잠실)은 OSM 경유지 추가 후 2단계에서 다룸 (2026-10-11)
ORIGINS = {
    "도심(시청)": (37.5663, 126.9779),
    "동대문(DDP)": (37.5665, 127.0092),
}

PROMPT = """너는 여행지 러닝 코스의 장소 추천 평가자다.
아래 러너에게 각 후보 장소가 '러닝 코스 경유지'로 얼마나 적합한지 0~3점으로 평가한다.
3=매우 적합, 2=적합, 1=약간 관련, 0=부적합. 장소 개요에 근거해서만 판단한다.

[러너]
취향: {tastes} / 목표 거리: {distance_km}km 순환 / 시간대: {time_kr} / 수준: {level}

[후보 장소]
{candidates}

반드시 아래 JSON 형식으로만 답한다. 모든 후보 id를 정확히 한 번씩 포함한다.
{{"ratings": [{{"id": "<place_id>", "rel": 0}}, ...]}}"""


def sample_persona(rng):
    k = rng.choice([1, 1, 2, 3])
    return {"tastes": rng.sample(C.TASTES, k), "distance_km": rng.choice(C.TARGET_KMS),
            "time": rng.choice(C.TIMES), "level": rng.choice(C.LEVELS)}


def sample_candidates(rng, places, origin, distance_km):
    """출발지 반경(목표 거리의 1/3) 안에서 후보 20개. 부족하면 반경을 넓혀요."""
    radius = distance_km / 3
    for _ in range(4):
        near = [p for p in places if haversine_km(*origin, p["lat"], p["lng"]) <= radius]
        if len(near) >= C.N_CANDIDATES:
            return rng.sample(near, C.N_CANDIDATES)
        radius *= 1.5
    return None  # 장소 부족 → 이 쿼리는 건너뜀


def usable_places(places):
    return [p for p in places if p["category"] not in C.EXCLUDE_CATEGORIES]


def check_coverage(places):
    """지역·목표 거리별로 반경 안에 후보가 20개 이상 있는지 점검 (API 호출 없음)"""
    print(f"후보로 쓸 장소: {len(places)}개 (제외: {', '.join(C.EXCLUDE_CATEGORIES)})")
    for region, origin in ORIGINS.items():
        row = []
        for km in C.TARGET_KMS:
            r = km / 3
            n = sum(1 for p in places if haversine_km(*origin, p["lat"], p["lng"]) <= r)
            row.append(f"{km}km(반경 {r:.1f}km): {n:3d}개{' ← 부족, 반경 자동 확장' if n < C.N_CANDIDATES else ''}")
        print(f"  {region:10s} | " + " | ".join(row))
    cats = {}
    for p in places:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    print("  카테고리:", cats)


def validate(resp_text, cand_ids):
    """자동 검증: JSON 파싱, 후보 id만 사용, 모든 후보 1번씩, 점수 0~3"""
    data = json.loads(resp_text)
    ratings = data["ratings"]
    ids = [r["id"] for r in ratings]
    if sorted(ids) != sorted(cand_ids):
        raise ValueError("후보 id 불일치 (누락·중복·환각)")
    if any(r["rel"] not in (0, 1, 2, 3) for r in ratings):
        raise ValueError("점수 범위 오류")
    return {r["id"]: r["rel"] for r in ratings}


def call_gemini(client, prompt):
    resp = client.models.generate_content(
        model=C.GEMINI_MODEL, contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0.2})
    return resp.text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=C.N_QUERIES)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--check", action="store_true", help="API 호출 없이 지역별 후보 수만 점검")
    args = ap.parse_args()

    if args.check:
        check_coverage(usable_places(read_jsonl(C.DATA_DIR / "places.jsonl")))
        return

    from google import genai               # pip install google-genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    rng = random.Random(args.seed)
    places = usable_places(read_jsonl(C.DATA_DIR / "places.jsonl"))

    out_path = C.DATA_DIR / "queries.jsonl"
    queries = read_jsonl(out_path) if out_path.exists() else []   # 중간에 끊겨도 이어서 생성
    fails = 0
    while len(queries) < args.n:
        region, origin = rng.choice(list(ORIGINS.items()))
        persona = sample_persona(rng)
        cands = sample_candidates(rng, places, origin, persona["distance_km"])
        if cands is None:
            continue
        cand_text = "\n".join(f"- id={p['place_id']} | {p['name']} | {p['category']} | {(p.get('overview') or '')[:200]}"
                              for p in cands)
        prompt = PROMPT.format(tastes=", ".join(persona["tastes"]), distance_km=persona["distance_km"],
                               time_kr="야간" if persona["time"] == "night" else "주간",
                               level=persona["level"], candidates=cand_text)
        for attempt in range(3):
            try:
                rel = validate(call_gemini(client, prompt), [p["place_id"] for p in cands])
                break
            except Exception as e:           # 파싱 실패·검증 실패·API 오류 → 재시도
                fails += 1
                time.sleep(2 ** attempt)
        else:
            continue
        queries.append({"query_id": f"q{len(queries):05d}", "region": region, "persona": persona,
                        "origin": {"lat": origin[0], "lng": origin[1]},
                        "candidates": [{"place_id": p["place_id"], "rel": rel[p["place_id"]]} for p in cands]})
        if len(queries) % 50 == 0:
            write_jsonl(out_path, queries)
            print(f"{len(queries)}/{args.n} 생성 (실패·재시도 {fails}회)")
    write_jsonl(out_path, queries)

    # 사람 검수용 샘플 (10~20%): 결과를 직접 보고 이상한 점수를 고쳐요
    name = {p["place_id"]: p["name"] for p in places}
    sample = rng.sample(queries, int(len(queries) * C.REVIEW_RATIO))
    with open(C.DATA_DIR / "review_sample.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["query_id", "tastes", "distance_km", "time", "level", "place_id", "place_name", "rel", "rel_수정", "메모"])
        for q in sample:
            p = q["persona"]
            for c in q["candidates"]:
                w.writerow([q["query_id"], "+".join(p["tastes"]), p["distance_km"], p["time"], p["level"],
                            c["place_id"], name[c["place_id"]], c["rel"], "", ""])
    print(f"완료: {len(queries)}건, 검수 샘플 {len(sample)}건 → data/review_sample.csv")


if __name__ == "__main__":
    main()
