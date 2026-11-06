"""보안등 파일 중 위도·경도가 빈 행을 카카오 주소 검색으로 채워 lamps_geo/에 저장합니다. 원본(lamps/)은 그대로 둡니다.
사용: (환경 변수 KAKAO_REST_KEY 필요)  python geocode_lamps.py  →  python merge_lamps.py lamps_geo
찾은 좌표는 보안등_좌표캐시.csv에 쌓여 다시 돌려도 같은 주소는 호출하지 않습니다."""
import os, re, glob, json, urllib.request, urllib.parse, urllib.error
from concurrent.futures import ThreadPoolExecutor
import pandas as pd

KEY = os.environ.get("KAKAO_REST_KEY")
SRC, DST = "lamps", "lamps_geo"
CACHE = "보안등_좌표캐시.csv"
SKIP = ["성동구"]   # 아파트 단지 37행뿐이라 구 전체를 대표 못 함 → 넣으면 성동 전체가 '적음'으로 나옴. 전체 자료 받으면 빼기


def clean(a):
    return re.sub(r"(\S+구)(\S+동)", r"\1 \2", str(a).strip())   # "용산구남영동 53-5" → "용산구 남영동 53-5"


def geocode(addr):
    url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode({"query": addr, "size": 1})
    req = urllib.request.Request(url, headers={"Authorization": f"KakaoAK {KEY}"})
    for _ in range(3):
        try:
            docs = json.load(urllib.request.urlopen(req, timeout=10))["documents"]
            return (float(docs[0]["y"]), float(docs[0]["x"])) if docs else (None, None)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise SystemExit(f"카카오 인증 실패({e.code}): REST API 키와 '카카오맵 사용 설정 ON'을 확인하세요")
        except (urllib.error.URLError, TimeoutError):
            pass
    return None   # 요청 실패: '주소 없음'((None, None))과 구분해 캐시에 남기지 않고 다음 실행 때 다시 시도


def read_csv(path):
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue


if __name__ == "__main__":
    if not KEY:
        raise SystemExit("KAKAO_REST_KEY 환경 변수가 없습니다")
    os.makedirs(DST, exist_ok=True)
    cache = dict(zip(*[pd.read_csv(CACHE, keep_default_na=False)[c] for c in ("주소", "좌표")])) if os.path.exists(CACHE) else {}
    files = {f: read_csv(f) for f in sorted(glob.glob(os.path.join(SRC, "*.csv"))) if not any(g in f for g in SKIP)}

    def addr_of(df):   # 지번 주소 우선, 없으면 도로명
        jibun = df.get("소재지지번주소", pd.Series("", index=df.index)).fillna("")
        road = df.get("소재지도로명주소", pd.Series("", index=df.index)).fillna("")
        return jibun.where(jibun.str.strip() != "", road).map(clean)

    todo = set()
    for df in files.values():
        miss = df["위도"].isna() | df["경도"].isna()
        todo |= set(addr_of(df[miss])) - set(cache) - {""}
    print(f"새로 찾을 주소 {len(todo)}개 (캐시 {len(cache)}개)")
    with ThreadPoolExecutor(8) as ex:
        failed = 0
        for a, r in zip(todo, ex.map(geocode, todo)):
            if r is None:
                failed += 1
                continue
            cache[a] = f"{r[0]},{r[1]}" if r[0] else ""
    if failed:
        print(f"요청 실패 {failed}개는 캐시에 넣지 않음 → 다시 실행하면 재시도")
    pd.DataFrame({"주소": list(cache), "좌표": list(cache.values())}).to_csv(CACHE, index=False, encoding="utf-8-sig")

    for f, df in files.items():
        miss = df["위도"].isna() | df["경도"].isna()
        xy = addr_of(df[miss]).map(lambda a: cache.get(a) or ",").str.split(",", expand=True)
        if miss.any():
            df.loc[miss, "위도"] = pd.to_numeric(xy[0], errors="coerce")
            df.loc[miss, "경도"] = pd.to_numeric(xy[1], errors="coerce")
        ok = df["위도"].notna().sum()
        print(f"  {os.path.basename(f)}: 빈 좌표 {miss.sum()}행 → 채움 {ok - (~miss).sum()}행 / 전체 {len(df)}행")
        df.to_csv(os.path.join(DST, os.path.basename(f)), index=False, encoding="utf-8-sig")
