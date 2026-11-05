"""손실 함수. 팀원은 자기 후보의 함수만 수정해요.
  A. Pointwise (BCE)      — 팀원1
  B. Pairwise (RankNet)   — 팀원2
  C. Listwise (ListNet)   — 장현서
모든 함수 시그니처: loss(scores, rel, mask) → 스칼라
  scores: (B, 20) 모델 점수 / rel: (B, 20) 관련도 0~3 / mask: (B, 20) 실제 후보=1
옵티마이저는 공정 비교를 위해 config.py에서 공통으로 정해요 (여기서 바꾸지 않기).
"""
import torch
import torch.nn.functional as F

NEG = -1e9  # 패딩 후보를 softmax에서 빼기 위한 값


def loss_A(scores, rel, mask):
    """Pointwise: 장소 하나하나가 '적합(관련도 ≥ 2)'일 확률을 예측"""
    target = (rel >= 2).float()
    per = F.binary_cross_entropy_with_logits(scores, target, reduction="none")
    return (per * mask).sum() / mask.sum().clamp(min=1)


def loss_B(scores, rel, mask):
    """Pairwise (RankNet): 관련도가 더 높은 장소가 점수도 더 높도록 쌍을 비교"""
    ds = scores.unsqueeze(2) - scores.unsqueeze(1)                 # s_i - s_j
    better = (rel.unsqueeze(2) > rel.unsqueeze(1)).float()         # rel_i > rel_j 인 쌍
    valid = mask.unsqueeze(2) * mask.unsqueeze(1)
    pair = better * valid
    return (F.softplus(-ds) * pair).sum() / pair.sum().clamp(min=1)  # -log σ(s_i - s_j)


def loss_C(scores, rel, mask):
    """Listwise (ListNet): 정답 관련도 분포와 모델 점수 분포의 cross-entropy"""
    s = scores.masked_fill(mask == 0, NEG)
    r = rel.masked_fill(mask == 0, NEG)
    target = F.softmax(r, dim=-1)                                  # TODO 실험: 2**rel - 1 로 상위권 강조
    return -(target * F.log_softmax(s, dim=-1)).sum(-1).mean()


LOSSES = {"A": loss_A, "B": loss_B, "C": loss_C}
