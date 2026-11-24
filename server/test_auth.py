"""API 키 검사 (AI_API_KEY). 레포 루트에서  python -m server.test_auth"""
from fastapi.testclient import TestClient

import server.app as app_mod
from server.app import app

BODY = {"preferences": ["NIGHT_VIEW"], "isNight": True, "candidates": []}


def main(c):
    app_mod.API_KEY = "test-key"
    try:
        for headers in ({}, {"X-API-Key": "wrong"}):
            r = c.post("/recommend", json=BODY, headers=headers)
            assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED", r.text
        r = c.post("/recommend", json={}, headers={})          # 키 검사가 요청 형식 검사보다 먼저
        assert r.status_code == 401, r.text
        assert c.post("/recommend", json=BODY, headers={"X-API-Key": "test-key"}).status_code == 200
        assert c.get("/health").status_code == 200 and c.get("/docs").status_code == 200
        assert "X-API-Key" in c.get("/openapi.json").text       # /docs의 Authorize 버튼
        assert c.get("/nope", headers={"X-API-Key": "test-key"}).json()["code"] == "RESOURCE_NOT_FOUND"
    finally:
        app_mod.API_KEY = ""
    assert c.post("/recommend", json=BODY).status_code == 200    # 키 설정이 없으면 검사 안 함 (로컬 개발)
    print("API 키 검사 확인")


if __name__ == "__main__":
    with TestClient(app) as c:
        main(c)
    print("점검 통과")
