"""TourAPI(KorService2) 서울 장소 수집. 중간에 끊겨도 다시 실행하면 이어서 받는다.

출력: data/raw/tourapi_list.json (목록), data/raw/tourapi_overview.jsonl (contentid별 개요)
실행: TOURAPI_KEY 환경변수 필요 (Decoding 키)
"""
import json, os, sys, time, urllib.parse, urllib.request
from pathlib import Path

KEY = os.environ["TOURAPI_KEY"]
BASE = "https://apis.data.go.kr/B551011/KorService2/"
CONTENT_TYPES = [12, 14, 28]  # 관광지, 문화시설, 레포츠
RAW = Path(__file__).parent / "raw"
LIST_PATH = RAW / "tourapi_list.json"
OVERVIEW_PATH = RAW / "tourapi_overview.jsonl"


def call(op, **params):
    q = {"serviceKey": KEY, "MobileOS": "ETC", "MobileApp": "RUNTrip", "_type": "json", **params}
    url = BASE + op + "?" + urllib.parse.urlencode(q)
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            body = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        sys.exit(f"[중단] {op} HTTP {e.code} (429면 일일 한도 초과 → 내일 다시 실행하면 이어받기)")
    try:
        data = json.loads(body)
        code = data["response"]["header"]["resultCode"]
    except (json.JSONDecodeError, KeyError):
        # 한도 초과·인증 오류는 XML/비정상 응답으로 온다 → 중단 후 재실행으로 이어받기
        sys.exit(f"[중단] {op} 비정상 응답: {body[:300].replace(KEY, '***')}")
    if code != "0000":
        sys.exit(f"[중단] {op} resultCode={code}: {data['response']['header'].get('resultMsg')}")
    items = data["response"]["body"].get("items") or {}
    return items.get("item", []) if isinstance(items, dict) else [], data["response"]["body"]["totalCount"]


def collect_list():
    if LIST_PATH.exists():
        return json.loads(LIST_PATH.read_text(encoding="utf-8"))
    # areacode가 비어 있는 장소(예: 경복궁)가 있어 신규 법정동 코드(lDongRegnCd=11)로도 받아 합친다
    by_id = {}
    for t in CONTENT_TYPES:
        for region in ({"areaCode": 1}, {"lDongRegnCd": 11}):
            page = 1
            while True:
                items, total = call("areaBasedList2", numOfRows=1000, pageNo=page, contentTypeId=t, **region)
                by_id.update({p["contentid"]: p for p in items})
                if page * 1000 >= total:
                    break
                page += 1
            print(f"contentTypeId={t} {region}: {total}건")
    places = list(by_id.values())
    LIST_PATH.write_text(json.dumps(places, ensure_ascii=False, indent=1), encoding="utf-8")
    return places


def collect_overviews(places):
    done = set()
    if OVERVIEW_PATH.exists():
        done = {json.loads(l)["contentid"] for l in OVERVIEW_PATH.read_text(encoding="utf-8").splitlines() if l}
    todo = [p["contentid"] for p in places if p["contentid"] not in done]
    print(f"개요: 완료 {len(done)} / 남음 {len(todo)}")
    with OVERVIEW_PATH.open("a", encoding="utf-8") as f:
        for i, cid in enumerate(todo, 1):
            items, _ = call("detailCommon2", contentId=cid)
            overview = items[0].get("overview", "") if items else ""
            f.write(json.dumps({"contentid": cid, "overview": overview}, ensure_ascii=False) + "\n")
            f.flush()
            if i % 50 == 0:
                print(f"  {i}/{len(todo)}")
            time.sleep(0.1)


if __name__ == "__main__":
    RAW.mkdir(parents=True, exist_ok=True)
    places = collect_list()
    print(f"목록 합계: {len(places)}건")
    collect_overviews(places)
    print("완료")
