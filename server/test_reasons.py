"""/reasons 점검 (Gemini 없이 가짜 응답으로). 레포 루트에서  python -m server.test_reasons
1) 근거 검증: 받지 않은 근거·개요에 없는 숫자·근거 없는 야경·너무 긴 문장 → reason null
2) 요청에 없는 장소는 응답에 안 나오고, Gemini가 빠뜨린 장소는 null, 응답은 요청 순서
3) Gemini 실패(키 없음·응답 형식 오류) → 502 REASON_FAILED, 요청 오류 → 400
실제 Gemini로 보려면 GEMINI_API_KEY를 설정하고  python -m server.test_reasons --live"""
import json
import sys

from fastapi.testclient import TestClient

import server.reasons as R
from server.app import app

PLACES = [
    {"placeId": "A", "name": "덕수궁 돌담길", "overview": "덕수궁을 따라 이어진 돌담길로, 1.1km 길이의 산책로다.", "evidence": ["night_spot", "취향 유사도 높음"]},
    {"placeId": "B", "name": "서울숲", "overview": "2005년 문을 연 도시 숲이다.", "evidence": ["취향 유사도 높음"]},
    {"placeId": "C", "name": "청계천", "overview": None, "evidence": ["취향 유사도 높음"]},
]
BODY = {"preferences": ["NIGHT_VIEW"], "isNight": True, "places": PLACES}


def fake(reasons):
    R.call_gemini = lambda text: json.dumps({"reasons": reasons}, ensure_ascii=False)


def main(c):
    fake([
        {"placeId": "C", "reason": "도심 속 물길을 따라 달리기 좋아요", "usedEvidence": ["취향 유사도 높음"]},
        {"placeId": "A", "reason": "돌담을 따라 조명이 이어져 밤에도 걷기 편해요", "usedEvidence": ["night_spot"]},
        {"placeId": "B", "reason": "2005년 문을 연 숲에서 야경을 즐길 수 있어요", "usedEvidence": ["취향 유사도 높음"]},   # 근거 없는 야경
        {"placeId": "Z", "reason": "요청에 없는 장소예요", "usedEvidence": ["취향 유사도 높음"]},
    ])
    r = c.post("/reasons", json=BODY)
    assert r.status_code == 200, r.text
    got = r.json()["reasons"]
    assert [x["placeId"] for x in got] == ["A", "B", "C"], got                       # 요청 순서, Z 없음
    assert got[0]["reason"].startswith("돌담을") and got[0]["usedEvidence"] == ["night_spot"], got
    assert got[1] == {"placeId": "B", "reason": None, "usedEvidence": []}, got
    assert got[2]["reason"] is not None, got                                          # 개요 없어도 근거로 설명

    bad = [("A", "돌담길 2km 산책로예요", ["night_spot"]),                            # 개요에 없는 숫자 (1.1km만 있음)
           ("A", "덕수궁 돌담길이에요", ["인기 장소"]),                                  # 받지 않은 근거
           ("A", "덕수궁 돌담길이에요", []),                                            # 근거 안 씀
           ("A", "가" * 81, ["night_spot"])]                                          # 너무 김
    for pid, text, used in bad:
        fake([{"placeId": pid, "reason": text, "usedEvidence": used}])
        assert c.post("/reasons", json=BODY).json()["reasons"][0]["reason"] is None, (text, used)
    fake([{"placeId": "B", "reason": "2005년 문을 연 도시 숲이에요", "usedEvidence": ["취향 유사도 높음"]}])
    out = c.post("/reasons", json=BODY).json()["reasons"]
    assert out[1]["reason"] is not None and out[0]["reason"] is None, out              # 개요에 있는 숫자는 통과, 빠뜨린 A는 null

    def one(pid, text, used, night=True):
        fake([{"placeId": pid, "reason": text, "usedEvidence": used}])
        out = c.post("/reasons", json=dict(BODY, isNight=night)).json()["reasons"]
        return next(x["reason"] for x in out if x["placeId"] == pid)
    assert one("B", "200년 역사의 숲이에요", ["취향 유사도 높음"]) is None                # "200"은 "2005"의 일부일 뿐
    assert one("A", "1km 산책로예요", ["night_spot"]) is None and one("A", "1.1km 산책로예요", ["night_spot"])
    assert one("C", "밤에도 물길을 따라 달리기 좋아요", ["취향 유사도 높음"])              # 밤 코스에서 시간만 말하면 통과
    assert one("C", "밤에도 물길을 따라 달리기 좋아요", ["취향 유사도 높음"], night=False) is None
    assert one("C", "물길에 불빛이 비쳐 예뻐요", ["취향 유사도 높음"]) is None              # 근거 없는 밤 풍경
    assert one("A", "야경이 아름다워요", ["취향 유사도 높음"]) is None                      # night_spot을 받았어도 안 썼다고 함

    # 형식만 이상한 장소는 그 장소만 null, 응답 전체가 이상하면 502
    fake([{"placeId": ["A"], "reason": "x", "usedEvidence": ["night_spot"]},
          {"placeId": "B", "reason": "2005년 문을 연 도시 숲이에요", "usedEvidence": [{"x": 1}]},
          {"placeId": "C", "reason": "청계천을 따라 달려요", "usedEvidence": ["취향 유사도 높음"]}])
    out = c.post("/reasons", json=BODY)
    assert out.status_code == 200 and [x["reason"] is None for x in out.json()["reasons"]] == [True, True, False], out.text
    R.call_gemini = lambda text: json.dumps({"reasons": 5})
    assert c.post("/reasons", json=BODY).status_code == 502

    R.call_gemini = lambda text: "not json"
    r = c.post("/reasons", json=BODY)
    assert r.status_code == 502 and r.json()["code"] == "REASON_FAILED", r.text
    R.call_gemini = ORIGINAL
    r = c.post("/reasons", json=BODY)                                                 # 키 없음
    assert r.status_code == 502 and r.json()["code"] == "REASON_FAILED", r.text

    for body in [dict(BODY, places=[]), dict(BODY, places=PLACES[:1] * 2), dict(BODY, preferences=[]),
                 dict(BODY, places=[dict(PLACES[0], evidence=[])])]:
        r = c.post("/reasons", json=body)
        assert r.status_code == 400 and r.json()["code"] == "VALIDATION_ERROR", r.text


def live(c):
    import time
    t = time.perf_counter()
    r = c.post("/reasons", json=BODY)
    print(f"{(time.perf_counter() - t) * 1000:.0f}ms", r.status_code, json.dumps(r.json(), ensure_ascii=False, indent=1))


ORIGINAL = R.call_gemini

if __name__ == "__main__":
    with TestClient(app) as c:
        if "--live" in sys.argv:
            live(c)
        else:
            import os
            os.environ.pop("GEMINI_API_KEY", None)
            main(c)
            print("점검 통과")
