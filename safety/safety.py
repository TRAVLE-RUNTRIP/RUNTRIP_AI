"""코스 경로를 받아 안전도를 계산합니다: 조명(가로등 등급·야간 경고·score 0~100)과 보행 환경(길 종류·인도 없음·계단·비포장, walk_score 0~100). 경로는 바꾸지 않고 조언만 합니다.
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

# 보행 환경: 경로 25m 조각마다 가장 가까운 OSM 길의 종류로 판정. sidewalk 태그는 차도의 약 7%에만 있어 명시된 no만 '인도 없음' (종로·중구 2026-11-17)
# 가중치 F안 (2026-11-17, 종로·중구 무작위 경로 300개): 대로를 크게 깎으면 조명의 '큰길 추정'을 뒤집은 값이 됨(상관 -0.6) → 대로 0.5로 상관 -0.33
# ponytail: 가중치는 임시값, 팀 합의·완주 로그로 조정. 조명 score와 합칠지도 미정이라 따로 냄
WALK_WEIGHT = {"보행로": 1.0, "골목": 0.7, "계단": 0.6, "비포장": 0.6, "대로": 0.5, "좁은 차도": 0.2, "인도 없음": 0.0}
FOOT = {"footway", "pedestrian", "path", "cycleway", "living_street"}
CAR = BIG | {"tertiary"}                              # + *_link. BIG = 대로, 나머지 = 좁은 차도
SHORT_M = 50                                          # 이보다 짧은 보행 구간은 앞 구간에 합침 (교차로에서 25m씩 끊겨 지도가 얼룩덜룩해짐)
KEEP_SHORT = {"인도 없음"}                            # 짧아도 위험하니 합치지 않음
UNPAVED = {"unpaved", "dirt", "earth", "ground", "gravel", "grass", "sand", "mud", "pebblestone"}
SNAP_M = 15                                           # OSRM 경로는 OSM 길 위를 지나므로 15m 안에 길이 없으면 '자료없음'
WALK_WARN = {"인도 없음": "인도가 없는 차도예요", "계단": "계단이 있어요", "비포장": "비포장 길이에요"}


def walk_grade(hw, surface, sidewalk, both):
    first = lambda v: v[0] if isinstance(v, list) else v   # 합쳐진 구간은 태그가 리스트
    hw = str(first(hw))
    if hw == "steps":
        return "계단"
    if first(surface) in UNPAVED:
        return "비포장"
    if hw in FOOT:
        return "보행로"
    if hw in CAR or hw.endswith("_link"):
        return "인도 없음" if "no" in (first(sidewalk), first(both)) else "대로" if hw in BIG else "좁은 차도"
    return "골목"


def absorb_short(segs):
    """SHORT_M 미만 구간을 앞 구간에 합침 (첫 구간이면 다음 구간에). KEEP_SHORT 등급은 남기고, 그 구간이 다른 구간을 흡수하지도 않음"""
    short = lambda s: s[1] - s[0] < SHORT_M and s[2] not in KEEP_SHORT
    out = []
    for s in segs:
        if out and short(s) and out[-1][2] not in KEEP_SHORT:
            out[-1][1] = s[1]
        else:
            out.append(list(s))
    if len(out) > 1 and short(out[0]) and out[1][2] not in KEEP_SHORT:
        start = out.pop(0)[0]
        out[0][0] = start
    return runs([g for _, _, g in out], [b - a for a, b, _ in out])


def runs(labels, lens):
    """같은 등급 조각을 이어 붙임 → [[시작m, 끝m, 등급], ...]"""
    out, pos = [], 0.0
    for g, L in zip(labels, lens):
        if out and out[-1][2] == g:
            out[-1][1] = pos + L
        else:
            out.append([pos, pos + L, g])
        pos += L
    return out


def score_of(segs, weight):
    rated = [(weight[g], b - a) for a, b, g in segs if g in weight]
    total = sum(L for _, L in rated)
    return round(100 * sum(w * L for w, L in rated) / total) if total else None


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
        tags = e.reindex(columns=["highway", "surface", "sidewalk", "sidewalk:both"])   # 없는 태그 열은 빈 값 (OSMnx 기본 설정엔 sidewalk·surface 없음)
        tags = tags.astype(object).where(tags.notna(), None)   # parquet의 빈 값(pd.NA)은 비교하면 오류 → None
        self.walk = gpd.GeoDataFrame({"grade": [walk_grade(*t) for t in tags.itertuples(index=False)]}, geometry=e.geometry, crs=5179)

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

        segs = runs(grade, p["len_m"])
        for s in segs:
            if s[2] == "적음" and s[1] - s[0] < DARK_RUN_M:
                s[2] = "보통"
        merged = runs([s[2] for s in segs], [s[1] - s[0] for s in segs])
        near = gpd.sjoin_nearest(mid, self.walk, max_distance=SNAP_M)
        near = near[~near.index.duplicated()]["grade"]   # 같은 거리의 길이 여럿이면 첫 번째
        walk = absorb_short(runs([near.get(i, "자료없음") for i in range(n)], p["len_m"]))

        warnings = [f"{s[0]/1000:.1f}~{s[1]/1000:.1f}km 구간({s[1]-s[0]:.0f}m)은 확인된 가로등이 적어요" for s in merged if s[2] == "적음"]
        if night and warnings:
            warnings.insert(0, "밤에는 확인된 가로등이 적은 구간이 있어요. 밝은 옷과 라이트를 챙기세요")
        if any(s[2] == "자료없음" for s in merged):
            warnings.append("일부 구간은 가로등 자료가 없어 안전 정보를 표시하지 않아요")
        warnings += [f"{a/1000:.1f}~{b/1000:.1f}km 구간({b-a:.0f}m)은 {WALK_WARN[g]}" for a, b, g in walk if g in WALK_WARN]
        score = score_of(merged, WEIGHT)
        level = None if score is None else next(name for cut, name in LEVELS if score >= cut)
        if score is not None and data_ratio < MIN_DATA_RATIO:
            level = "자료부족"
            warnings.append("이 경로는 가로등 자료가 있는 지역 밖이 많아 점수는 참고용이에요")
        # coverage: 보안등으로 판정한(관측) 길이 비율. 행정구역 기준 자료 확보율이지 그 구의 자료가 빠짐없다는 뜻은 아님
        # estimated: 큰길(조명 추정) 길이 비율. 점수엔 PPT 설계(도로 유형 기반)대로 들어가므로 둘을 같이 보여 줘야 함
        ratio = lambda gs: round(sum(b - a for a, b, g in merged if g in gs) / line.length, 2) if line.length else 0
        return {"score": score, "level": level, "coverage": ratio({"많음", "보통", "적음"}), "estimated": ratio({"큰길(조명 추정)"}), "segments": [{"start_m": round(a), "end_m": round(b), "grade": g} for a, b, g in merged],
                "walk_score": score_of(walk, WALK_WEIGHT), "walk_segments": [{"start_m": round(a), "end_m": round(b), "grade": g} for a, b, g in walk], "warnings": warnings}


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
    assert r2["walk_score"] == 70 and r2["walk_segments"][0]["grade"] == "골목", r2   # sidewalk·surface 열 없는 지도도 동작
    r2b = SafetyIndex(edges, lamps).grade_course([(dx(0), lat0), (dx(600), lat0)])
    assert [s["grade"] for s in r2b["walk_segments"]] == ["골목", "대로"], r2b
    # 보행 환경: 보행로 200m · 계단 100m · 인도 없는 큰길 150m · 자갈 골목 150m
    w = gpd.GeoDataFrame({"highway": ["footway", "steps", "primary", "residential"], "sidewalk": [None, None, "no", None], "surface": [None, None, None, "gravel"]},
                         geometry=[LineString([(dx(a), lat0), (dx(b), lat0)]) for a, b in [(0, 200), (200, 300), (300, 450), (450, 600)]], crs=4326)
    r8 = SafetyIndex(w, lamps).grade_course([(dx(0), lat0), (dx(600), lat0)])
    assert [s["grade"] for s in r8["walk_segments"]] == ["보행로", "계단", "인도 없음", "비포장"], r8
    # 짧은 구간 합치기: 25m 골목은 보행로에 합쳐지고, 30m 인도 없음은 남음
    w2 = gpd.GeoDataFrame({"highway": ["footway", "residential", "footway", "tertiary", "footway"], "sidewalk": [None, None, None, "no", None]},
                          geometry=[LineString([(dx(a), lat0), (dx(b), lat0)]) for a, b in [(0, 200), (200, 225), (225, 400), (400, 430), (430, 600)]], crs=4326)
    g9 = [s["grade"] for s in SafetyIndex(w2, lamps).grade_course([(dx(0), lat0), (dx(600), lat0)])["walk_segments"]]
    assert g9 == ["보행로", "인도 없음", "보행로"], g9
    r9 = SafetyIndex(w2, lamps).grade_course([(dx(190), lat0), (dx(600), lat0)])   # 첫 구간(짧은 골목)이 다음 구간에 합쳐짐
    ws = r9["walk_segments"]
    assert [s["grade"] for s in ws] == ["보행로", "인도 없음", "보행로"] and ws[0]["start_m"] == 0, ws
    assert all(a["end_m"] == b["start_m"] for a, b in zip(ws, ws[1:])) and ws[-1]["end_m"] == r9["segments"][-1]["end_m"], ws   # 빈틈·겹침 없이 경로 끝까지
    assert 50 < r8["walk_score"] < 65 and sum(x.endswith(("차도예요", "계단이 있어요", "비포장 길이에요")) for x in r8["warnings"]) == 3, r8
    assert SafetyIndex(w, lamps).grade_course([(dx(0), lat0 + 0.001), (dx(100), lat0 + 0.001)])["walk_score"] is None   # 길에서 110m 떨어진 경로 → 자료없음
    print("자가 점검 통과")
