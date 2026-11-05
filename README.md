# 런트립 AI

| 폴더·파일 | 내용 | 실행 방법 |
|---|---|---|
| [poc/](poc/README.md), [data/](data/) | 장소 추천 모델 PoC (피처·규칙 기준선·MLP 학습/평가)와 데이터 | [poc/README.md](poc/README.md) |
| `osrm/` | OSRM 도보 경로 서버 | 아래 1장 |
| `safety.py`, `서울_보안등.csv` | 조명 환경 점수 | 아래 2·3장 |

---

# 안전도 · OSRM (장현서, 2026-11-03)

WBS 2.5 안전도 스코어링 설계 · 3.11 AI 데이터 수집 · OSRM 운영 결과물입니다.

## 1. OSRM 도보 경로 서버 (osrm/)

준비: Docker Desktop, 그리고 지도 파일 `south-korea-latest.osm.pbf`(약 290MB)를
https://download.geofabrik.de/asia/south-korea.html 에서 받아 `osrm/` 폴더에 넣기.

```powershell
powershell -ExecutionPolicy Bypass -File osrm\run_osrm.ps1
```

- 처음 한 번은 전처리 10~30분 (Docker 메모리 8GB 기준, 실제 사용 약 2GB). 다음부턴 바로 실행.
- 서버: http://localhost:5000 (컨테이너 이름 osrm-foot, PC 재부팅 후 자동 실행)
- 경로: `/route/v1/foot/경도,위도;경도,위도?overview=full&geometries=geojson`
- 거리 행렬(OR-Tools 입력): `/table/v1/foot/경도,위도;경도,위도;...?annotations=distance`
- 속도: 경로 5~12ms, 20×20 거리 행렬 약 0.2초
- `foot.lua` = 기본 도보 설정에서 **페리만 뺀 것**. 기본 설정은 한강버스를 경로에 넣어 시청→잠실이 25.1km로 나옴 (수정 후 13.8km).
  설정을 바꾸면 `osrm/*.osrm*` 파일을 지우고 다시 실행.
- EC2에도 같은 이미지(ghcr.io/project-osrm/osrm-backend:v5.27.1)·같은 명령으로 옮길 수 있음.

## 2. 조명 환경 점수 (safety.py)

```
pip install geopandas osmnx
python safety.py          # 자가 점검
```

```python
import osmnx as ox, pandas as pd
from safety import SafetyIndex
ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["lit"]))   # 필수: 기본값엔 lit이 없어 lit=no 큰길도 '조명 추정'이 됨
edges = ox.graph_to_gdfs(ox.graph_from_point((37.5685, 126.9850), dist=2500, network_type="all"), nodes=False)
idx = SafetyIndex(edges, pd.read_csv("서울_보안등.csv"))
idx.grade_course([(126.9918, 37.5704), (126.9850, 37.5820)], night=True)   # OSRM 경로 좌표를 그대로 넣으면 됨
# → {"score": 81, "level": "좋음", "coverage": 0.59, "estimated": 0.41, "segments": [{"start_m", "end_m", "grade"}...], "warnings": [...]}
```

- 경로는 바꾸지 않고 조언만 함 (회피 경로는 2단계).
- 구간 등급: 큰길(조명 추정) / 많음(100m당 조명 지점 8개 이상) / 보통 / 적음(조명 0개가 100m 이상) / 자료없음
- 큰길(조명 추정): 도로 가로등 자료가 없어 관측이 아닌 추정. PPT 설계(도로 유형 기반)대로 점수엔 넣음. OSM에 lit=no인 큰길은 추정하지 않고 보안등으로 판정
- 같은 좌표의 보안등은 1개로 셈 (주소로 찾은 좌표는 한 점에 수십 개가 몰려 있음)
- '많음' 기준은 종로·중구 골목의 상위 25% 밀도 = 상대 구분이지 실제 밝기 측정은 아님 (골목 약 25%, 차도·골목 전체 약 15~20%가 '많음')
- 점수 0~100 = 조명 있는 길 비율, 80 이상 좋음 · 60 이상 보통 · 그 밖 주의
- **coverage** = 보안등으로 판정한(관측) 길이 비율 = **행정구역 기준 자료 확보율**. **estimated** = 큰길(조명 추정) 길이 비율.
  점수엔 둘 다 들어가므로 같이 보여 줄 것 (예: 종로3가→동대문 100점 = 관측 0%, 추정 100%).
  그 구의 자료가 빠짐없다는 뜻은 아님 (동 단위 누락은 확인 불가).
   점수는 이 구간만으로 계산하므로 coverage가 다른 경로끼리 점수만 비교하지 말 것
- 화면 표기는 '안전도'보다 '조명 환경 점수'(참고 지수)를 권장: 보도·횡단보도·교통량은 반영 안 됨
- 앱 화면(FE)에 쓸 값: `score`, `level`, `coverage`, `estimated`, `segments`, `warnings`
- 안내 문구는 "확인된 가로등이 적어요" (자료 기준이지 현장 확인은 아님). 화면 문구는 FE와 협의

## 3. 보안등 데이터 (서울_보안등.csv)

- 33,398개: 종로 9,553 / 용산 10,021 / 마포 7,975 / 중구 5,849. 이 4개 구 밖은 '자료없음'.
- 성동구는 원본이 아파트 단지 37행뿐이라 제외.
- 다시 만들 때만 필요: 구별 원본(공공데이터포털 '보안등정보')을 `lamps/`에 넣고
  `python geocode_lamps.py` (카카오 REST 키를 환경 변수 KAKAO_REST_KEY로) → `python merge_lamps.py lamps_geo`
- `segment_stats.py`: 기준값(8개/100m)을 정한 통계 스크립트 + 집계 공통 함수(safety.py가 같은 방식으로 셈). 기준값은 종로·중구로 정했고 마포·용산은 3.8 때 재확인 예정.
- `check_osm.py`, `check_lamps.py`: 데이터 점검용.
