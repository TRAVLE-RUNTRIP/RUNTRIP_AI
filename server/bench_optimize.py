"""/optimize를 실제 OSRM 거리표로 검증 (#4). OSRM(127.0.0.1:5000)을 띄운 뒤 레포 루트에서  python -m server.bench_optimize

BE가 할 일을 흉내 냄: 후보 범위(직선거리 합 ≤ 목표 ÷ 1.3) → /recommend → 상위 40곳 → OSRM table → /optimize → OSRM route
확인: 해를 찾는 비율, 응답 시간, 총 거리 ±10%, maxPlaces, excludedCombos(다시 만들기 3번), 실제 경로 거리
--exact: 3·5km는 모든 조합·순서를 계산(완전 탐색)해 점수 합이 최적인지도 확인
"""
import itertools, sys
import csv, json, math, time, urllib.request
from pathlib import Path

from fastapi.testclient import TestClient

from server.app import app

OSRM = "http://127.0.0.1:5000"
TOP = 40
STARTS = {"시청": (37.5663, 126.9779), "홍대입구": (37.5572, 126.9245), "강남역": (37.4979, 127.0276),
          "잠실": (37.5133, 127.1002), "여의도": (37.5284, 126.9328), "서울숲": (37.5444, 127.0374),
          "경복궁": (37.5796, 126.9770), "노원": (37.6555, 127.0614)}
TARGETS = [3, 5, 10]
PREFS = [["NIGHT_VIEW"], ["ATTRACTION"], ["NATURE"], ["NIGHT_VIEW", "NATURE"]]
places = {r["place_id"]: r for r in csv.DictReader(open(Path(__file__).resolve().parent.parent / "data" / "places.csv", encoding="utf-8-sig"))}
pool = [p for p in places.values() if p["category"] != "기타"]         # '기타'는 코스 후보 제외 (DB 스키마)


def max_places(km):                    # 개선안 6장 제안값
    return 2 if km <= 3 else 3 if km <= 7 else 4 if km <= 14 else 5


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    return 2 * 6371 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def osrm(kind, pts, q=""):
    url = f"{OSRM}/{kind}/v1/foot/" + ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in pts) + q
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def one_way_end(s, km):
    """출발지에서 동쪽으로 목표 거리의 1/3 떨어진 도착지 (최소 입력 거리 = 최단 × 1.1 이하가 되게)"""
    return (s[0], s[1] + km / 3 / (111.32 * math.cos(math.radians(s[0]))))


def run_case(c, s, e, km, prefs, night):
    D = hav(s, e)
    cand = []
    for p in pool:
        x = (float(p["lat"]), float(p["lng"]))
        d = hav(s, x) + hav(x, e)
        if d <= km / 1.3:
            cand.append((p["place_id"], (d - D) / km, x))
    if not cand:
        return None
    r = c.post("/recommend", json={"preferences": prefs, "isNight": night,
                                   "candidates": [{"placeId": p, "detourRatio": dr} for p, dr, _ in cand]}).json()
    top = sorted(zip(cand, (x["score"] for x in r["scores"])), key=lambda t: -t[1])[:TOP]
    ids, scores, pts = [t[0][0] for t in top], [t[1] for t in top], [t[0][2] for t in top]
    m = osrm("table", [s, *pts, e], "?annotations=distance")["distances"]
    m = [[round(v) for v in row] for row in m]
    body = {"targetKm": km, "maxPlaces": max_places(km), "timeLimitMs": 500, "placeIds": ids, "scores": scores,
            "distanceMatrixM": m, "excludedCombos": []}
    rounds = []
    for _ in range(4):                  # 처음 + 다시 만들기 3번
        t = time.perf_counter()
        res = c.post("/optimize", json=body).json()
        ms = (time.perf_counter() - t) * 1000
        rounds.append((res, ms))
        if not res["found"]:
            break
        body["excludedCombos"] = body["excludedCombos"] + [res["orderedPlaceIds"]]
    return ids, scores, m, body, rounds, len(cand)


