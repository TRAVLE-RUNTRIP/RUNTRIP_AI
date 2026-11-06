"""장소 점수 계산. 피처는 poc/features.py와 같은 순서·같은 계산, 점수는 poc/evaluate.py의 규칙 기준선을 그대로 쓴다.
#7에서 MLP로 바꿀 때는 score()의 rule_baseline만 모델로 바꾸면 된다 (피처 10개는 같음)."""
import csv
from pathlib import Path

import numpy as np

from poc.evaluate import rule_baseline
from poc.features import CATS, FEATURES, PREFS

SERVING = Path(__file__).parent / "data" / "places_serving.csv"
PREF_OF = {"NIGHT_VIEW": "야경", "ATTRACTION": "관광 명소", "NATURE": "자연·공원"}   # API 명세 → PoC 취향 이름


class UnknownPlace(Exception):
    def __init__(self, ids):
        self.ids = ids


class Scorer:
    def __init__(self, path=SERVING):
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.index = {r["place_id"]: i for i, r in enumerate(rows)}
        self.sims = np.array([[float(r[f"sim_{p}"]) for p in PREFS] for r in rows], np.float32)
        self.cats = np.array([[float(r["category"] == c) for c in CATS] for r in rows], np.float32)
        self.night = np.array([float(r["night_spot"]) for r in rows], np.float32)

    def features(self, prefs, is_night, place_ids, detour_ratios):
        """(후보 수, 10) 피처. features.py build()의 X[qi, j]와 같은 값"""
        miss = [p for p in place_ids if p not in self.index]
        if miss:
            raise UnknownPlace(miss)
        idx = np.array([self.index[p] for p in place_ids], int)
        chosen = [PREFS.index(PREF_OF[p]) for p in prefs]
        X = np.zeros((len(idx), len(FEATURES)), np.float32)
        X[:, 0] = self.sims[idx][:, chosen].max(1)
        X[:, 1:4] = self.cats[idx]
        X[:, 4] = self.night[idx]
        X[:, 5] = detour_ratios
        X[:, 6] = float(is_night)
        X[:, 7:10] = [float(p in chosen) for p in range(len(PREFS))]
        return X

    def score(self, prefs, is_night, place_ids, detour_ratios):
        return rule_baseline(self.features(prefs, is_night, place_ids, detour_ratios))
