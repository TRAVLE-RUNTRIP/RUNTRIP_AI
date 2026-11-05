import torch.nn as nn


class Scorer(nn.Module):
    """A·B·C 공통 모델: 피처 → 64 → 32 → 1"""

    def __init__(self, d, dropout=0.2):
        super().__init__()
        self.net = nn.Sequential(nn.Linear(d, 64), nn.ReLU(), nn.Dropout(dropout),
                                 nn.Linear(64, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x):                # x: (batch, 후보, d)
        return self.net(x).squeeze(-1)   # (batch, 후보) 점수
