"""코스 경로를 받아 구간별 가로등 등급·안내 문구·야간 경고·조명 환경 점수(0~100)를 계산합니다. 경로는 바꾸지 않고 조언만 합니다.
기준값은 segment_stats.py 결과(2026-11-03 재계산: 같은 좌표 1개로, 25m 조각·도로 구간 같은 방식으로 셈, 종로구·중구)에서 정했습니다.
사용: idx = SafetyIndex(edges, lamps);  idx.grade_course([(경도, 위도), ...], night=True)
자가 점검: python safety.py"""
import math
import geopandas as gpd
from shapely.geometry import LineString
from shapely.ops import substring
from segment_stats import BUF_M, lamp_points, data_area, per100

BIG = {"motorway", "trunk", "primary", "secondary"}   # 큰길은 도로 가로등이 따로 관리돼 보안등 수로 판단하지 않고 조명 있다고 "추정" (도로 가로등 자료 없음. OSM lit 태그 있는 primary 261개 중 257개, secondary 25개 모두 yes)
# PPT 설계(도로 유형·가로등 기반)대로 점수에는 넣되, 관측한 조명(많음·보통·적음)과 등급 이름을 구분. OSM에 lit=no인 큰길은 추정하지 않고 보안등으로 판정
BIG_NEAR_M = 20                                       # 큰길 옆 보도도 큰길로 봄
MANY = 8                                              # 100m당 조명 지점 8개 이상 = 많음 (골목 p75 7.95), 0개 = 적음. 상대 밀도 구분이지 실제 밝기 측정은 아님
STEP_M = 25                                           # 경로를 25m 조각으로 나눠 판정
DARK_RUN_M = 100                                      # 보안등 0개가 100m 이상 이어질 때만 '적음' (짧은 구간의 0개는 잡음)
# 점수 ≈ 조명 있는 길 비율(보통은 약간 감점). 무작위 경로 300개에서 0.7/0.3보다 어두운 경로를 잘 걸러냄 (2026-11-03)
# ponytail: 판단 기준값, 추천·완주 로그가 쌓이면 조정
WEIGHT = {"큰길(조명 추정)": 1.0, "많음": 1.0, "보통": 0.8, "적음": 0.0}
LEVELS = [(80, "좋음"), (60, "보통"), (0, "주의")]    # 앱 표시용 점수 등급
# 경로 중 보안등 자료 범위 안 길이가 이 비율보다 적으면 level = "자료부족" (자료 밖 큰길 추정만으로 100점이 나오는 것 방지, 예: 강남)
# ponytail: 0.5는 임시값, FE와 표시 방식 확정 시 조정
MIN_DATA_RATIO = 0.5


