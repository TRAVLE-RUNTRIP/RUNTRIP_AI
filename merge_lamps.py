"""구별 보안등 파일(CSV/XLS)을 한 폴더에 모아 하나로 합칩니다.
사용: python merge_lamps.py 폴더이름   → 서울_보안등.csv 생성 (그 뒤 python check_lamps.py 서울_보안등.csv)"""
import os, sys, glob
import pandas as pd

args = [a for a in sys.argv[1:] if not a.startswith("--")]
folder = args[0] if args else "lamps"
CRS = None
if "--crs" in sys.argv:                     # 미터 단위 좌표(TM 등) 파일을 위경도로 바꿀 때: --crs EPSG:5186
    CRS = sys.argv[sys.argv.index("--crs") + 1]
GU = ["강남구","강동구","강북구","강서구","관악구","광진구","구로구","금천구","노원구","도봉구",
      "동대문구","동작구","마포구","서대문구","서초구","성동구","성북구","송파구","양천구",
      "영등포구","용산구","은평구","종로구","중구","중랑구"]
LAT = ["위도", "lat", "latitude", "y", "y좌표", "위도(y)", "wgs84위도"]
LNG = ["경도", "lon", "lng", "long", "longitude", "x", "x좌표", "경도(x)", "wgs84경도"]
ADDR_WORDS = ["주소", "소재지", "위치", "지번", "도로명"]

def read_any(path):
    if path.lower().endswith((".xls", ".xlsx")):
        return pd.read_excel(path)
    for enc in ("utf-8-sig", "cp949"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("글자 인코딩을 읽지 못했습니다")

def find_col(cols, names):
    low = {str(c).strip().lower(): c for c in cols}
    for n in names:
        if n in low:
            return low[n]
    return None

files = sorted(glob.glob(os.path.join(folder, "*.csv")) + glob.glob(os.path.join(folder, "*.xls*")))
if not files:
    sys.exit(f"'{folder}' 폴더에 csv/xls 파일이 없습니다.")

parts, summary = [], []
for f in files:
    name = os.path.basename(f)
    gu = next((g for g in GU if g in name), None)
    try:
        df = read_any(f)
    except Exception as e:
        summary.append((name, gu, 0, f"읽기 실패: {e}")); continue
    la, lo = find_col(df.columns, LAT), find_col(df.columns, LNG)
    if la is None or lo is None:
        summary.append((name, gu, 0, f"위도/경도 열을 못 찾음 → 열 이름: {list(df.columns)[:12]}")); continue
    d = pd.DataFrame({"위도": pd.to_numeric(df[la], errors="coerce"), "경도": pd.to_numeric(df[lo], errors="coerce")})
    addr_cols = [c for c in df.columns if any(w in str(c) for w in ADDR_WORDS)]
    addr = df[addr_cols].fillna("").astype(str).agg(" ".join, axis=1) if addr_cols else ""
    d = d.assign(_a=addr)
    n0 = len(d)
    note = ""
    v = d.dropna(subset=["위도", "경도"])
    in_lat = lambda x: x.between(37.40, 37.72)
    in_lng = lambda x: x.between(126.70, 127.25)
    if len(v) and (in_lat(v["경도"]).mean() > 0.5 and in_lng(v["위도"]).mean() > 0.5):
        d["위도"], d["경도"] = d["경도"], d["위도"]; note = " (위도·경도 열이 서로 바뀌어 있어 자동으로 바로잡음)"
    elif len(v) and v["위도"].abs().median() > 1000:                      # 미터 단위 좌표
        if CRS:
            try:
                from pyproj import Transformer
                t = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
                lon_, lat_ = t.transform(d["경도"].values, d["위도"].values)   # x=경도열, y=위도열
                d["위도"], d["경도"] = lat_, lon_; note = f" (미터 좌표를 {CRS}로 변환)"
            except ImportError:
                print("pyproj가 필요합니다: pip install pyproj"); sys.exit(1)
    d = d.dropna(subset=["위도", "경도"])
    d = d[d["위도"].between(37.40, 37.72) & d["경도"].between(126.70, 127.25)]   # 서울 범위만
    if len(d) < n0 * 0.5:                                                # 많이 버려졌으면 원인 진단 출력
        print(f"\n[진단] {name}: 사용한 열 위도='{la}', 경도='{lo}', 서울 좌표 {len(d)}/{n0}행")
        print("  위도열 최소/최대:", v["위도"].min() if len(v) else None, "/", v["위도"].max() if len(v) else None)
        print("  경도열 최소/최대:", v["경도"].min() if len(v) else None, "/", v["경도"].max() if len(v) else None)
        print("  앞 3행:", df[[la, lo]].head(3).values.tolist(), "| 전체 열:", list(df.columns)[:12])
        print("  위도·경도가 비어 있는 행 수:", int(df[[la, lo]].isna().any(axis=1).sum()))
    label = f"서울특별시 {gu}" if gu else "서울특별시 (구 미상)"
    d["소재지지번주소"] = d["_a"].apply(lambda a: a if "서울" in str(a) else f"{label} {a}")
    d["소재지도로명주소"] = ""
    d["관리기관명"] = label
    parts.append(d[["위도", "경도", "소재지지번주소", "소재지도로명주소", "관리기관명"]])
    summary.append((name, gu, len(d), f"원본 {n0}행 중 서울 좌표 {len(d)}행" + note + ("" if gu else " (파일명에 구 이름이 없어 '구 미상'으로 처리)")))

print("[파일별 결과]")
for name, gu, n, msg in summary:
    print(f"  {name} → {gu or '?'} : {msg}")
if parts:
    out = pd.concat(parts, ignore_index=True)
    out.to_csv("서울_보안등.csv", index=False, encoding="utf-8-sig")
    print(f"\n합계 {len(out)}행 → 서울_보안등.csv 저장")
    print(out["관리기관명"].value_counts().to_string())
else:
    print("\n합칠 데이터가 없습니다.")
