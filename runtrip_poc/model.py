"""A·B·C 공통 모델. 팀원은 이 파일을 수정하지 않아요."""
import torch.nn as nn
import config as C


class Scorer(nn.Module):
    """후보 장소마다 점수 1개를 내는 MLP: 피처 → 64 → 32 → 1"""
    def __init__(self, d, dropout=0.2):
        super().__init__()
        h1, h2 = C.HIDDEN
        self.net = nn.Sequential(
            nn.Linear(d, h1), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(h1, h2), nn.ReLU(),
            nn.Linear(h2, 1),
        )

    def forward(self, x):                 # x: (batch, 20, d)
        return self.net(x).squeeze(-1)    # (batch, 20) 장소별 점수
