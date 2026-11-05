import sys
import numpy as np
import pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "보안등.csv"
if path.lower().endswith((".xls", ".xlsx")):
    df = pd.read_excel(path)
else:
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        df = pd.read_csv(path, encoding="cp949")
print("열 이름:", list(df.columns))
need = ["위도", "경도", "소재지지번주소", "소재지도로명주소"]
lack = [c for c in need if c not in df.columns]
if lack:
    print("없는 열:", lack, "← 위 '열 이름' 줄을 그대로 알려 주세요")
    sys.exit(1)

df = df.dropna(subset=["위도", "경도"])
addr = df["소재지지번주소"].fillna("").astype(str) + " " + df["소재지도로명주소"].fillna("").astype(str)
org = df["관리기관명"].fillna("").astype(str) if "관리기관명" in df.columns else pd.Series("", index=df.index)
text_all = addr + " " + org                      # 주소와 관리기관명을 합쳐서 '서울'을 찾음
seoul = df[text_all.str.contains("서울", na=False)].copy()
seoul_text = text_all[seoul.index]
print("전체 행 수:", len(df), "/ 서울 보안등 행 수:", len(seoul))

if len(seoul) == 0:
    print("\n서울 행이 0개입니다. 파일 상태를 확인합니다.")
    for c in ["관리기관명", "소재지지번주소", "소재지도로명주소"]:
        if c in df.columns:
            print(f"[{c}] 앞 5개:", df[c].dropna().astype(str).head(5).tolist())
    if "관리기관명" in df.columns:
        print("관리기관명 상위 10:", df["관리기관명"].value_counts().head(10).to_dict())
    print("→ 이 출력을 그대로 알려 주세요. (전체 행이 정확히 50,000이면 다운로드 5만 건 제한에 걸린 것입니다)")
    sys.exit(0)

# 1) 25개 구가 모두 들어 있는지
GU = ["강남구","강동구","강북구","강서구","관악구","광진구","구로구","금천구","노원구","도봉구",
      "동대문구","동작구","마포구","서대문구","서초구","성동구","성북구","송파구","양천구",
      "영등포구","용산구","은평구","종로구","중구","중랑구"]
print("\n[구별 건수]")
missing = []
for g in GU:
    n = int(seoul_text.str.contains(g, regex=False).sum())
    print(f"  {g:6s} {n:6d}" + ("   ← 없음" if n == 0 else ""))
    if n == 0:
        missing.append(g)
print("데이터 없는 구:", missing if missing else "없음")

# 2) 서울 곳곳의 대표 지점 반경 1km 안 보안등 수 (표본 확인용)
def near(la, lo, km):
    d = np.hypot((seoul["위도"] - la) * 111, (seoul["경도"] - lo) * 88)
    return int((d <= km).sum())

POINTS = {"시청(중구)": (37.5663, 126.9779), "홍대입구(마포)": (37.5572, 126.9245),
          "여의도(영등포)": (37.5284, 126.9328), "서울숲(성동)": (37.5444, 127.0374),
          "잠실(송파)": (37.5133, 127.1002), "강남역(강남)": (37.4979, 127.0276)}
print("\n[대표 지점 반경 1km 보안등 수]")
for name, (la, lo) in POINTS.items():
    print(f"  {name:12s} {near(la, lo, 1)}개")
