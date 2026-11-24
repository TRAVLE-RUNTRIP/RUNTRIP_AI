"""AI 파트 시연용 지도 데모. BE 대신 코스 생성 순서(API 명세 B-4)를 흉내 내고, 결과를 지도에 그림.
후보 조회(직선거리) → /recommend → 상위 40곳 → OSRM 거리표 → /optimize → OSRM 경로선 → /safety, 추천 이유(/reasons)는 코스를 먼저 보여 준 뒤 따로 호출

실행 (파이썬 기본 라이브러리만 씀):
  1) EC2의 AI 서버·OSRM을 내 PC로 연결 (창을 열어 둠)
     ssh -i ~/.ssh/runtrip.pem -N -L 8000:127.0.0.1:8000 -L 5000:127.0.0.1:5000 ubuntu@15.134.44.138
  2) 레포 루트에서  python demo/server.py   →  브라우저에서 http://127.0.0.1:8080 (같은 와이파이의 휴대폰은 실행 때 찍히는 http://<PC IP>:8080)
로컬에서 docker compose로 띄운 AI 서버·OSRM이 있으면 1)은 필요 없음. 주소는 환경 변수 AI_URL·OSRM_URL로 바꿀 수 있음
AI 서버에 API 키를 설정했으면 환경 변수 AI_API_KEY에 같은 키를 넣고 실행"""
import csv
import json
import math
import os
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
AI = os.environ.get("AI_URL", "http://127.0.0.1:8000")
OSRM = os.environ.get("OSRM_URL", "http://127.0.0.1:5000")
PORT = 8080
HOST = os.environ.get("HOST", "0.0.0.0")   # 같은 와이파이의 휴대폰·다른 PC에서도 접속 (내 PC만이면 HOST=127.0.0.1)
TOP = 40
KMS = {3, 5, 7, 10}
PREFS = {"NIGHT_VIEW", "ATTRACTION", "NATURE"}
SEOUL = (37.40, 37.72, 126.75, 127.20)               # 위도·경도 범위 (서울 밖 클릭 막기)

# 후보 규칙·장소 수는 server/bench_optimize.py와 같음 (그쪽은 FastAPI가 필요해 여기선 다시 씀)
places = {r["place_id"]: r for r in csv.DictReader(open(ROOT.parent / "data" / "places.csv", encoding="utf-8-sig"))}
pool = [p for p in places.values() if p["category"] != "기타"]


def max_places(km):
    return 2 if km <= 3 else 3 if km <= 7 else 4 if km <= 14 else 5


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    return 2 * 6371 * math.asin(math.sqrt(math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2))


def get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.load(r)


