# 런트립 AI

| 폴더·파일 | 내용 | 실행 방법 |
|---|---|---|
| [poc/](poc/README.md), [data/](data/) | 장소 추천 모델 PoC (피처·규칙 기준선·MLP 학습/평가)와 데이터 | [poc/README.md](poc/README.md) |
| `osrm/` | OSRM 도보 경로 서버 | 아래 1장 |
| `safety/` | 안전도: 조명 + 보행 환경 (`safety.py`, `서울_보안등.csv`, 수집·점검 스크립트) | 아래 2·3장 |
| `server/`, `compose.yaml` | AI 서버 (FastAPI, API 명세 B파트) | 아래 AI 서버 |

---

# AI 서버 (server/)

API 명세 B파트(백엔드 → AI). 지금은 `POST /recommend`(B1, 추천 모델 점수), `POST /optimize`(B2), `POST /safety`(B4, 조명 환경 점수)가 있어요.

```bash
docker compose up -d --build        # 레포 루트: AI 서버(127.0.0.1:8000) + OSRM(5000). OSRM 전처리는 아래 1장
# 또는 Docker 없이 (레포 루트에서)
pip install -r server/requirements.txt
uvicorn server.app:app --port 8000
```

- BE 호출 주소: 같은 Compose 네트워크면 `http://ai-server:8000`, 로컬 개발은 `http://127.0.0.1:8000`. 포트는 127.0.0.1에만 열어 외부에 공개하지 않아요
  - `localhost`는 쓰지 말 것: Windows에서 IPv6(`::1`)를 먼저 시도하다 실패해 요청마다 약 2초 늦어져요 (500ms 제한 초과, 2026-11-06 측정)