class SafetyIndex:
    def __init__(self, edges, lamps):
        """edges: EPSG:4326 GeoDataFrame(highway 열), lamps: 위도·경도(·관리기관명) 열이 있는 DataFrame"""
        e = edges.to_crs(5179).reset_index(drop=True)
        # OSMnx는 합쳐진 구간의 서로 다른 태그를 리스트로 줌 → "no"가 하나라도 있으면 추정하지 않음
        lit = e["lit"].apply(lambda v: "no" if isinstance(v, list) and "no" in v else str(v)) if "lit" in e else ""
        is_big = e["highway"].apply(lambda v: any(h in BIG for h in v) if isinstance(v, list) else v in BIG)   # 합쳐진 구간은 highway도 리스트
        self.big = e.loc[is_big & (lit != "no"), ["geometry"]]
        self.lamps = lamp_points(lamps)
        self.hull = data_area(self.lamps)             # 밖은 '자료없음': 어두움으로 보지 않고 점수에서도 뺌

    def grade_course(self, coords, night=False):
        line = gpd.GeoSeries([LineString(coords)], crs=4326).to_crs(5179).iloc[0]
        n = max(1, math.ceil(line.length / STEP_M))
        p = gpd.GeoDataFrame(geometry=[substring(line, i * line.length / n, (i + 1) * line.length / n) for i in range(n)], crs=5179)
        p["len_m"] = p.length
        mid = gpd.GeoDataFrame(geometry=p.geometry.interpolate(0.5, normalized=True), crs=5179)
        big = gpd.sjoin(gpd.GeoDataFrame(geometry=mid.buffer(BIG_NEAR_M), crs=5179), self.big, predicate="intersects")
        cnt = gpd.sjoin(self.lamps, gpd.GeoDataFrame(geometry=p.buffer(BUF_M), crs=5179), predicate="within").groupby("index_right").size()
        p["lamps"] = p.index.map(cnt).fillna(0)
        dens = per100(p["lamps"], p["len_m"])
        inside = [self.hull.contains(m) for m in mid.geometry]
        grade = ["큰길(조명 추정)" if i in big.index else "자료없음" if not ok else "적음" if dens[i] == 0
                 else "많음" if dens[i] >= MANY else "보통" for i, ok in enumerate(inside)]
        data_ratio = sum(L for L, ok in zip(p["len_m"], inside) if ok) / p["len_m"].sum()

        segs = []                                     # 같은 등급 조각을 이어 붙임: [시작m, 끝m, 등급]
        pos = 0.0
        for g, L in zip(grade, p["len_m"]):
            if segs and segs[-1][2] == g:
                segs[-1][1] = pos + L
            else:
                segs.append([pos, pos + L, g])
            pos += L
        for s in segs:
            if s[2] == "적음" and s[1] - s[0] < DARK_RUN_M:
                s[2] = "보통"
        merged = []
        for s in segs:
            if merged and merged[-1][2] == s[2]:
                merged[-1][1] = s[1]
            else:
                merged.append(s)

        warnings = [f"{s[0]/1000:.1f}~{s[1]/1000:.1f}km 구간({s[1]-s[0]:.0f}m)은 확인된 가로등이 적어요" for s in merged if s[2] == "적음"]
        if night and warnings:
            warnings.insert(0, "밤에는 확인된 가로등이 적은 구간이 있어요. 밝은 옷과 라이트를 챙기세요")
        if any(s[2] == "자료없음" for s in merged):
            warnings.append("일부 구간은 가로등 자료가 없어 안전 정보를 표시하지 않아요")
        rated = [(WEIGHT[s[2]], s[1] - s[0]) for s in merged if s[2] in WEIGHT]
        total = sum(L for _, L in rated)
        score = round(100 * sum(w * L for w, L in rated) / total) if total else None
        level = None if score is None else next(name for cut, name in LEVELS if score >= cut)
        if score is not None and data_ratio < MIN_DATA_RATIO:
            level = "자료부족"
            warnings.append("이 경로는 가로등 자료가 있는 지역 밖이 많아 점수는 참고용이에요")
        # coverage: 보안등으로 판정한(관측) 길이 비율. 행정구역 기준 자료 확보율이지 그 구의 자료가 빠짐없다는 뜻은 아님
        # estimated: 큰길(조명 추정) 길이 비율. 점수엔 PPT 설계(도로 유형 기반)대로 들어가므로 둘을 같이 보여 줘야 함
        ratio = lambda gs: round(sum(b - a for a, b, g in merged if g in gs) / line.length, 2) if line.length else 0
        return {"score": score, "level": level, "coverage": ratio({"많음", "보통", "적음"}), "estimated": ratio({"큰길(조명 추정)"}), "segments": [{"start_m": round(a), "end_m": round(b), "grade": g} for a, b, g in merged], "warnings": warnings}