def post(path, body):
    req = urllib.request.Request(AI + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json", "X-API-Key": os.environ.get("AI_API_KEY", "")})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"AI 서버 {path} {e.code}: {e.read().decode(errors='replace')[:200]}") from e


def osrm(kind, pts, q):
    return get(f"{OSRM}/{kind}/v1/foot/" + ";".join(f"{lng:.6f},{lat:.6f}" for lat, lng in pts) + q)


def course(req):
    s = tuple(req["start"])
    e = tuple(req.get("end") or req["start"])
    km, prefs, night = req["km"], req["preferences"], bool(req["isNight"])
    t, steps = time.perf_counter(), []

    def lap(name):
        nonlocal t
        now = time.perf_counter()
        steps.append({"name": name, "ms": round((now - t) * 1000)})
        t = now

    D = hav(s, e)
    if D > km / 1.1:
        raise ValueError(f"출발지와 도착지 직선거리({D:.1f}km)가 목표 거리에 비해 너무 멀어요")
    cand = []
    for p in pool:
        x = (float(p["lat"]), float(p["lng"]))
        d = hav(s, x) + hav(x, e)
        if d <= km / 1.3:
            cand.append((p["place_id"], (d - D) / km, x))
    if not cand:
        raise ValueError("주변에 후보 장소가 없어요. 출발지를 옮기거나 거리를 늘려 보세요")
    lap("후보 조회")
    sc = post("/recommend", {"preferences": prefs, "isNight": night,
                             "candidates": [{"placeId": p, "detourRatio": dr} for p, dr, _ in cand]})["scores"]
    lap("/recommend")
    top = sorted(zip(cand, (x["score"] for x in sc)), key=lambda z: -z[1])[:TOP]
    ids, scores, pts = [z[0][0] for z in top], [z[1] for z in top], [z[0][2] for z in top]
    m = [[round(v) for v in row] for row in osrm("table", [s, *pts, e], "?annotations=distance")["distances"]]
    lap("OSRM 거리표")
    res = post("/optimize", {"targetKm": km, "maxPlaces": max_places(km), "timeLimitMs": 500, "placeIds": ids,
                             "scores": scores, "distanceMatrixM": m, "excludedCombos": req.get("excluded", []),
                             "nodeCoords": [s, *pts, e]})     # 있으면 AI 서버가 같은 길 왕복이 적은 코스를 고름
    lap("/optimize")
    if not res["found"]:
        raise ValueError("조건에 맞는 코스를 찾지 못했어요" + (" (더 만들 수 있는 코스가 없어요)" if req.get("excluded") else ""))
    order = res["orderedPlaceIds"]
    pos = lambda x: (float(places[x["placeId"]]["lat"]), float(places[x["placeId"]]["lng"])) if x["type"] == "PLACE" else (x["lat"], x["lng"])
    seq = res.get("stops") or [{"type": "PLACE", "placeId": p} for p in order]     # 우회 경유지(#33)까지 방문 순서대로
    r = osrm("route", [s, *map(pos, seq), e], "?overview=full&geometries=geojson")["routes"][0]
    path = [[lat, lng] for lng, lat in r["geometry"]["coordinates"]]
    lap("OSRM 경로선")
    safety = post("/safety", {"path": path, "isNight": night})
    lap("/safety")
    score_of = dict(zip(ids, scores))
    return {"path": path, "routeKm": round(r["distance"] / 1000, 2), "candidates": len(cand), "order": order, "steps": steps,
            "overlap": res.get("overlapRatio"),
            "waypoints": [[x["lat"], x["lng"]] for x in seq if x["type"] == "WAYPOINT"],
            "safety": safety,
            "places": [{"placeId": p, "name": places[p]["title"], "category": places[p]["category"], "lat": la, "lng": lo,
                        "nightSpot": places[p]["night_spot"] == "1", "score": round(score_of[p], 3)}
                       for p, (la, lo) in ((p, pos({"type": "PLACE", "placeId": p})) for p in order)]}


def reasons(req):
    t = time.perf_counter()
    body = {"preferences": req["preferences"], "isNight": bool(req["isNight"]), "places": [
        {"placeId": p, "name": places[p]["title"], "overview": places[p]["overview"] or None,
         "evidence": (["night_spot"] if places[p]["night_spot"] == "1" else []) + ["취향 유사도 높음"]} for p in req["order"]]}
    try:
        out = post("/reasons", body)["reasons"]
    except RuntimeError:
        out = [{"placeId": p, "reason": None, "usedEvidence": []} for p in req["order"]]   # BE처럼 실패하면 개요로 대체
    for o in out:
        if o["reason"] is None:
            o["fallback"] = (places[o["placeId"]]["overview"] or "")[:80] or None
    return {"reasons": out, "ms": round((time.perf_counter() - t) * 1000)}


def check(req, need_order=False):
    """브라우저 입력 검사 (이 데모 서버가 받는 값만)"""
    ok = isinstance(req.get("preferences"), list) and req["preferences"] and set(req["preferences"]) <= PREFS
    if need_order:
        return ok and isinstance(req.get("order"), list) and 0 < len(req["order"]) <= 10 and all(p in places for p in req["order"])
    pts = [req.get("start")] + ([req["end"]] if req.get("end") else [])
    in_seoul = all(isinstance(q, list) and len(q) == 2 and all(isinstance(v, (int, float)) for v in q)
                   and SEOUL[0] <= q[0] <= SEOUL[1] and SEOUL[2] <= q[1] <= SEOUL[3] for q in pts)
    return ok and in_seoul and req.get("km") in KMS and isinstance(req.get("excluded", []), list)


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self.send(200, (ROOT / "index.html").read_bytes(), "text/html; charset=utf-8")
        self.send(404, {"error": "없는 주소예요"})

    def do_POST(self):
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/course" and check(req):
                return self.send(200, course(req))
            if self.path == "/api/reasons" and check(req, need_order=True):
                return self.send(200, reasons(req))
            self.send(400, {"error": "요청 값이 올바르지 않아요"})
        except ValueError as e:                        # 코스를 못 만든 경우 (사용자에게 보여 줄 문구)
            self.send(422, {"error": str(e)})
        except (OSError, RuntimeError, KeyError) as e:  # AI 서버·OSRM 연결 실패 (터널 확인)
            self.send(502, {"error": f"AI 서버·OSRM 호출 실패: {e}. SSH 터널이 켜져 있는지 확인하세요"})

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    import socket
    lan = socket.gethostbyname(socket.gethostname())
    print(f"RUN+Trip AI 데모: http://127.0.0.1:{PORT}" + (f" · 같은 네트워크에서 http://{lan}:{PORT}" if HOST == "0.0.0.0" else "") + f"  (AI {AI}, OSRM {OSRM})")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
