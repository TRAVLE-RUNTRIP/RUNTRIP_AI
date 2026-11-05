"""places.csv → personas.json, queries.jsonl, split.json (장소 추천 PoC 학습용 쿼리)

- PoC는 개요(overview)가 있는 장소만 사용 (KURE 유사도·라벨링 기준을 같게)
- 페르소나 200명 = 취향 조합 7 × 시간대 2 에 고르게 배분, 1명당 쿼리 10건
- 목표거리: 3·5·10km 칩 50%, 자유 입력 50% (3~12km 80%, 1~3km 10%, 12~21km 10%)
- 후보 = 타원 영역: d(출발,p) + d(p,도착) <= 목표거리 / ROAD_FACTOR (순환 코스는 도착=출발 → 원)
- 후보 최대 20개(카테고리가 섞이게 뽑음), MIN_CANDS 미만이면 출발지를 다시 뽑음
- 분할: 페르소나 기준 70/15/15 (취향·시간대 조합별로 나눠 고르게)
"""
import csv, itertools, json
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SEED = 42
N_PERSONAS, Q_PER_PERSONA = 200, 10
MAX_CANDS, MIN_CANDS = 20, 5
ROAD_FACTOR = 1.3      # 실제 도보 경로 ≈ 직선거리 × 1.3
END_RATIO = 0.4        # 도착지 지정 쿼리 비율 (나머지는 순환)
CHIP_RATIO = 0.5       # 3·5·10km 빠른 선택 비율
FREE_KM_RANGES = [((3, 12), 0.8), ((1, 3), 0.1), ((12, 21), 0.1)]  # 자유 입력 분포
START_JITTER_KM = 0.5  # 출발지 = 임의 장소 좌표 + 최대 0.5km 이동
PREFS = ["야경", "관광 명소", "자연·공원"]
TIME_SLOTS = ["day", "night"]


def haversine_km(lat, lng, lats, lngs):
    p = np.pi / 180
    h = np.sin((lats - lat) * p / 2) ** 2 + np.cos(lat * p) * np.cos(lats * p) * np.sin((lngs - lng) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(h))


def jitter(rng, lat, lng, max_km):
    r, theta = max_km * np.sqrt(rng.random()), rng.random() * 2 * np.pi
    return lat + r * np.cos(theta) / 111.0, lng + r * np.sin(theta) / (111.0 * np.cos(np.radians(lat)))


def make_personas():
    combos = [list(c) for k in (1, 2, 3) for c in itertools.combinations(PREFS, k)]  # 7가지
    slots = [(c, t) for c in combos for t in TIME_SLOTS]                             # 14가지
    return [
        {"persona_id": f"P{i + 1:03d}", "prefs": slots[i % len(slots)][0], "time_slot": slots[i % len(slots)][1]}
        for i in range(N_PERSONAS)
    ]


def sample_target_km(rng):
    if rng.random() < CHIP_RATIO:
        return float(rng.choice([3, 5, 10]))
    ranges, weights = zip(*FREE_KM_RANGES)
    lo, hi = ranges[rng.choice(len(ranges), p=weights)]
    return float(round(rng.uniform(lo, hi) * 2) / 2)  # 0.5km 단위


def pick_candidates(rng, idx):
    """영역 안 장소에서 무작위로 최대 MAX_CANDS개 (카테고리 균형을 맞추면 작은 카테고리 장소가 과다 등장함)"""
    return list(rng.choice(idx, size=min(MAX_CANDS, len(idx)), replace=False))


