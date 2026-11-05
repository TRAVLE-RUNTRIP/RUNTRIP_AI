"""후보별 담당자가 수정하는 파일: 자기 손실 함수와 옵티마이저 설정만 바꾼다.

s: 점수 (batch, 후보), rel: 관련도 0~3 (batch, 후보), mask: 실제 후보=True (batch, 후보)
패딩 자리는 mask로 손실에서 뺀다.
"""
import torch
import torch.nn.functional as F

NEG = -1e9


def loss_A(s, rel, mask):  # Pointwise BCE (관련도 ≥ 2 → 1), 담당: 이민구
    bce = F.binary_cross_entropy_with_logits(s, (rel >= 2).float(), reduction="none")
    return (bce * mask).sum() / mask.sum()


def loss_B(s, rel, mask):  # Pairwise RankNet, 담당: 노종원
    ds = s.unsqueeze(2) - s.unsqueeze(1)
    pair = (rel.unsqueeze(2) > rel.unsqueeze(1)) & mask.unsqueeze(2) & mask.unsqueeze(1)
    pair = pair.float()
    return (F.softplus(-ds) * pair).sum() / pair.sum().clamp(min=1)


def loss_C(s, rel, mask):  # Listwise ListNet, 담당: 장현서
    target = F.softmax(rel.float().masked_fill(~mask, NEG), -1)
    log_p = F.log_softmax(s.masked_fill(~mask, NEG), -1)
    return -(target * log_p).masked_fill(~mask, 0).sum(-1).mean()


LOSSES = {"A": loss_A, "B": loss_B, "C": loss_C}


def make_optimizer(name, params, lr):
    if name == "B":
        return torch.optim.AdamW(params, lr=lr, weight_decay=1e-2)
    return torch.optim.Adam(params, lr=lr)
