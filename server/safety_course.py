"""/safety (API 명세 B4): safety/safety.py의 SafetyIndex로 경로 조명 환경 점수를 계산하고, 구간 위치(m)를 path 인덱스로 바꾼다.
서울 도로(safety/서울_도로.parquet, build_roads.py로 만듦)·보안등(safety/서울_보안등.csv)은 서버 시작 때 한 번 읽음 (약 3초, 메모리 약 200MB)"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent.parent / "safety"
sys.path.insert(0, str(DIR))              # safety.py가 같은 폴더의 segment_stats를 불러옴
from safety import WALK_WARN, SafetyIndex  # noqa: E402


def load_index():
    return SafetyIndex(gpd.read_parquet(DIR / "서울_도로.parquet"), pd.read_csv(DIR / "서울_보안등.csv", encoding="utf-8-sig"))


def cum_m(path):
    """path([lat, lng]) 각 점까지의 누적 거리(m). grade_course와 같은 EPSG:5179로 재서 start_m·end_m과 같은 기준"""
    p = gpd.GeoSeries(gpd.points_from_xy([q[1] for q in path], [q[0] for q in path]), crs=4326).to_crs(5179)
    d = np.hypot(np.diff(p.x.to_numpy()), np.diff(p.y.to_numpy()))
    return np.concatenate([[0.0], np.cumsum(d)])


def to_indices(cum, segs):
    """[{start_m, end_m, grade}] → [{fromIndex, toIndex, grade}]. 경계는 가장 가까운 점으로, 이웃 구간이 같은 점을 공유해 빈틈·겹침 없음.
    점 사이에 끼어 길이가 0이 된 구간은 빼고, 그래서 이어진 같은 등급은 합침"""
    out = []
    for i, s in enumerate(segs):
        a = 0 if i == 0 else int(np.abs(cum - s["start_m"]).argmin())
        b = len(cum) - 1 if i == len(segs) - 1 else int(np.abs(cum - s["end_m"]).argmin())
        if b <= a:
            continue
        if out and out[-1]["grade"] == s["grade"]:
            out[-1]["toIndex"] = b
        else:
            out.append({"fromIndex": a, "toIndex": b, "grade": s["grade"]})
    out[0]["fromIndex"] = 0                # 앞 구간이 빠졌을 때도 path 처음부터
    return out


def grade(index, path, night):
    r = index.grade_course([(lng, lat) for lat, lng in path], night=night)
    return {"score": r["score"], "level": r["level"], "coverage": r["coverage"], "estimated": r["estimated"],
            "hasLowSegment": any(s["grade"] == "적음" for s in r["segments"]),
            "segments": to_indices(cum_m(path), r["segments"]),
            # ponytail: 보행 환경 경고는 FE(노종원)와 표시 방식이 정해질 때까지 뺌. 정해지면 이 거르기를 지우고 B4에 walk 필드 추가
            "warnings": [w for w in r["warnings"] if not w.endswith(tuple(WALK_WARN.values()))]}