- `osrm/`에서 OSRM을 따로 띄워 둔 상태면 5000번 포트가 겹치니 `osrm/`에서 `docker compose down` 후 실행
- `GET /health` → `{"status": "ok"}`
- `POST /recommend`

  ```json
  // 요청
  {"preferences": ["NIGHT_VIEW", "NATURE"], "isNight": true,
   "candidates": [{"placeId": "T1116925", "detourRatio": 0.42}]}
  // 응답 (후보 순서 그대로, 0~1, 높을수록 추천)
  {"scores": [{"placeId": "T1116925", "score": 0.92}]}
  ```

  점수 = sigmoid(MLP 점수 + 2 × 취향 일치) (#6 최종 모델 `server/data/recommend_model.npz`, `server/scoring.py`)
  - 취향 일치: 고른 취향이 야경이면 서울시 야경명소, 관광 명소·자연·공원이면 같은 카테고리
  - 가산점 2는 sigmoid 안에: 순서가 #6 평가(모델 점수 + 2 × 취향 일치)와 같아짐. sigmoid는 점수를 0~1 양수로 만들어 `/optimize`가 음수 점수를 '넣을수록 손해'로 다루지 않게 함
  - 모델 파일이 없거나 읽지 못하면 경고 로그를 남기고 규칙 기준선(고른 취향 중 KURE 유사도 최댓값 + 0.3 × 취향 일치 − 0.3 × `detourRatio`, `poc/evaluate.py` `rule_baseline`)으로 대신
  - 서버는 torch 없이 numpy로 계산. 모델을 바꾸면 `.pt`·`.json`을 `server/data/recommend_model.*`에 복사하고 `.venv`에서 `python server/export_model.py` (torch와 numpy 점수가 같은지 확인)
- 오류: `{ "code", "message" }`

  | code | HTTP | 상황 |
  |---|---|---|
  | VALIDATION_ERROR | 400 | 취향이 없거나 중복·잘못된 값, `detourRatio`가 음수, 후보가 2,000개 초과 |
  | UNKNOWN_PLACE | 422 | 서빙 파일에 없는 `placeId` (BE와 `places.csv` 버전이 다름) |
  | RESOURCE_NOT_FOUND / METHOD_NOT_ALLOWED | 404 / 405 | 없는 주소·메서드 |
  | SERVER_ERROR | 500 | 그 밖의 오류 |
- `POST /optimize`: 목표 거리 ±10% 안에서 점수 합이 최대인 장소 조합·순서 ('코스 생성 로직 개선안 (확정)')

  ```json
  // 요청: 거리표 첫 줄 = 출발지, 마지막 줄 = 도착지(순환이면 출발지와 같은 좌표), 가운데 = placeIds 순서 (정수 m)
  {"targetKm": 5, "maxPlaces": 3, "timeLimitMs": 500, "placeIds": ["T1116925", "T128961"], "scores": [0.92, 0.88],
   "distanceMatrixM": [[0, 320, 410, 0], [320, 0, 150, 320], [410, 150, 0, 410], [0, 320, 410, 0]], "excludedCombos": []}
  // 응답. 못 찾으면 {"found": false, "orderedPlaceIds": [], "totalKm": null} → BE가 NO_PLACES / NO_MORE_COURSES
  {"found": true, "orderedPlaceIds": ["T128961", "T1116925"], "totalKm": 5.1}
  ```

  - 장소마다 빼면 점수 × 1000만큼 손해(`AddDisjunction`), 거리 상한 목표 × 1.1, 하한 × 0.9, 장소 수 ≤ `maxPlaces`. 점수가 음수인 장소도 점수 합에 그대로 반영(넣을수록 손해)해서, 점수 합을 더 높이거나 거리를 맞출 때만 들어감
  - `excludedCombos`: 이미 보여준 조합의 장소가 모두 다시 들어가지 않게 함 (개선안 10장 "활성 변수 합 ≤ 장소 수 − 1")
  - 솔버: 제한 시간의 30%는 OR-Tools Routing으로 첫 해, 나머지는 그 해를 힌트로 CP-SAT이 개선 → 점수 합이 큰 쪽.
    Routing만 쓰면 3·5km 32건 중 28건만 최적이고 1건은 해를 놓쳐서 바꿈 (2026-11-06)
  - 요청 오류(`VALIDATION_ERROR` 400): 거리표가 (장소 수 + 2)² 가 아님, `scores` 개수 다름, `placeIds` 중복·50곳 초과, 음수 거리, 범위 밖 값
    (50곳 상한: BE는 상위 40곳을 보내고, 더 많으면 CP-SAT 모델이 커져 제한 시간 안에 좋은 해를 찾기 어려움. 후보 수를 바꾸면 같이 조정)
- `POST /safety`: 코스 경로의 조명 환경 점수 (경로는 바꾸지 않음). 계산은 아래 2장 `safety.py` 그대로, `server/safety_course.py`가 API 형식으로 바꿈

  ```json
  // 요청: OSRM 경로선 [위도, 경도] (OSRM GeoJSON은 [경도, 위도]라 뒤집어서). 아래 응답은 점 53개(인덱스 0~52) 경로 기준, 앞 2개만 표시
  {"path": [[37.5658, 126.9751], [37.5661, 126.9755], ...], "isNight": true}
  // 응답. segments의 fromIndex·toIndex는 path 위치, 이웃 구간이 같은 점을 공유해 빈틈·겹침 없음
  {"score": 87, "level": "좋음", "coverage": 0.15, "estimated": 0.85, "hasLowSegment": true,
   "segments": [{"fromIndex": 0, "toIndex": 40, "grade": "큰길(조명 추정)"}, {"fromIndex": 40, "toIndex": 52, "grade": "적음"}],
   "warnings": ["밤에는 확인된 가로등이 적은 구간이 있어요. 밝은 옷과 라이트를 챙기세요"]}
  ```

  - `grade`: 큰길(조명 추정) · 많음 · 보통 · 적음 · 자료없음. `level`: 좋음(80↑) · 보통(60↑) · 주의 · 자료부족(자료 범위 안이 50% 미만), 점수가 null이면 null
  - 보행 환경(아래 2장 `walk_score`·계단·인도 없음 경고)은 FE 표시 방식이 정해질 때까지 `/safety` 응답에 넣지 않음
  - 25m 조각 경계를 가장 가까운 path 점으로 옮기므로, 점 사이에 끼는 아주 짧은 구간은 앞뒤에 합쳐짐 (적음은 100m 이상이라 OSRM 경로에선 남음)
  - 서버 시작 때 `safety/서울_도로.parquet`(OSM 도로 13만 개, `safety/build_roads.py`로 osrm/의 pbf에서 만듦)·`서울_보안등.csv`를 읽음: 약 3초, 메모리 약 270MB 더 씀
  - 요청 오류(`VALIDATION_ERROR` 400): 점 2개 미만·모두 같은 점, 위도·경도 범위 밖, 20,000점 초과
- 서빙 파일 `server/data/places_serving.csv`: 장소별 카테고리, `night_spot`, 취향 3개와의 KURE 유사도. 서버는 KURE 모델(2.3GB)을 쓰지 않아요.
  `places.csv`나 취향 문장(`poc/embed_kure.py` `PREF_QUERY`)이 바뀌면 다시 만들어요:
  `python poc/embed_kure.py` → `python server/build_serving.py` → `python poc/features.py` → `python -m server.test_recommend`
- 점검 (`pip install -r server/requirements-dev.txt`)
  - `python -m server.test_recommend`: 쿼리 2,000건 점수가 학습 때 점수와 같은지, 모델 파일이 없을 때 규칙 기준선으로 대신하는지, 오류 형식, 후보 수별 응답 시간
  - `python -m server.test_optimize`: 정답을 아는 작은 거리표 (개선안 7장 예시, 다시 만들기, 답 없음, 요청 오류)
  - `python -m server.bench_optimize --exact`: OSRM(127.0.0.1:5000)을 띄운 뒤 실제 거리표로 검증. 서울 8곳 × 3·5·10km × 순환·편도
  - `python -m server.test_safety`: 구간 → path 인덱스 변환, 빈틈·겹침, 자료 밖(부산) 경로, 오류 형식, 5·10km 응답 시간
- 측정 (2026-11-06)
  - `/recommend` (Docker 컨테이너, HTTP 20회 중앙값, 규칙 기준선 시절): 후보 40곳 5.5ms · 200곳 5.7ms · 1,480곳(전체) 17.2ms
  - `/recommend` MLP (2026-11-13, Docker 컨테이너, HTTP 20회 중앙값): 후보 40곳 7.9ms · 200곳 6.6ms · 1,480곳 20.4ms (최대 57.6ms).
    서버 안 처리 시간(TestClient)은 40곳 2.8ms · 200곳 3.7ms · 1,480곳 7.6ms
  - `/optimize` (`bench_optimize`, 후보 상위 40곳, 제한 500ms): 48건 중 47건 해를 찾음 (못 찾은 1건은 완전 탐색으로도 답이 없음),
    찾은 코스 모두 목표 ±10%·OSRM 실제 경로 거리와 같음, 3·5km 32건 전부 최적, 다시 만들기 128/141, 응답 중앙값 421ms · 최대 603ms
  - `/safety` (2026-11-24, EC2 m7i-flex.large Docker 컨테이너, HTTP 5회): OSRM 실제 경로 2.7km 31ms · 5.8km 57ms · 15.6km 145ms.
    서버 안 처리 시간(TestClient, 로컬 PC 직선 경로)은 5km 중앙 128ms · 10km 259ms
  - 이미지 1GB (OR-Tools·geopandas·도로·보안등 데이터 포함, `/safety` 전 539MB), 실행 메모리 약 356MB (`/safety` 전 82MB)

---

# 안전도 · OSRM (장현서, 2026-11-03)

WBS 2.5 안전도 스코어링 설계 · 3.11 AI 데이터 수집 · OSRM 운영 결과물입니다.

## 1. OSRM 도보 경로 서버 (osrm/)

준비: Docker (Windows·Mac은 Docker Desktop, Linux·EC2는 Docker Engine + Compose 플러그인),
그리고 지도 파일 `south-korea-latest.osm.pbf`(약 290MB)를 `osrm/` 폴더에 받기.

```bash
cd osrm
curl -LO https://download.geofabrik.de/asia/south-korea-latest.osm.pbf     # Windows PowerShell 5.1은 curl.exe -LO ...
docker compose up -d          # 끄기: docker compose down
```

- 예전 `run_osrm.ps1`로 띄운 적이 있으면 그 컨테이너가 5000번 포트를 쓰고 있으니 먼저 지우기: `docker rm -f osrm-foot`
- 처음 한 번은 `prepare`가 전처리(extract → contract) 후 끝나고 `osrm`이 뜸. 다음부턴 전처리를 건너뛰고 바로 실행.
  진행 확인: `docker compose logs -f prepare`
- 필요 사양 (2026-11-06, 8코어 PC 측정)

  | 항목 | 값 |
  |---|---|
  | 전처리 시간 | 약 1시간 (contract 53분) |
  | 전처리 메모리 | 최대 4.5GB (contract) → Docker 메모리 8GB 권장 |
  | 실행 메모리 | 약 2.7GB |
  | 디스크 | 지도 290MB + 전처리 결과 약 2.9GB |

- 서버: http://localhost:5000 (PC 재부팅 후 자동 실행)
- 경로: `/route/v1/foot/경도,위도;경도,위도?overview=full&geometries=geojson`
- 거리 행렬(OR-Tools 입력): `/table/v1/foot/경도,위도;경도,위도;...?annotations=distance,duration`
- 속도 (`data/places.csv` 장소 40곳 + 출발·도착 = 42개 지점, 20회 중앙값)

  | | 시청 | 홍대 | 강남 |
  |---|---|---|---|
  | 42×42 거리 행렬 | 72ms (p95 87) | 61ms (p95 75) | 64ms (p95 81) |

  경로 1개는 약 15ms. 전처리 방식은 **CH**: MLD는 같은 거리 행렬이 430~490ms라 7배 느려 바꿈 (거리 차이 최대 2.8m)
- `foot.lua` = 기본 도보 설정에서 **페리만 뺀 것**. 기본 설정은 한강버스를 경로에 넣어 시청→잠실이 25.1km로 나옴 (수정 후 13.8km).
  설정을 바꾸면 `osrm/` 폴더에서 `docker compose down` → `*.osrm*` 파일 삭제 → `docker compose up -d` (다시 전처리 후 실행).
- EC2에도 같은 이미지(ghcr.io/project-osrm/osrm-backend:v5.27.1)·같은 명령으로 옮길 수 있음.
  - 사양: 메모리 8GB 이상(t3.large급, 실행만 OSRM 2.7GB + AI 서버 약 82MB + BE), 디스크 20GB 이상. x86 기준 (ARM/Graviton은 OSRM 이미지 지원 확인 필요)
  - 전처리 건너뛰기: PC에서 만든 `osrm/south-korea-latest.osm.pbf`와 `south-korea-latest.osrm.*` 파일(약 3.7GB)을 EC2의 `osrm/` 폴더로 복사하면 `prepare`가 바로 끝남
  - 포트: AI 서버(8000)·OSRM(5000) 모두 127.0.0.1에만 열림. BE 컨테이너는 같은 Compose 네트워크(`runtrip_default`)에서 `http://ai-server:8000`, `http://osrm:5000`으로 호출
  - AI 서버와 OSRM을 함께 실행하려면 레포 루트에서 `docker compose up -d --build`를 실행하고, BE 컨테이너를 `runtrip_default`에 연결. `osrm/`에서 따로 실행 중이면 먼저 그 폴더에서 `docker compose down` 실행

## 2. 안전도 (safety/safety.py)

2·3장의 명령은 모두 `safety/` 폴더에서 실행합니다 (스크립트가 `서울_보안등.csv`, `서울_구경계.geojson`, `lamps/` 등을 현재 폴더에서 찾음).

```
pip install geopandas osmnx
cd safety
python safety.py          # 자가 점검
```

```python
import osmnx as ox, pandas as pd
from safety import SafetyIndex
ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["lit", "sidewalk", "sidewalk:both", "surface"]))   # 필수: 기본값엔 없어 lit=no 큰길도 '조명 추정', 인도 없음·비포장은 판정 안 됨
edges = ox.graph_to_gdfs(ox.graph_from_point((37.5685, 126.9850), dist=2500, network_type="all"), nodes=False)
idx = SafetyIndex(edges, pd.read_csv("서울_보안등.csv"))
idx.grade_course([(126.9918, 37.5704), (126.9850, 37.5820)], night=True)   # OSRM 경로 좌표를 그대로 넣으면 됨
# → {"score": 81, "level": "좋음", "coverage": 0.59, "estimated": 0.41, "segments": [{"start_m", "end_m", "grade"}...],
#    "walk_score": 74, "walk_segments": [{"start_m", "end_m", "grade"}...], "warnings": [...]}
```

안전도 = **조명**(`score`, `level`, `segments`) + **보행 환경**(`walk_score`, `walk_segments`). 둘을 합칠지·비율은 팀 합의 전이라 따로 냄.

### 보행 환경
- 경로 25m 조각마다 15m 안 가장 가까운 OSM 길의 종류로 판정 (없으면 자료없음, 점수에서 뺌)
- 등급(가중치, 임시값): 보행로 1.0 (footway·pedestrian·path·cycleway·living_street) / 골목 0.7 (residential·service 등) / 계단 0.6 / 비포장 0.6 (surface가 dirt·gravel 등) / 대로 0.5 (primary 이상) / 좁은 차도 0.2 (tertiary·*_link) / 인도 없음 0.0 (sidewalk=no인 차도)
- 가중치 근거 (종로·중구 무작위 경로 300개): 대로를 0.3~0.4로 깎으면 조명의 '큰길 추정'을 뒤집은 값이 됨(상관 -0.6). 0.5면 상관 -0.33, 평균 60·표준편차 7.7. 점수 폭이 좁아 화면은 숫자보다 구간 색·경고 위주 권장
- 50m 미만 구간은 앞 구간에 합침 (교차로에서 25m씩 끊김 방지). 인도 없음은 짧아도 남김
- 인도 없음·계단·비포장 구간은 `warnings`에 문구 추가
- sidewalk 태그는 차도의 약 7%에만 있음 (종로·중구) → 태그가 없으면 인도가 있다고 보고 '대로'·'좁은 차도'. surface도 보행로의 약 10%에만 있어 비포장은 일부만 잡힘
- 횡단보도·교통량·CCTV는 아직 반영 안 됨
- 실측: `python check_walk.py` (`pip install networkx`, `segment_stats.py`가 만든 `osm_graph_2500_v2.graphml` 필요) → 대표 코스 5개 + 무작위 경로 300개의 점수 분포·경고 수

### 조명

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
- 화면 표기는 '안전도'(참고 지수): 조명 + 보행 환경. 횡단보도·교통량·CCTV는 반영 안 됨
- 앱 화면(FE)에 쓸 값: `score`, `level`, `coverage`, `estimated`, `segments`, `walk_score`, `walk_segments`, `warnings`
- 안내 문구는 "확인된 가로등이 적어요" (자료 기준이지 현장 확인은 아님). 화면 문구는 FE와 협의

## 3. 보안등 데이터 (safety/서울_보안등.csv)

- 189,024개, 21개 구 (2026-11-05): 강남 18,767 / 관악 13,285 / 성북 12,310 / 서초 10,929 / 용산 10,021 / 종로 9,553 / 중랑 9,230 / 광진 9,229 / 강북 9,173 / 강서 9,079 / 동작 8,518 / 영등포 8,300 / 은평 8,234 / 마포 7,975 / 강동 7,496 / 양천 7,388 / 구로 6,816 / 금천 6,043 / 노원 5,941 / 중구 5,849 / 송파 4,888
- 제외 (그 구는 '자료없음'): 도봉(500건, 2018) · 서대문(463건, 2020) · 성동(아파트 단지 37행)은 일부만 있어 넣으면 구 전체가 '적음'으로 잘못 나옴. 동대문은 API에 없음 (공공데이터포털 파일은 있음, 추가 예정)
- 자료 범위 = 자료 있는 구의 실제 경계 `서울_구경계.geojson` (OSM 행정경계, © OpenStreetMap contributors).
  볼록 껍질로 감쌌을 때는 오목한 구가 이웃 구를 덮어 마포 → 신촌·연희, 노원 → 창동이 자료 없이 '적음'으로 나왔음
- 경로 중 자료 범위 안 길이가 50% 미만이면 `level` = "자료부족" (자료 밖 큰길 추정만으로 100점이 나오는 것 방지, `safety.MIN_DATA_RATIO` 임시값)
- 주의: 구마다 밀도가 다름 (km²당 조명 지점 송파 110 · 노원 152 · 서초 165 · 강남 194 ~ 광진 494). 기준값(8개/100m)은 종로·중구로 정한 값이라
  밀도 낮은 구는 '적음'이 실제보다 많이 나올 수 있음 → #10(3.8) 때 구별 재확인.
  강남·송파·마포·용산은 주소로 좌표를 찾아 한 점에 몰림 (강남은 18,767개 → 지점 7,830곳). 송파는 기준일 2022-12, 주소 12% 못 찾음
- 다시 만들 때만 필요 (`.env`의 키를 환경 변수로):
  먼저 종로·중구·마포·용산은 API 대신 공공데이터포털 '보안등정보' 파일을 받아 `lamps/서울특별시_OO구_보안등정보.csv`로 넣기
  (`lamps/`는 git에 없음. 안 넣으면 `서울_보안등.csv`가 그 4개 구가 빠진 채로 덮어써짐)
  → `python fetch_lamps_api.py` (DATA_GO_KR_KEY, 전국보안등정보표준데이터 API → `lamps/`, 종로·중구·마포·용산은 기존 파일)
  → `python geocode_lamps.py` (KAKAO_REST_KEY, 빈 좌표를 주소로 채움 → `lamps_geo/`) → `python merge_lamps.py lamps_geo`
- `segment_stats.py`: 기준값(8개/100m)을 정한 통계 스크립트 + 집계 공통 함수(safety.py가 같은 방식으로 셈). 기준값은 종로·중구로 정했고 나머지 구는 3.8 때 재확인 예정.
- `check_osm.py`, `check_lamps.py`: 데이터 점검용.