if __name__ == "__main__":
    import pandas as pd
    # 평면 좌표 대신 위경도 소수점으로 만든 가짜 지도: 동쪽으로 0.001도 ≈ 88m
    lon0, lat0 = 126.98, 37.57
    dx = lambda m: lon0 + m / 88_000
    edges = gpd.GeoDataFrame({"highway": ["residential", "primary"]},
                             geometry=[LineString([(dx(0), lat0), (dx(400), lat0)]), LineString([(dx(400), lat0), (dx(600), lat0)])], crs=4326)
    # 0~150m 보안등 촘촘, 150~350m 없음(200m → 적음), 350~400m 1개, 400~600m 큰길(보안등 없음 → 큰길(조명 추정))
    xs = [dx(m) for m in range(0, 150, 5)] + [dx(380)]
    corners = [(dx(-300), lat0 + 0.003), (dx(-300), lat0 - 0.003), (dx(900), lat0 + 0.003), (dx(900), lat0 - 0.003)]   # 자료 범위만 넓히는 먼 점
    lamps = pd.DataFrame({"경도": xs + [c[0] for c in corners], "위도": [lat0 + 0.0001] * len(xs) + [c[1] for c in corners]})
    r = SafetyIndex(edges, lamps).grade_course([(dx(0), lat0), (dx(600), lat0)], night=True)
    print(r)
    g = [s["grade"] for s in r["segments"]]
    assert "적음" in g and g[-1] == "큰길(조명 추정)" and g[0] == "많음", g
    assert r["warnings"][0].startswith("밤에는") and 0 < r["score"] < 100
    r2 = SafetyIndex(edges, lamps).grade_course([(dx(0), lat0), (dx(140), lat0)])
    assert r2["warnings"] == [] and r2["score"] == 100 and r2["level"] == "좋음", r2
    # 같은 좌표 50개(주소로 찾은 보안등)는 1개로 셈 → 어두운 구간 한가운데라도 '많음'이 되지 않음
    dup = pd.concat([lamps, pd.DataFrame({"경도": [dx(250)] * 50, "위도": [lat0 + 0.0001] * 50})])
    g3 = [s["grade"] for s in SafetyIndex(edges, dup).grade_course([(dx(200), lat0), (dx(300), lat0)])["segments"]]
    assert "많음" not in g3, g3
    # 자료 범위(약 1,000m까지) 밖은 점수에서 빼고 coverage로 알려 줌, 큰길 200m는 estimated로 따로
    r4 = SafetyIndex(edges, lamps).grade_course([(dx(0), lat0), (dx(2000), lat0)])
    assert 0.3 < r4["coverage"] < 0.5 and 0.05 < r4["estimated"] < 0.15 and "자료없음" in [s["grade"] for s in r4["segments"]], r4
    # OSM에 lit=no인 큰길은 추정하지 않음 → 보안등이 없으니 '적음' (앞 22m는 380m 지점 보안등이 잡혀 '보통')
    r5 = SafetyIndex(edges.assign(lit=["yes", "no"]), lamps).grade_course([(dx(400), lat0), (dx(600), lat0)])
    assert "큰길(조명 추정)" not in [s["grade"] for s in r5["segments"]] and r5["segments"][-1]["grade"] == "적음", r5
    r5b = SafetyIndex(edges.assign(lit=["yes", ["yes", "no"]]), lamps).grade_course([(dx(400), lat0), (dx(600), lat0)])   # 합쳐진 구간의 lit 리스트
    assert "큰길(조명 추정)" not in [s["grade"] for s in r5b["segments"]], r5b
    r5c = SafetyIndex(edges.assign(highway=["residential", ["residential", "primary"]]), lamps).grade_course([(dx(400), lat0), (dx(600), lat0)])
    assert r5c["segments"][-1]["grade"] == "큰길(조명 추정)", r5c                     # 리스트 중 하나라도 큰길이면 큰길
    # 자료 범위 밖 큰길만 지나는 경로: 추정만으로 100점이지만 level은 '자료부족'. 자료 범위 안 큰길(0~600m 구간의 400~600m)은 그대로
    far = gpd.GeoDataFrame({"highway": ["primary"]}, geometry=[LineString([(dx(3000), lat0), (dx(3600), lat0)])], crs=4326)
    r6 = SafetyIndex(pd.concat([edges, far]), lamps).grade_course([(dx(3000), lat0), (dx(3600), lat0)])
    assert r6["level"] == "자료부족" and r6["score"] == 100 and r6["warnings"][-1].endswith("참고용이에요"), r6
    r7 = SafetyIndex(edges, lamps).grade_course([(dx(400), lat0), (dx(600), lat0)])
    assert r7["level"] == "좋음" and r7["score"] == 100, r7
    print("자가 점검 통과")
