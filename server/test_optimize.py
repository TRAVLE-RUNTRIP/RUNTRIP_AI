"""/optimize 점검 (OSRM 없이, 정답을 아는 작은 거리표). 레포 루트에서  python -m server.test_optimize
실제 OSRM 거리표 검증은 server/bench_optimize.py"""
from fastapi.testclient import TestClient

from server.app import app

# 일직선 위의 점 (m): 출발지 0, 장소 A~E, 도착지 0 (순환). 거리 = 위치 차이
# 개선안 7장 표와 같게: A+B 왕복 7.8km(초과), A+C+D 4.6km(점수 합 2.47), B+E 4.8km(1.58)
POS = {"S": 0, "A": 1500, "B": -2400, "C": 2300, "D": 1000, "E": -2200, "T": 0}


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
    assert r == {"found": False, "orderedPlaceIds": [], "totalKm": None}, r
    print("답 없음·음수 점수·장소 수 상한 확인")

    bad = [
        ("거리표 크기", {**body(ids, scores), "distanceMatrixM": matrix(["S", "A", "T"])}),
        ("점수 개수", {**body(ids, scores), "scores": [0.9]}),
        ("장소 중복", body(["A", "A"], [0.9, 0.8])),
        ("음수 거리", {**body(["A"], [0.9]), "distanceMatrixM": [[0, -1, 0], [1, 0, 1], [0, 1, 0]]}),
        ("목표 거리 0", body(ids, scores, km=0)),
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
