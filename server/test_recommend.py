"""/recommend 점검. 레포 루트에서  pip install -r server/requirements-dev.txt  →  python -m server.test_recommend
1) data/queries.jsonl 전체를 API로 보내 data/features.npz로 계산한 학습 때 점수와 같은지 (features.py를 같은 KURE 결과로 다시 만든 뒤)
   모델 점수 = sigmoid(MLP + 가산점 × 취향 일치). 모델 파일이 없을 때 규칙 기준선으로 대신하는지도 확인
2) 오류 응답 형식 {code, message}
3) 후보 수별 응답 시간 (서버 안 처리 시간, TestClient)"""
import json, time
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient

from poc.evaluate import pref_match, rule_baseline
from server.app import app, state
from server.scoring import Scorer, mlp_logit

DATA = Path(__file__).resolve().parent.parent / "data"
PREF_API = {"야경": "NIGHT_VIEW", "관광 명소": "ATTRACTION", "자연·공원": "NATURE"}


def same_as_training(c):
    """features.npz가 없으면(git에 없음) 건너뛰고 False. 만드는 순서는 README 'AI 서버' 서빙 파일 항목"""
    if not (DATA / "features.npz").exists():
        print("학습 때 점수와 비교: 건너뜀 (data/features.npz 없음 → README 순서대로 embed_kure.py → build_serving.py → features.py 먼저)")
        return False
    queries = [json.loads(line) for line in (DATA / "queries.jsonl").read_text(encoding="utf-8").splitlines() if line]
    d = np.load(DATA / "features.npz")
    w = state["scorer"].model
    assert w is not None, "server/data/recommend_model.npz를 읽지 못함"
    base = 1 / (1 + np.exp(-(mlp_logit(w, d["X"]) + w["pref_bonus"] * pref_match(d["X"]))))
    worst = 0.0
    for qi, q in enumerate(queries):
        assert d["query_ids"][qi] == q["query_id"]
        body = {"preferences": [PREF_API[p] for p in q["prefs"]], "isNight": q["time_slot"] == "night",
                "candidates": [{"placeId": x["place_id"], "detourRatio": x["detour_km"] / q["target_km"]} for x in q["candidates"]]}
        r = c.post("/recommend", json=body)
        assert r.status_code == 200, r.text
        got = np.array([s["score"] for s in r.json()["scores"]])
        assert [s["placeId"] for s in r.json()["scores"]] == [x["place_id"] for x in q["candidates"]]
        worst = max(worst, float(np.abs(got - base[qi, :len(got)]).max()))
    print(f"학습 때 점수와 비교: 쿼리 {len(queries)}건, 점수 최대 차이 {worst:.2e}")
    assert worst < 1e-6

    q = queries[0]   # 모델 파일이 없으면 규칙 기준선으로 대신
    rule = Scorer(model=DATA / "없는_모델.npz")
    got = rule.score([PREF_API[p] for p in q["prefs"]], q["time_slot"] == "night", [x["place_id"] for x in q["candidates"]],
                     [x["detour_km"] / q["target_km"] for x in q["candidates"]])
    assert rule.model is None and np.abs(got - rule_baseline(d["X"][0, :len(got)])).max() < 1e-6
    print("모델 파일이 없을 때 규칙 기준선으로 대신: 확인")
    return True


def errors(c):
    ok = {"preferences": ["NATURE"], "isNight": False, "candidates": [{"placeId": "T1116925", "detourRatio": 0.4}]}
    cases = [
        ("취향 없음", "/recommend", {**ok, "preferences": []}, 400, "VALIDATION_ERROR"),
        ("없는 취향", "/recommend", {**ok, "preferences": ["FOOD"]}, 400, "VALIDATION_ERROR"),
        ("취향 중복", "/recommend", {**ok, "preferences": ["NATURE", "NATURE"]}, 400, "VALIDATION_ERROR"),
        ("음수 우회", "/recommend", {**ok, "candidates": [{"placeId": "T1116925", "detourRatio": -1}]}, 400, "VALIDATION_ERROR"),
        ("후보 2,001개", "/recommend", {**ok, "candidates": ok["candidates"] * 2001}, 400, "VALIDATION_ERROR"),
        ("없는 장소", "/recommend", {**ok, "candidates": [{"placeId": "NOPE", "detourRatio": 0.1}]}, 422, "UNKNOWN_PLACE"),
        ("없는 주소", "/nope", ok, 404, "RESOURCE_NOT_FOUND"),
    ]
    for name, path, body, status, code in cases:
        r = c.post(path, json=body)
        assert r.status_code == status and r.json()["code"] == code and r.json()["message"], (name, r.status_code, r.text)
    r = c.get("/recommend")
    assert r.status_code == 405 and r.json()["code"] == "METHOD_NOT_ALLOWED", r.text
    r = c.post("/recommend", json={**ok, "candidates": []})
    assert r.status_code == 200 and r.json() == {"scores": []}, r.text
    r = c.post("/recommend", json={**ok, "candidates": ok["candidates"] * 2000})   # 상한 2,000개까지는 정상
    assert r.status_code == 200 and len(r.json()["scores"]) == 2000, r.status_code
    print(f"오류 응답: {len(cases) + 3}가지 확인")


def timing(c, ids):
    for n in (40, 200, len(ids)):
        body = {"preferences": ["NIGHT_VIEW", "NATURE"], "isNight": True,
                "candidates": [{"placeId": p, "detourRatio": 0.3} for p in ids[:n]]}
        ts = []
        for _ in range(21):
            t = time.perf_counter()
            assert c.post("/recommend", json=body).status_code == 200
            ts.append((time.perf_counter() - t) * 1000)
        print(f"후보 {n}곳: 중앙값 {np.median(ts[1:]):.1f}ms, 최대 {max(ts[1:]):.1f}ms")


if __name__ == "__main__":
    with TestClient(app) as c:
        compared = same_as_training(c)
        errors(c)
        timing(c, list(state["scorer"].index))
    print("점검 통과" if compared else "점검 통과 (단, 학습 때 점수 비교는 안 함)")
