# RUN+Trip 장소 추천 모델 PoC — 공통 코드

A(Pointwise) · B(Pairwise) · C(Listwise) 세 후보를 **같은 데이터·피처·모델 구조·평가 코드**로 비교하기 위한 뼈대예요.
후보 간 차이는 `losses.py`의 손실 함수 하나뿐이에요.

## 실행 순서

```bash
pip install -r requirements.txt

# 0) 데이터 없이 흐름만 점검할 때 (가짜 데이터 + 가짜 임베딩, 1분 내외)
python make_dummy_data.py --n 600
python split.py
python features.py --embedder dummy
python baseline.py
python train.py --cand A    # B, C도 동일
python summarize.py         # results/summary.md → 노션 6장 표에 붙여넣기

# 1) 실제 PoC
TOUR_API_KEY=... python fetch_places.py --probe   # 응답 형식 확인
TOUR_API_KEY=... python fetch_places.py           # data/places.jsonl 생성 (호출 제한 걸리면 다음 날 --skip-list로 이어서)
GEMINI_API_KEY=... python data_gen.py --n 2000   # 합성 라벨 + data/review_sample.csv(검수용)
python split.py
python features.py --embedder kure
python baseline.py
python train.py --cand C     # 각자 자기 후보만
python summarize.py
```

## 파일과 담당

| 파일 | 내용 | 수정 |
| --- | --- | --- |
| `config.py` | 공통 설정 (취향·카테고리 목록, 그리드, 시드, 옵티마이저) | 장현서만 |
| `fetch_places.py` | TourAPI 위치기반 목록 + 개요 수집 → `places.jsonl` | 장현서 |
| `data_gen.py` | Gemini 합성 데이터 생성 + 자동 검증 + 검수 샘플 | 장현서 |
| `split.py` | 페르소나 기준 70/15/15 분할, 누수 검사 | 장현서 |
| `features.py` | KURE 유사도 + 카테고리·거리·시간대·취향 피처 | 장현서 |
| `model.py` | `Scorer` MLP (피처 → 64 → 32 → 1) | **수정 금지** |
| `losses.py` | `loss_A` / `loss_B` / `loss_C` | **자기 함수만** |
| `train.py` | 공통 학습 루프 (그리드 × 시드, 조기 종료, test 1회 평가) | **수정 금지** |
| `metrics.py` | NDCG@5, HitRate@5, 취향 일치율 | **수정 금지** |
| `baseline.py` | 규칙 점수 기준선 | 장현서 |
| `summarize.py` | 결과표 + 선정 규칙 자동 적용 | 장현서 |

## 진행 규칙 (노션 4장과 동일)

1. 각자 `losses.py`의 자기 손실 함수만 수정해요. 데이터·피처·모델·평가 코드는 건드리지 않아요.
2. 하이퍼파라미터는 `config.GRID` (lr {1e-3, 3e-4} × dropout {0.1, 0.3}), 시드 3개 평균.
3. `train.py`가 valid로만 설정을 고르고, test는 최적 설정으로 **한 번만** 평가해요.
4. 결과는 평균 ± 표준편차로 기록돼요. 표준편차가 0.01보다 크면 후보 간 차이가 우연일 수 있어요.

## 노션 문서와 달라진 점 (팀 확인 필요)

- **옵티마이저 통일**: 노션 표는 B만 AdamW, A·C는 Adam인데, 그러면 차이가 손실 함수 때문인지 weight decay 때문인지 구분이 안 돼요. 세 후보 모두 `AdamW(weight_decay=1e-4)`로 맞췄어요 (`config.OPTIMIZER`).
- **페르소나 정의**: 취향·거리·시간대만으로는 42종뿐이라 test에 6종 정도만 남아요. 러너 수준(초보/중급/상급)을 추가해 126종으로 늘렸어요 (`config.PERSONA_KEY_FIELDS`).
- **결과표에 표준편차 추가**: 0.01 차이 규칙이 의미 있는지 판단하려고요.

## 아직 TODO

- `config.py`: 취향 선택지·카테고리 매핑·테스트 지역 확정
- `data_gen.py`: Gemini 모델 ID 확정 (1주차 LLM API PoC 결과)
- `fetch_places.py`: `--probe` 결과로 필드 이름·'공원·자연' 분류 기준 확인
- `baseline.py`: 규칙 가중치(0.5/0.3/0.2) valid로 가볍게 조정
- `/recommend` 연결: `checkpoints/{선정 모델}.pt` 로드해서 FastAPI에서 `Scorer` 추론
