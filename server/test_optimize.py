"""/optimize 점검 (OSRM 없이, 정답을 아는 작은 거리표). 레포 루트에서  python -m server.test_optimize
실제 OSRM 거리표 검증은 server/bench_optimize.py"""
from fastapi.testclient import TestClient

from server import optimize
from server.app import app

# 일직선 위의 점 (m): 출발지 0, 장소 A~E, 도착지 0 (순환). 거리 = 위치 차이
# 개선안 7장 표와 같게: A+B 왕복 7.8km(초과), A+C+D 4.6km(점수 합 2.47), B+E 4.8km(1.58)
POS = {"S": 0, "A": 1500, "B": -2400, "C": 2300, "D": 1000, "E": -2200, "F": -1000, "T": 0}


def matrix(names):
    return [[abs(POS[a] - POS[b]) for b in names] for a in names]


def body(ids, scores, km=5, max_places=3, excluded=()):
    return {"targetKm": km, "maxPlaces": max_places, "timeLimitMs": 300, "placeIds": ids, "scores": scores,
            "distanceMatrixM": matrix(["S", *ids, "T"]), "excludedCombos": [list(c) for c in excluded]}


def main(c):
    ids, scores = ["A", "B", "C", "D", "E"], [0.92, 0.88, 0.80, 0.75, 0.70]
    # 개선안 7장 예시: A(1등)·B(2등)는 반대 방향이라 같이 가면 7.8km → 거리 초과. 같은 방향 묶음이 점수 합 최대
    r = c.post("/optimize", json=body(ids, scores)).json()
    assert r["found"] and 4.5 <= r["totalKm"] <= 5.5 and len(r["orderedPlaceIds"]) <= 3, r
    best = r["orderedPlaceIds"]
    assert set(best) == {"A", "C", "D"} and r["totalKm"] == 4.6, r
    print("1등·2등이 반대 방향:", best, r["totalKm"], "km")

    # 다시 만들기: 이미 보여준 조합이 다시 나오지 않음
    shown = [best]
    for _ in range(3):
        r = c.post("/optimize", json=body(ids, scores, excluded=shown)).json()
        if not r["found"]:
            break
        assert not any(set(s) <= set(r["orderedPlaceIds"]) for s in shown), (shown, r)
        assert 4.5 <= r["totalKm"] <= 5.5, r
        shown.append(r["orderedPlaceIds"])
    print("다시 만들기:", shown[1:])

    # 장소 수 상한
    r = c.post("/optimize", json=body(ids, scores, km=5, max_places=1)).json()
    assert not r["found"] or len(r["orderedPlaceIds"]) == 1, r

    # 음수 점수 장소는 피함: A만으로 3km가 맞으면 C(음수)는 넣지 않음
    r = c.post("/optimize", json=body(["A", "C"], [0.9, -0.5], km=3)).json()
    assert r["found"] and r["orderedPlaceIds"] == ["A"], r
    # E만(4.4km)과 E+B(4.8km) 둘 다 거리는 맞음 → 음수인 B를 뺀 E만
    r = c.post("/optimize", json=body(["B", "E"], [-0.5, 0.7], km=4.6)).json()
    assert r["found"] and r["orderedPlaceIds"] == ["E"], r
    # 0에 아주 가까운 음수도 손해로 봄: E(−0.0004, 4.4km)와 B(0, 4.8km) 둘 다 거리는 맞음 → 더 먼 B
    # (−0.0004가 0으로 반올림되면 둘이 같은 점수가 되어 짧은 E를 고르게 됨)
    r = c.post("/optimize", json=body(["B", "E"], [0.0, -0.0004], km=4.6, max_places=1)).json()
    assert r["found"] and r["orderedPlaceIds"] == ["B"], r
    # 다른 방법이 없으면 넣음: D(2km)로는 5km가 안 되고 B(음수) 왕복 4.8km만 가능 → 코스를 못 만드는 것보다 나음
    r = c.post("/optimize", json=body(["D", "B"], [0.9, -0.5], km=5)).json()
    assert r["found"] and r["orderedPlaceIds"] == ["B"] and r["totalKm"] == 4.8, r

    # 답이 없음: 가장 먼 장소를 왕복해도 목표의 90%에 못 미침
    r = c.post("/optimize", json=body(["D"], [0.9], km=10)).json()
    assert r == {"found": False, "orderedPlaceIds": [], "totalKm": None, "overlapRatio": None, "stops": []}, r
    print("답 없음·음수 점수·장소 수 상한 확인")

    # 같은 길 왕복 줄이기 (실제 OSRM 대신 가짜 겹침). F(−1000m)를 더하면 점수 최고는 A+C+D·A+D+F(2.47),
    # B+E+F(2.38, 4.8km)는 95%(2.35) 이상, A+C(1.72)는 95% 아래
    ids6, scores6 = [*ids, "F"], [*scores, 0.80]
    coords = [(37.5, 127.0)] + [(37.5 + POS[p] / 111_000, 127.0) for p in ids6] + [(37.5, 127.0)]
    names = {pt: p for p, pt in zip(ids6, coords[1:-1])}
    fake = {frozenset("ACD"): 0.9, frozenset("ADF"): 0.9, frozenset("BEF"): 0.1, frozenset("AC"): 0.0}
    req = {**body(ids6, scores6), "nodeCoords": coords}
    real, real_wp, real_ext = optimize.osrm_overlap, optimize.make_waypoints, optimize.extend
    optimize.make_waypoints = lambda coords, km: []       # 이 부분은 경유지 없이 (#31)
    optimize.osrm_overlap = lambda pts: fake.get(frozenset(names[q] for q in pts[1:-1]), 0.5)
    try:
        r = c.post("/optimize", json=req).json()       # 겹침 0인 A+C는 점수가 너무 낮아 제외 → B+E+F
        assert r["found"] and set(r["orderedPlaceIds"]) == set("BEF") and r["overlapRatio"] == 0.1 and r["totalKm"] == 4.8, r
        print("왕복 심한 1등 대신:", r["orderedPlaceIds"], r["totalKm"], "km")

        def down(pts):
            raise OSError("OSRM 꺼짐")
        optimize.osrm_overlap = down                   # OSRM이 안 되면 예전처럼 점수 최고 + overlapRatio null
        r = c.post("/optimize", json=req).json()
        assert set(r["orderedPlaceIds"]) in ({"A", "C", "D"}, {"A", "D", "F"}) and r["overlapRatio"] is None, r
        assert [x["placeId"] for x in r["stops"]] == r["orderedPlaceIds"], r

        # 우회 경유지 (#33): 경유지 좌표는 위도로 일직선 위치를 나타냄 (가짜 OSRM nearest·table)
        line = lambda lat: round((lat - 37.5) * 111_000)
        optimize.extend = lambda dist, cs, wps: [[abs(line(a[0]) - line(b[0])) for b in [*cs, *wps]] for a in [*cs, *wps]]
        W = lambda m: (37.5 + m / 111_000, 127.0)
        # 1) A(1500m)만으로는 5km가 안 됨(3km) → 반대편 경유지(−1200m)로 채워 S→A→W→S 5.4km
        optimize.make_waypoints = lambda coords, km: [W(-1200)]
        optimize.osrm_overlap = lambda pts: 0.2
        one = [(37.5, 127.0), (37.5 + 1500 / 111_000, 127.0), (37.5, 127.0)]
        r = c.post("/optimize", json={**body(["A"], [0.9]), "nodeCoords": one}).json()
        assert r["found"] and r["orderedPlaceIds"] == ["A"] and r["totalKm"] == 5.4, r
        assert [x["type"] for x in r["stops"]] in (["PLACE", "WAYPOINT"], ["WAYPOINT", "PLACE"]), r
        # 2) 점수가 같으면 겹침이 적은 쪽: A+C+D(4.6km, 겹침 0.9)에 경유지(−200m)를 넣은 5.0km 코스가 겹침 0.05
        optimize.make_waypoints = lambda coords, km: [W(-200)]
        wp = W(-200)
        optimize.osrm_overlap = lambda pts: 0.05 if wp in pts else fake.get(frozenset(names[q] for q in pts[1:-1]), 0.5)
        r = c.post("/optimize", json=req).json()
        assert r["found"] and set(r["orderedPlaceIds"]) == set("ACD") and r["overlapRatio"] == 0.05 and r["totalKm"] == 5.0, r
        assert sum(x["type"] == "WAYPOINT" for x in r["stops"]) == 1, r
        # 3) 경유지 코스가 더 나쁘면 쓰지 않음 (지금 방식보다 나빠지지 않음)
        optimize.osrm_overlap = lambda pts: 0.99 if wp in pts else fake.get(frozenset(names[q] for q in pts[1:-1]), 0.5)
        r = c.post("/optimize", json=req).json()
        assert set(r["orderedPlaceIds"]) == set("BEF") and r["overlapRatio"] == 0.1 and all(x["type"] == "PLACE" for x in r["stops"]), r
        # 4) 경유지 만들기가 실패하면 장소만으로
        def wp_down(coords, km):
            raise OSError("OSRM 꺼짐")
        optimize.make_waypoints = wp_down
        optimize.osrm_overlap = lambda pts: fake.get(frozenset(names[q] for q in pts[1:-1]), 0.5)
        r = c.post("/optimize", json=req).json()
        assert set(r["orderedPlaceIds"]) == set("BEF") and r["overlapRatio"] == 0.1, r
        print("우회 경유지: 거리 채우기·겹침 적은 쪽·나빠지지 않음·실패 대체 확인")
    finally:
        optimize.osrm_overlap, optimize.make_waypoints, optimize.extend = real, real_wp, real_ext
    # 겹침 계산: 1→2→3→2→1 (같은 길 왕복 전부) / 1→2→3 + 3→4 (겹침 없음)
    leg = lambda ns, ds: {"annotation": {"nodes": ns, "distance": ds}}
    assert optimize.overlap_of([leg([1, 2, 3], [10, 30]), leg([3, 2, 1], [30, 10])]) == 1.0
    assert optimize.overlap_of([leg([1, 2, 3], [10, 30]), leg([3, 4], [60])]) == 0.0
    assert optimize.overlap_of([leg([1, 2, 3], [10, 30]), leg([3, 2, 5], [30, 30])]) == 0.6
    print("같은 길 왕복 줄이기·OSRM 실패 대체·겹침 계산 확인")

    bad = [
        ("거리표 크기", {**body(ids, scores), "distanceMatrixM": matrix(["S", "A", "T"])}),
        ("점수 개수", {**body(ids, scores), "scores": [0.9]}),
        ("장소 중복", body(["A", "A"], [0.9, 0.8])),
        ("음수 거리", {**body(["A"], [0.9]), "distanceMatrixM": [[0, -1, 0], [1, 0, 1], [0, 1, 0]]}),
        ("목표 거리 0", body(ids, scores, km=0)),
        ("좌표 개수", {**body(["A"], [0.9]), "nodeCoords": [[37.5, 127.0]] * 2}),
        ("좌표 범위", {**body(["A"], [0.9]), "nodeCoords": [[37.5, 127.0], [137.5, 127.0], [37.5, 127.0]]}),
        ("maxPlaces 0", body(ids, scores, max_places=0)),
        ("장소 51곳", {**body(["A"], [0.9]), "placeIds": [f"P{i}" for i in range(51)], "scores": [0.5] * 51,
                     "distanceMatrixM": [[0] * 53 for _ in range(53)]}),
    ]
    for name, b in bad:
        r = c.post("/optimize", json=b)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR" and r.json()["message"], (name, r.text)
    print(f"요청 오류 {len(bad)}가지 확인")


if __name__ == "__main__":
    with TestClient(app) as c:
        main(c)
    print("점검 통과")
