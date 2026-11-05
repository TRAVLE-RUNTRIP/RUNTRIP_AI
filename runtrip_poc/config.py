"""PoC 공통 설정. 팀원 모두 같은 값을 쓰도록 여기서만 바꿔요."""
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"          # places.jsonl, queries.jsonl, split/*.jsonl
FEAT_DIR = ROOT / "features"      # train/valid/test.npz
RESULT_DIR = ROOT / "results"     # A.json, B.json, C.json, baseline.json, summary.md
CKPT_DIR = ROOT / "checkpoints"

# ---- 데이터 형식 (TODO: 합성 데이터 형식 확정 후 팀 확인) ----
N_CANDIDATES = 20                  # 쿼리당 후보 장소 수
REL_MAX = 3                        # 관련도 0~3점
SPLIT_RATIO = (0.70, 0.15, 0.15)   # 페르소나 기준 train / valid / test
SPLIT_SEED = 42

# 취향 선택지 (와이어프레임 기준, TODO: 최종 목록 확정)
TASTES = ["야경", "관광 명소", "자연·공원"]
# 임베딩용 취향 문장 (KURE가 읽는 문장)
TASTE_SENTENCES = {
    "야경": "밤에 조명과 야경이 아름다운 곳",
    "관광 명소": "역사와 문화가 있는 대표 관광 명소",
    "자연·공원": "나무와 물길이 있는 조용한 공원과 자연",
}
# TourAPI 카테고리 묶음 (TODO: contentTypeId 매핑 확정)
CATEGORIES = ["관광지", "문화시설", "공원·자연", "쇼핑", "음식점", "기타"]
# 후보에서 뺄 카테고리. TourAPI 서울 장소의 약 58%가 음식점이라, 그대로 두면 후보 20개 중 11개가
# 음식점이 돼요. 러닝 경유지 추천이 목적이라 PoC에서는 제외 (TODO: 팀 확인)
EXCLUDE_CATEGORIES = ["음식점"]
# 취향 일치율 / 규칙 기준선에서 쓰는 '취향 → 맞는 카테고리' 매핑 (TODO: 팀 확인)
TASTE_TO_CATEGORIES = {
    "야경": ["관광지", "공원·자연"],
    "관광 명소": ["관광지", "문화시설"],
    "자연·공원": ["공원·자연"],
}
TIMES = ["day", "night"]
TARGET_KMS = [3, 5, 10]
LEVELS = ["초보", "중급", "상급"]
# '같은 페르소나'를 판단하는 필드. 취향(7조합)×거리(3)×시간대(2)만 쓰면 페르소나가 42종뿐이라
# test에 6종 정도만 남아요. 러너 수준을 넣으면 126종. TODO: 팀에서 최종 정의 확정
PERSONA_KEY_FIELDS = ["tastes", "distance_km", "time", "level"]

# ---- 임베딩 ----
USE_EMBEDDING = True               # 리스크 축소 순서 3번: False면 KURE 유사도 피처를 0으로 (피처 단순화)
EMBED_MODEL = "nlpai-lab/KURE-v1"  # 대체: "BAAI/bge-m3"

# ---- 학습 (A·B·C 공통) ----
HIDDEN = (64, 32)
GRID = {"lr": [1e-3, 3e-4], "dropout": [0.1, 0.3]}
SEEDS = [0, 1, 2]
BATCH_SIZE = 32                    # 쿼리 단위 배치
MAX_EPOCHS = 100
PATIENCE = 10                      # valid NDCG@5 기준 조기 종료
# 공정 비교를 위해 옵티마이저는 세 후보 모두 동일하게 둬요 (손실 함수만 다르게).
OPTIMIZER = "AdamW"
WEIGHT_DECAY = 1e-4

# ---- 평가 ----
TOP_K = 5
SIMPLER_WINS_MARGIN = 0.01         # NDCG@5 차이가 이보다 작으면 단순한 모델(A→B→C) 선택

# ---- 합성 데이터 (Gemini) ----
GEMINI_MODEL = "gemini-3.8-flash"  # TODO: 1주차 LLM API PoC 결과로 확정, 정확한 모델 ID 확인
N_QUERIES = 2000
REVIEW_RATIO = 0.15                # 사람이 직접 검수할 비율 (10~20%)
