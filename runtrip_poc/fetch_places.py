"""TourAPI(국문 관광정보 서비스 GW)로 테스트 지역 장소를 모아 data/places.jsonl 생성.

사용:
  set TOUR_API_KEY=발급받은_Decoding_키          (맥: export TOUR_API_KEY=...)
  python fetch_places.py --probe       # 1) 응답 형식 확인 (원본 1건 출력)
  python fetch_places.py               # 2) 목록 수집 → 개요 수집 → places.jsonl

- 목록: 위치기반 조회(출발지 좌표 + 반경)로 장소 목록
- 개요: 장소마다 공통정보 조회 1번씩 (KURE가 읽을 소개글)
- 일일 호출 제한에 걸리면 진행 상황을 저장하고 멈춰요. 다음 날 다시 실행하면 이어서 받아요.
"""
import argparse, html, json, os, re, time
import requests
import config as C
from common import read_jsonl, write_jsonl
from data_gen import ORIGINS

BASE = "https://apis.data.go.kr/B551011/KorService2"
LIST_OP = "locationBasedList2"     # TODO: 활용신청 상세 페이지의 오퍼레이션 이름과 다르면 수정
DETAIL_OP = "detailCommon2"
RADIUS_M = 5000                     # 출발지마다 반경 5km (10km 코스 후보 검색 반경을 넉넉히 포함)

# 콘텐츠타입 ID → 우리 카테고리 (숙박 32, 여행코스 25, 행사 15는 경유지가 아니라서 제외)
CONTENT_TYPES = {"12": "관광지", "14": "문화시설", "28": "기타", "38": "쇼핑", "39": "음식점"}
NATURE_WORDS = ("공원", "숲", "한강", "천", "호수", "정원", "산책로", "둘레길")

CACHE = C.DATA_DIR / "overview_cache.jsonl"
LIST_FILE = C.DATA_DIR / "places_list.jsonl"


class QuotaExceeded(Exception):
    pass


def _call_once(op, params):
    key = os.environ["TOUR_API_KEY"]
    q = {"serviceKey": key, "MobileOS": "ETC", "MobileApp": "RunTrip", "_type": "json", **params}
    r = requests.get(f"{BASE}/{op}", params=q, timeout=15)
    text = r.text.strip()
    if r.status_code == 429 or "LIMITED" in text:
        raise QuotaExceeded(text[:200])
    if not text.startswith("{"):                    # 키 오류·호출 초과는 XML로 오는 경우가 많음
        if "22" in re.findall(r"<returnReasonCode>(\d+)", text):
            raise QuotaExceeded(text[:200])
        raise RuntimeError(f"JSON이 아닌 응답 (HTTP {r.status_code}):\n{text[:300]}")
    data = r.json()
    if "response" not in data:                      # 게이트웨이 오류는 다른 형식의 JSON으로 와요
        code, msg = str(data.get("resultCode", "")), str(data.get("resultMsg", ""))
        if code == "22" or "LIMIT" in msg.upper() or "초과" in msg:
            raise QuotaExceeded(msg)
        raise RuntimeError(f"예상과 다른 응답 (HTTP {r.status_code}): {json.dumps(data, ensure_ascii=False)[:300]}")
    header = data["response"]["header"]
    if header.get("resultCode") not in ("0000", "00"):
        if str(header.get("resultCode")) == "22":
            raise QuotaExceeded(str(header))
        raise RuntimeError(f"API 오류 {header}")
    return data["response"]["body"]


def call(op, retries=3, **params):
    """일시적 오류는 잠깐 쉬고 다시 시도. 호출 제한은 바로 멈춤"""
    for attempt in range(retries):
        try:
            return _call_once(op, params)
        except QuotaExceeded:
            raise
        except (RuntimeError, requests.RequestException, ValueError) as e:
            if attempt == retries - 1:
                raise
            print(f"  일시 오류, {2 ** (attempt + 1)}초 후 재시도: {str(e)[:120]}")
            time.sleep(2 ** (attempt + 1))


def items_of(body):
    """items가 비어 있으면 '' 이고, 1건이면 dict로 와서 리스트로 통일"""
    items = body.get("items") or {}
    item = items.get("item", []) if isinstance(items, dict) else []
    return [item] if isinstance(item, dict) else item


