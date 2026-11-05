# 장소 추천 PoC 공통 코드

Notion "RUN+Trip - 장소 추천 모델 PoC" 문서 기준. 데이터는 `../data/`(9장 참고).

## Colab에서 실행 (권장)

1. Google Drive `내 드라이브/RUNTrip/`에 `poc/` 폴더와 `data/`의 `places.csv`, `queries.jsonl`, `labels.jsonl`, `split.json`을 올려요.
2. `poc/runtrip_poc.ipynb`를 Colab으로 열고 위에서부터 셀을 실행해요.
3. 하이퍼파라미터 탐색 셀에서 `LOSS`를 자기 담당 후보(A/B/C)로 바꿔요. 결과는 Drive `poc/runs/`에 쌓여 팀원 모두 볼 수 있어요.

## 로컬 설치

```bash
pip install torch sentence-transformers
```

## 실행 순서

```bash
python poc/embed_kure.py                   # 1회: KURE 임베딩 → data/kure/ (모델 약 2.3GB 다운로드)
python poc/features.py                     # 피처 배열 → data/features.npz
python poc/evaluate.py                     # 규칙 기준선 valid 성능
python poc/train.py --loss A --lr 1e-3 --dropout 0.1 --seed 0
```

결과는 `poc/runs/{loss}_lr{lr}_do{dropout}_s{seed}.json`과 같은 이름의 `.pt`(최적 epoch 가중치, `/recommend` 서빙용)로 저장돼요.

KURE 없이 흐름만 점검할 때 (무작위 벡터라 성능 수치는 의미 없음):

```bash
python poc/embed_kure.py --dummy               # data/kure_dummy/ (data/kure/는 건드리지 않음)
python poc/features.py --kure-dir data/kure_dummy
python poc/evaluate.py
python poc/train.py --loss A --test
```

## 파일

| 파일 | 내용 | 수정 |
|---|---|---|
| `embed_kure.py` | 장소 개요·취향 문장 임베딩. `PREF_QUERY`는 팀 확정 필요 | 공통 |
| `features.py` | 피처 10개 + 패딩(최대 20) + mask | 공통 |
| `evaluate.py` | NDCG@5, HitRate@5(2점 이상), 취향 일치율@5, 규칙 기준선 | 공통 |
| `model.py` | `Scorer` MLP | 공통 |
| `train.py` | 학습 루프, valid NDCG@5로 최적 epoch 선택, 결과 → `poc/runs/` | 공통 |
| `losses.py` | 손실 함수 A·B·C와 옵티마이저 | **각자 자기 함수만** |

## 피처 (features.py `FEATURES`)

`kure_sim`(고른 취향 중 max), 카테고리 one-hot 3개, `night_spot`, `detour_ratio`(= detour_km ÷ 목표거리), `is_night`, 고른 취향 multi-hot 3개

## 팀 확정 필요

- `evaluate.py` `EXCLUDE_NO_POSITIVE`: 2점 이상 장소가 없는 쿼리를 HitRate에서 제외(기본) vs 0점
- `evaluate.py` `W_MATCH`, `W_DETOUR`: 규칙 기준선 가중치 (정한 뒤 바꾸지 않기)
- `embed_kure.py` `PREF_QUERY`: 취향 문장

## 진행 규칙 (PoC 문서 4장)

- 하이퍼파라미터: lr {1e-3, 3e-4} × dropout {0.1, 0.3}, 시드 3개 평균
- 튜닝은 valid로만, `--test`는 최종 설정으로 한 번만
