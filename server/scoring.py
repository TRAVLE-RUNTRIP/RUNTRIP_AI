"""장소 점수 계산. 피처는 poc/features.py와 같은 순서·같은 계산.
점수 = sigmoid(MLP 점수 + 취향 가산점 × 취향 일치) (#6 최종 설정, 0~1).
- 가산점을 sigmoid 안에 넣어야 순서가 #6 평가(모델 점수 + 2 × 취향 일치)와 같다
- sigmoid: 모델 점수(logit)는 대부분 음수라 그대로 주면 /optimize가 '넣을수록 손해'인 장소로 다룸 → 0~1 양수로
모델 파일(recommend_model.npz)이 없거나 읽지 못하면 규칙 기준선(poc/evaluate.py rule_baseline)으로 대신한다."""
import csv
import logging
from pathlib import Path

import numpy as np

from poc.evaluate import pref_match, rule_baseline
from poc.features import CATS, FEATURES, PREFS

SERVING = Path(__file__).parent / "data" / "places_serving.csv"
MODEL = Path(__file__).parent / "data" / "recommend_model.npz"   # server/export_model.py로 만듦
log = logging.getLogger("runtrip.ai")
PREF_OF = {"NIGHT_VIEW": "야경", "ATTRACTION": "관광 명소", "NATURE": "자연·공원"}   # API 명세 → PoC 취향 이름


def mlp_logit(w, X):
    """poc/model.py Scorer와 같은 계산 (eval 모드라 dropout 없음): 10 → 64 → 32 → 1"""
    h = np.maximum(X @ w["W1"].T + w["b1"], 0)
    h = np.maximum(h @ w["W2"].T + w["b2"], 0)
    return (h @ w["W3"].T + w["b3"])[..., 0]


def load_model(path=MODEL):
    try:
        w = dict(np.load(path))
        mlp_logit(w, np.zeros((1, len(FEATURES)), np.float32))   # 모양이 맞는지 미리 확인
        return w
    except Exception as e:
        log.warning("추천 모델을 읽지 못해 규칙 점수로 대신합니다: %s (%s)", path, e)
        return None


class UnknownPlace(Exception):
    def __init__(self, ids):
        self.ids = ids


class Scorer:
    def __init__(self, path=SERVING, model=MODEL):
        with open(path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.index = {r["place_id"]: i for i, r in enumerate(rows)}
        self.sims = np.array([[float(r[f"sim_{p}"]) for p in PREFS] for r in rows], np.float32)
        self.cats = np.array([[float(r["category"] == c) for c in CATS] for r in rows], np.float32)
        self.night = np.array([float(r["night_spot"]) for r in rows], np.float32)
        self.model = load_model(model)

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
        X = self.features(prefs, is_night, place_ids, detour_ratios)
        if self.model is None:
            return rule_baseline(X)
        z = mlp_logit(self.model, X) + self.model["pref_bonus"] * pref_match(X)
        return 1 / (1 + np.exp(-z))
