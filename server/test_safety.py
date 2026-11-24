"""/safety 점검. 레포 루트에서  pip install -r server/requirements-dev.txt  →  python -m server.test_safety
1) 구간 위치 → path 인덱스 변환 (점 사이에 낀 짧은 구간, 빈틈·겹침)
2) 서울 경로: B4 형식, segments가 path 처음~끝을 빈틈·겹침 없이 덮음
3) 보안등 자료 밖(부산) 경로도 오류 없이 '자료없음'
4) 오류 응답 형식 {code, message}
5) 5km·10km 응답 시간 (서버 안 처리 시간, TestClient. 이슈 #10 목표 500ms)"""
import time

import numpy as np
from fastapi.testclient import TestClient

from server.app import app
from server.safety_course import WALK_WARN, to_indices


def line(lat0, lng0, lat1, lng1, n):
    return [[lat0 + (lat1 - lat0) * i / (n - 1), lng0 + (lng1 - lng0) * i / (n - 1)] for i in range(n)]


def check_indices():
    cum = np.array([0, 100, 200, 300, 400.0])
    segs = [{"start_m": 0, "end_m": 120, "grade": "많음"}, {"start_m": 120, "end_m": 140, "grade": "적음"},   # 20m 구간은 점 사이에 끼어 빠짐
            {"start_m": 140, "end_m": 290, "grade": "많음"}, {"start_m": 290, "end_m": 400, "grade": "보통"}]
    assert to_indices(cum, segs) == [{"fromIndex": 0, "toIndex": 3, "grade": "많음"}, {"fromIndex": 3, "toIndex": 4, "grade": "보통"}]
    first_short = [{"start_m": 0, "end_m": 30, "grade": "적음"}, {"start_m": 30, "end_m": 400, "grade": "많음"}]
    assert to_indices(cum, first_short) == [{"fromIndex": 0, "toIndex": 4, "grade": "많음"}]


def check_course(c, path, night=True):
    r = c.post("/safety", json={"path": path, "isNight": night})
    assert r.status_code == 200, r.text
    b = r.json()
    assert set(b) == {"score", "level", "coverage", "estimated", "hasLowSegment", "segments", "warnings"}, b
    s = b["segments"]
    assert s[0]["fromIndex"] == 0 and s[-1]["toIndex"] == len(path) - 1, s
    assert all(x["fromIndex"] < x["toIndex"] for x in s) and all(a["toIndex"] == b2["fromIndex"] for a, b2 in zip(s, s[1:])), s
    assert b["hasLowSegment"] == any(x["grade"] == "적음" for x in s)
    assert not any(w.endswith(tuple(WALK_WARN.values())) for w in b["warnings"]), b["warnings"]   # 보행 경고는 아직 안 냄
    return b


def errors(c):
    for body, part in [({"path": [[37.57, 126.98]], "isNight": True}, "path"),
                       ({"path": [[37.57, 126.98], [37.57, 126.98]], "isNight": True}, "서로 다른 점"),
                       ({"path": [[37.57, 126.98], [137.57, 126.98]], "isNight": True}, "범위"),
                       ({"path": [[37.57, 126.98], [37.58, 126.98]]}, "isNight")]:
        r = c.post("/safety", json=body)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR" and part in r.json()["message"], r.text


if __name__ == "__main__":
    check_indices()
    with TestClient(app) as c:
        jongno = line(37.5700, 126.9770, 37.5710, 127.0100, 120)            # 종로 따라 약 2.9km
        b = check_course(c, jongno)
        assert b["score"] is not None and b["level"] in {"좋음", "보통", "주의"}, b
        busan = check_course(c, line(35.1580, 129.1600, 35.1600, 129.1800, 50))   # 해운대: 보안등·도로 자료 밖
        assert busan["score"] is None and busan["level"] is None and {x["grade"] for x in busan["segments"]} == {"자료없음"}, busan
        errors(c)
        for km, path in [(5, line(37.5700, 126.9600, 37.5720, 127.0170, 250)), (10, line(37.5400, 126.9400, 37.5900, 127.0400, 500))]:
            check_course(c, path)
            ts = []
            for _ in range(5):
                t = time.perf_counter()
                c.post("/safety", json={"path": path, "isNight": True})
                ts.append((time.perf_counter() - t) * 1000)
            print(f"{km}km {len(path)}점: 중앙 {sorted(ts)[2]:.0f}ms, 최대 {max(ts):.0f}ms")
            assert max(ts) < 500, ts
    print("점검 통과")