def to_category(it):
    cat = CONTENT_TYPES.get(str(it.get("contenttypeid")))
    if cat is None:
        return None
    is_nature = (it.get("cat1") == "A01" or it.get("lclsSystm1") == "NA"
                 or any(w in it.get("title", "") for w in NATURE_WORDS))
    return "공원·자연" if cat == "관광지" and is_nature else cat


def clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def collect_list():
    places = {}
    for region, (lat, lng) in ORIGINS.items():
        page, total = 1, None
        while total is None or (page - 1) * 100 < total:
            body = call(LIST_OP, mapX=lng, mapY=lat, radius=RADIUS_M, numOfRows=100, pageNo=page, arrange="E")
            total = int(body.get("totalCount", 0))
            for it in items_of(body):
                cat = to_category(it)
                if cat is None or not it.get("mapx"):
                    continue
                places[str(it["contentid"])] = {
                    "place_id": str(it["contentid"]), "name": it["title"], "category": cat,
                    "lat": float(it["mapy"]), "lng": float(it["mapx"]),
                    "content_type_id": str(it["contenttypeid"]), "addr": it.get("addr1", ""),
                    "image": it.get("firstimage", ""), "image_license": it.get("cpyrhtDivCd", ""),
                    "region": region,
                }
            page += 1
            time.sleep(0.1)
        print(f"{region}: 누적 {len(places)}개 (이 지역 전체 {total}건)")
    write_jsonl(LIST_FILE, list(places.values()))
    return list(places.values())


def collect_overviews(places):
    done = {r["place_id"]: r["overview"] for r in read_jsonl(CACHE)} if CACHE.exists() else {}
    todo = [p for p in places if p["place_id"] not in done]
    print(f"개요: 이미 받음 {len(done)}개, 남음 {len(todo)}개")
    with open(CACHE, "a", encoding="utf-8") as f:
        for i, p in enumerate(todo, 1):
            try:
                body = call(DETAIL_OP, contentId=p["place_id"])
            except QuotaExceeded as e:
                print(f"일일 호출 제한 도달 ({str(e)[:80]}). 지금까지 받은 개요는 저장됨 → 내일 --skip-list로 이어서 받아요.")
                return done, False
            except Exception as e:
                print(f"  건너뜀 {p['place_id']} {p['name']}: {str(e)[:120]}")
                continue
            its = items_of(body)
            ov = clean(its[0].get("overview")) if its else ""
            done[p["place_id"]] = ov
            f.write(json.dumps({"place_id": p["place_id"], "overview": ov}, ensure_ascii=False) + "\n")
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}")
            time.sleep(0.1)
    return done, True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true", help="목록 1건 + 개요 1건 원본 출력")
    ap.add_argument("--skip-list", action="store_true", help="목록은 이미 받았으면 생략")
    args = ap.parse_args()
    C.DATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.probe:
        lat, lng = next(iter(ORIGINS.values()))
        body = call(LIST_OP, mapX=lng, mapY=lat, radius=1000, numOfRows=1, pageNo=1, arrange="E")
        it = items_of(body)
        print("목록 원본:", json.dumps(it[:1], ensure_ascii=False, indent=2))
        if it:
            d = items_of(call(DETAIL_OP, contentId=it[0]["contentid"]))
            d = d[0] if d else {}
            print("개요 응답 필드:", list(d.keys()))
            print("overview 있음:", "overview" in d, "/ 앞부분:", clean(d.get("overview"))[:150])
        return

    places = read_jsonl(LIST_FILE) if args.skip_list and LIST_FILE.exists() else collect_list()
    overviews, finished = collect_overviews(places)
    for p in places:
        p["overview"] = overviews.get(p["place_id"], "")
    write_jsonl(C.DATA_DIR / "places.jsonl", places)

    cats = {}
    for p in places:
        cats[p["category"]] = cats.get(p["category"], 0) + 1
    empty = sum(1 for p in places if not p["overview"])
    print(f"places.jsonl 저장: {len(places)}개 {cats}, 개요 없음 {empty}개")
    if not finished:
        print("※ 개요가 덜 받아졌어요. 내일 `python fetch_places.py --skip-list`로 이어서 받으세요.")


if __name__ == "__main__":
    main()