def make_query(rng, persona, places, lats, lngs, stats):
    while True:
        target_km = sample_target_km(rng)
        a = rng.integers(len(places))
        s_lat, s_lng = jitter(rng, lats[a], lngs[a], START_JITTER_KM)
        d_start = haversine_km(s_lat, s_lng, lats, lngs)

        end = None
        d_end, d_se = d_start, 0.0
        if rng.random() < END_RATIO:
            # 도착지: 직선거리가 목표거리/ROAD_FACTOR의 30~80%인 장소 근처
            budget = target_km / ROAD_FACTOR
            ok = np.where((d_start >= 0.3 * budget) & (d_start <= 0.8 * budget))[0]
            if len(ok):
                b = rng.choice(ok)
                e_lat, e_lng = jitter(rng, lats[b], lngs[b], 0.2)
                d_end = haversine_km(e_lat, e_lng, lats, lngs)
                d_se = float(haversine_km(s_lat, s_lng, np.array([e_lat]), np.array([e_lng]))[0])
                end = {"lat": round(float(e_lat), 6), "lng": round(float(e_lng), 6)}

        inside = np.where(d_start + d_end <= target_km / ROAD_FACTOR)[0]
        if len(inside) < MIN_CANDS:
            stats[f"{'도착지' if end else '순환'} {target_km:g}km"] += 1
            continue

        picked = pick_candidates(rng, inside)
        return {
            "persona_id": persona["persona_id"], "prefs": persona["prefs"], "time_slot": persona["time_slot"],
            "start": {"lat": round(float(s_lat), 6), "lng": round(float(s_lng), 6)},
            "end": end, "target_km": target_km, "n_in_area": int(len(inside)),
            "candidates": [
                {"place_id": places[i]["place_id"], "detour_km": round(float(d_start[i] + d_end[i] - d_se), 3)}
                for i in picked
            ],
        }


def make_split(rng, personas):
    split = {"train": [], "valid": [], "test": []}
    by_combo = {}
    for p in personas:
        by_combo.setdefault((tuple(p["prefs"]), p["time_slot"]), []).append(p["persona_id"])
    for ids in by_combo.values():
        rng.shuffle(ids)
        n_va = n_te = round(len(ids) * 0.15)
        split["test"] += ids[:n_te]
        split["valid"] += ids[n_te:n_te + n_va]
        split["train"] += ids[n_te + n_va:]
    return split


def main():
    rng = np.random.default_rng(SEED)
    with (HERE / "places.csv").open(encoding="utf-8-sig") as f:
        all_places = list(csv.DictReader(f))
    places = [p for p in all_places if p["overview"].strip()]
    print(f"장소: 전체 {len(all_places)}곳 중 개요 있는 {len(places)}곳 사용")
    lats = np.array([float(p["lat"]) for p in places])
    lngs = np.array([float(p["lng"]) for p in places])

    personas = make_personas()
    stats = Counter()
    queries = []
    for p in personas:
        for _ in range(Q_PER_PERSONA):
            q = make_query(rng, p, places, lats, lngs, stats)
            queries.append({"query_id": f"Q{len(queries) + 1:04d}", **q})

    (HERE / "personas.json").write_text(json.dumps(personas, ensure_ascii=False, indent=1), encoding="utf-8")
    with (HERE / "queries.jsonl").open("w", encoding="utf-8") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    split = make_split(rng, personas)
    (HERE / "split.json").write_text(json.dumps(split, ensure_ascii=False, indent=1), encoding="utf-8")

    # 리포트
    n = np.array([len(q["candidates"]) for q in queries])
    km = np.array([q["target_km"] for q in queries])
    print(f"페르소나 {len(personas)}명, 쿼리 {len(queries)}건, 학습 쌍 {n.sum()}개")
    print(f"분할(페르소나): train {len(split['train'])} / valid {len(split['valid'])} / test {len(split['test'])}")
    print(f"순환 {sum(q['end'] is None for q in queries)} / 도착지 지정 {sum(q['end'] is not None for q in queries)}")
    print(f"목표거리: 3~12km {np.mean((km >= 3) & (km <= 12)):.0%}, 중앙값 {np.median(km):g}km")
    print(f"후보 수: 평균 {n.mean():.1f}, 20개 꽉 참 {np.mean(n == MAX_CANDS):.0%}, 10개 미만 {np.mean(n < 10):.0%}")
    print("목표거리별:")
    for lo, hi in [(1, 3), (3, 5), (5, 10), (10, 12.01), (12.01, 22)]:
        qs = [q for q in queries if lo <= q["target_km"] < hi]
        if qs:
            print(f"  {lo:>5g}~{hi:<5g}km: {len(qs):>4}건, 평균 후보 {np.mean([len(q['candidates']) for q in qs]):.1f}, "
                  f"영역 안 장소 중앙값 {int(np.median([q['n_in_area'] for q in qs]))}")
    print(f"후보 {MIN_CANDS}개 미만으로 다시 뽑은 횟수: {sum(stats.values())}회")
    pid2cat = {p["place_id"]: p["category"] for p in places}
    print("후보 카테고리 분포:", dict(Counter(pid2cat[c["place_id"]] for q in queries for c in q["candidates"])))


if __name__ == "__main__":
    main()
