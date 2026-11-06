"""전국보안등정보표준데이터 API로 서울 구별 보안등을 받아 lamps/서울특별시_OO구_보안등정보.csv로 저장합니다.
파일 형식은 공공데이터포털 파일 다운로드와 같아 geocode_lamps.py · merge_lamps.py를 그대로 씁니다. 이미 있는 파일은 덮지 않습니다.
사용: (환경 변수 DATA_GO_KR_KEY 필요)  python fetch_lamps_api.py [구 이름 ...]   → python geocode_lamps.py → python merge_lamps.py lamps_geo"""
import csv, json, os, sys, time, urllib.error, urllib.parse, urllib.request

URL = "https://api.data.go.kr/openapi/tn_pubr_public_scrty_lmp_api"
# 2026-11-05 확인: 좌표 있는 15개 구 + 주소만 있는 강남·송파(지오코딩 필요). 종로·중구·마포·용산은 기존 파일 사용
# 제외: 도봉(500건, 2018) · 서대문(463건, 2020) · 성동(37건, 아파트 단지)은 일부만 있어 그 구 전체가 '적음'으로 잘못 나옴, 동대문은 API에 없음
GU = ["강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구", "노원구", "동작구", "서초구",
      "성북구", "양천구", "영등포구", "은평구", "중랑구", "강남구", "송파구"]
COLS = {"보안등위치명": "lmpLcNm", "설치개수": "installationCo", "소재지도로명주소": "rdnmadr", "소재지지번주소": "lnmadr",
        "위도": "latitude", "경도": "longitude", "설치연도": "installationYear", "설치형태": "installationType",
        "관리기관전화번호": "phoneNumber", "관리기관명": "institutionNm", "데이터기준일자": "referenceDate"}
ROWS = 1000


class HttpsOnly(urllib.request.HTTPRedirectHandler):
    """주소에 서비스 키가 실려 있으므로 http로 넘어가는 리다이렉트는 따라가지 않음"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.startswith("https://"):
            raise urllib.error.URLError("https가 아닌 주소로 리다이렉트되어 중단")   # newurl에 키가 있을 수 있어 출력하지 않음
        return super().redirect_request(req, fp, code, msg, headers, newurl)


OPEN = urllib.request.build_opener(HttpsOnly).open

def page(key, inst, no):
    q = urllib.parse.urlencode({"serviceKey": key, "type": "json", "pageNo": no, "numOfRows": ROWS, "institutionNm": inst})
    for wait in (0, 5, 15, 45):                 # 공공데이터포털은 가끔 응답 없이 끊김 → 대기 후 재시도
        time.sleep(wait)
        try:
            with OPEN(f"{URL}?{q}", timeout=60) as r:
                d = json.load(r)
            if d["header"]["resultCode"] == "03":    # NODATA: 이 관리기관명으로는 자료 없음
                return 0, []
            body = d["body"]
            items = body.get("items") or {}
            return int(body["totalCount"]), items.get("item", []) if isinstance(items, dict) else items
        except Exception as e:
            print(f"  {inst} {no}쪽 실패({e}), 재시도")
    raise SystemExit(f"{inst} {no}쪽을 받지 못했습니다")


def fetch(key, gu):
    out = f"lamps/서울특별시_{gu}_보안등정보.csv"
    if os.path.exists(out):
        print(f"{gu}: 이미 있음, 건너뜀 ({out})")
        return
    for inst in (f"서울특별시 {gu}청", f"서울특별시 {gu}"):   # 구마다 등록 이름이 다름 (영등포만 '청' 없음, 2026-11-05)
        total, rows = page(key, inst, 1)
        if total:
            break
    else:
        raise SystemExit(f"{gu}: 자료 없음")
    for no in range(2, (total + ROWS - 1) // ROWS + 1):
        rows += page(key, inst, no)[1]
    assert len(rows) == total, f"{gu}: {len(rows)}건 받음, 총 {total}건"
    os.makedirs("lamps", exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        w.writerows([r.get(k, "") for k in COLS.values()] for r in rows)
    print(f"{gu}: {total}건, 좌표 있음 {sum(1 for r in rows if r.get('latitude'))}건 → {out}")


if __name__ == "__main__":
    key = os.environ.get("DATA_GO_KR_KEY")
    if not key:
        raise SystemExit("DATA_GO_KR_KEY 환경 변수가 없습니다")
    for gu in sys.argv[1:] or GU:
        fetch(key, gu)
