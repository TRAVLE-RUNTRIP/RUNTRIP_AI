"""도로 구간(OSM)마다 보안등이 몇 개 있는지 세어, 점수 규칙의 기준값(가로등 밀도 등)을 정하는 데 씁니다.
사전 준비: pip install osmnx   (geopandas 포함)   / merge_lamps.py로 만든 서울_보안등.csv
사용: python segment_stats.py [서울_보안등.csv] [반경(m)]
주의: 기준값은 종로구·중구 구간만으로 집계합니다 (마포·용산은 주소로 찾은 좌표라 기준 산정에서 뺌). 자료 없는 곳의 0개를 '어두움'으로 보지 않기 위해서예요."""
import sys
import numpy as np
import pandas as pd
import geopandas as gpd
from shapely.ops import unary_union

BUF_M = 30                                   # 도로에서 30m 안의 보안등만 그 구간 것으로 셈
CENTER, DIST = (37.5685, 126.9850), 2500     # 시청~종로 사이 중심, 반경 2.5km (더 크게: 2번째 인자로 미터 단위 지정)
ROAD = ["primary", "secondary", "tertiary", "residential", "living_street", "unclassified"]
FOOT = ["pedestrian", "footway", "path", "steps"]


def lamp_points(lamps):
    """보안등 DataFrame → 조명 지점 GeoDataFrame(EPSG:5179, gu 열). 같은 좌표는 1개로 셈: 주소로 좌표를 찾은 보안등은 한 점에 수십 개씩 몰려 있음"""
    d = lamps.drop_duplicates(["위도", "경도"])
    gu = d["관리기관명"].values if "관리기관명" in d else [0] * len(d)
    return gpd.GeoDataFrame({"gu": gu}, geometry=gpd.points_from_xy(d["경도"], d["위도"]), crs=4326).to_crs(5179)


def data_area(g):
    """보안등 자료가 있는 지역. 구마다 따로 감쌈: 한꺼번에 감싸면 사이에 낀 자료 없는 구까지 '적음'이 됨"""
    return unary_union(list(g.dissolve("gu").convex_hull.buffer(100)))


def per100(n, len_m, buf=BUF_M):
    """100m당 조명 지점 수. 띠는 선 양끝으로도 buf만큼 나가므로 실제로 센 길이(len + 2·buf)로 나눔 → 25m 조각이든 긴 도로 구간이든 같은 기준"""
    return n / (len_m + 2 * buf) * 100


def analyze(edges, lamps, buf=BUF_M):
    """edges: EPSG:4326 GeoDataFrame(highway 열), lamps: 위도·경도 열이 있는 DataFrame → 구간별 보안등 수·밀도"""
    e = edges.to_crs(5179).reset_index(drop=True)
    e["eid"] = e.index
    e["hw"] = e["highway"].apply(lambda v: v[0] if isinstance(v, list) else v)
    e["len_m"] = e.geometry.length
    g = lamp_points(lamps)
    hull = data_area(g)
    mid = e.geometry.interpolate(0.5, normalized=True)
    e = e[mid.within(hull)].copy()           # 보안등 자료가 있는 지역의 구간만
    zone = e[["eid", "geometry"]].copy()
    zone["geometry"] = zone.geometry.buffer(buf)                     # 구간 양옆 30m 띠
    j = gpd.sjoin(g[["geometry"]], zone, how="inner", predicate="within")
    e["lamps"] = e["eid"].map(j.groupby("eid").size()).fillna(0)   # 도로 옆 보도에 있어도 도로 구간에 포함
    e["per100"] = per100(e["lamps"], e["len_m"], buf)
    return e


def report(e):
    print(f"\n집계 대상 구간 {len(e)}개, 총 {e['len_m'].sum()/1000:.0f}km")
    print(f"{'도로유형':14s}{'구간수':>7s}{'길이km':>8s}{'1개이상%':>9s}{'100m당 중앙':>11s}{'p25':>6s}{'p75':>6s}{'p90':>6s}")
    for hw in ROAD + FOOT:
        s = e[e["hw"] == hw]
        if len(s) == 0:
            continue
        q = s["per100"].quantile([.25, .5, .75, .9]).values
        print(f"{hw:14s}{len(s):7d}{s['len_m'].sum()/1000:8.1f}{(s['lamps']>0).mean()*100:8.0f}%{q[1]:11.2f}{q[0]:6.2f}{q[2]:6.2f}{q[3]:6.2f}")
    r = e[e["hw"].isin(ROAD)]
    q = r["per100"].quantile([.1, .25, .5, .75, .9]).round(2).to_dict()
    print("\n[차도·골목 전체] 100m당 보안등 분위수:", q)
    for col in ["lit", "sidewalk"]:
        if col in e.columns:
            t = e[e["hw"].isin(ROAD + FOOT)]
            print(f"\n[{col} 태그] 태그가 있는 구간 비율: {t[col].notna().mean():.0%}")
            print("  도로유형별 비율:", t.groupby("hw")[col].apply(lambda x: x.notna().mean()).round(2).to_dict())
            print("  값 분포:", t[col].astype(str).value_counts().head(6).to_dict())
        else:
            print(f"\n[{col}] 열이 없습니다 (OSM에 태그가 없거나 받지 못함)")
    print("→ 위 표와 분위수를 그대로 알려 주세요. '가로등 적음/보통/많음' 기준을 여기서 정합니다.")


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "서울_보안등.csv"
    lamps = pd.read_csv(path, encoding="utf-8-sig")
    gu = lamps["관리기관명"].astype(str)
    lamps = lamps[gu.str.contains("종로구|중구")]            # 자료가 충분한 구만
    print("사용 보안등:", len(lamps), "개 (종로구·중구)")
    import os
    import osmnx as ox
    dist = int(sys.argv[2]) if len(sys.argv) > 2 else DIST
    cache = f"osm_graph_{dist}_v2.graphml"                    # 한 번 받으면 저장해 두고 다음엔 바로 불러옴
    if os.path.exists(cache):
        print("저장해 둔 지도를 불러옵니다:", cache)
        G = ox.load_graphml(cache)
    else:
        ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both", "lit", "footway", "surface"]))
        ox.settings.log_console = True                     # 내려받는 진행 상황을 화면에 표시
        print(f"OSM 도로를 내려받는 중입니다 (반경 {dist}m, 몇 분 걸릴 수 있어요)...")
        try:
            G = ox.graph_from_point(CENTER, dist=dist, network_type="all")
            ox.save_graphml(G, cache)
            print("내려받기 완료, 저장:", cache)
        except Exception as ex:                            # Overpass 서버가 자주 끊김 → 예전에 받아 둔 지도로 대신 집계
            old = "osm_graph_1500.graphml"
            if not os.path.exists(old):
                raise
            print(f"내려받기 실패({type(ex).__name__}). 예전 지도 {old}로 대신 집계합니다 (반경 1500m, lit·sidewalk 태그 없음)")
            G = ox.load_graphml(old)
    edges = ox.graph_to_gdfs(G, nodes=False)
    print("도로 구간 수:", len(edges))
    report(analyze(edges, lamps))