def check(km, ids, m, body, rounds, s, e):
    """솔버와 별개로 거리표에서 다시 계산해 제약을 확인. 첫 코스는 OSRM route로 실제 거리도 확인"""
    idx = {p: i + 1 for i, p in enumerate(ids)}
    seen, route_km = [], None
    for k, (res, _) in enumerate(rounds):
        if not res["found"]:
            continue
        seq = [0, *[idx[p] for p in res["orderedPlaceIds"]], len(ids) + 1]
        total = sum(m[a][b] for a, b in zip(seq, seq[1:])) / 1000
        assert abs(total - res["totalKm"]) < 0.01, (total, res)
        assert km * 0.9 <= total <= km * 1.1, (km, total)
        assert 1 <= len(res["orderedPlaceIds"]) <= body["maxPlaces"]
        for prev in seen:                                   # 이미 보여준 조합의 장소가 모두 다시 들어가면 안 됨
            assert not set(prev) <= set(res["orderedPlaceIds"]), (prev, res)
        seen.append(res["orderedPlaceIds"])
        if k == 0:
            pts = [s, *[(float(places[p]["lat"]), float(places[p]["lng"])) for p in res["orderedPlaceIds"]], e]
            route_km = osrm("route", pts, "?overview=false")["routes"][0]["distance"] / 1000
    return route_km


def exact_best(km, mp, scores, m):
    """모든 조합·순서 중 ±10% 안에서 점수 합 최대 (없으면 -1). 3·5km(장소 2~3곳)만 현실적인 시간"""
    n, lo, hi, best = len(scores), km * 900, km * 1100, -1.0
    for k in range(1, mp + 1):
        for combo in itertools.combinations(range(1, n + 1), k):
            sc = sum(max(0, scores[i - 1]) for i in combo)
            if sc > best and any(lo <= sum(m[a][b] for a, b in zip(seq, seq[1:])) <= hi
                                 for seq in ((0, *p, n + 1) for p in itertools.permutations(combo))):
                best = sc
    return best


if __name__ == "__main__":
    exact = "--exact" in sys.argv
    opt_same = opt_total = 0
    rows, n = [], 0
    with TestClient(app) as c:
        for name, s in STARTS.items():
            for km in TARGETS:
                for kind in ("LOOP", "ONE_WAY"):
                    e = s if kind == "LOOP" else one_way_end(s, km)
                    prefs, night = PREFS[n % len(PREFS)], n % 2 == 1
                    n += 1
                    out = run_case(c, s, e, km, prefs, night)
                    if out is None:
                        rows.append((name, kind, km, 0, None, [], None))
                        continue
                    ids, scores, m, body, rounds, ncand = out
                    route_km = check(km, ids, m, body, rounds, s, e)
                    if exact and km <= 5:
                        best = exact_best(km, body["maxPlaces"], scores, m)
                        got = sum(max(0, scores[ids.index(p)]) for p in rounds[0][0]["orderedPlaceIds"]) if rounds[0][0]["found"] else -1
                        opt_total += 1
                        opt_same += abs(best - got) < 1e-9
                        if abs(best - got) >= 1e-9:
                            print(f"  최적 아님: {name} {kind} {km}km 최적 {best:.3f} / 결과 {got:.3f}")
                    rows.append((name, kind, km, ncand, rounds[0][0], rounds, route_km))

    print(f"{'출발':6s} {'종류':7s} {'목표':>4s} {'후보':>4s} {'첫 코스':>8s} {'실제경로':>8s} {'장소':>4s} {'다시 만들기':>10s} {'응답(ms)':>9s}")
    first_found = re_found = re_total = 0
    times = []
    for name, kind, km, ncand, first, rounds, route_km in rows:
        if first is None:
            print(f"{name:6s} {kind:7s} {km:4d} {ncand:4d}  후보 없음")
            continue
        first_found += first["found"]
        re = [r for r, _ in rounds[1:]]
        re_found += sum(r["found"] for r in re)
        re_total += 3 if first["found"] else 0
        times += [ms for _, ms in rounds]
        print(f"{name:6s} {kind:7s} {km:4d} {ncand:4d} {(str(first['totalKm']) + 'km') if first['found'] else '못 찾음':>8s} "
              f"{(f'{route_km:.2f}km') if route_km else '-':>8s} {len(first['orderedPlaceIds']):4d} "
              f"{sum(r['found'] for r in re)}/{len(re) if first['found'] else 0:>8} {max(ms for _, ms in rounds):9.0f}")
    times.sort()
    print(f"\n첫 코스 해를 찾은 비율: {first_found}/{len(rows)}  |  다시 만들기: {re_found}/{re_total}"
          f"  |  응답 중앙값 {times[len(times) // 2]:.0f}ms, 최대 {times[-1]:.0f}ms (솔버 제한 500ms)")
    if exact:
        print(f"3·5km 완전 탐색 최적과 같음: {opt_same}/{opt_total} (답이 없는 경우는 양쪽 다 -1로 같음)")
