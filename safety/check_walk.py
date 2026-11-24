"""실제 서울 지도로 안전도(조명 + 보행 환경)를 실측합니다: 대표 코스 5개 + 무작위 경로 300개(1.5~5km)의 점수 분포·등급 비율·경고 수.
경로는 OSRM 대신 지도 위 networkx 최단 경로 (같은 OSM 길 위를 지나 판정은 같지만, 청계천처럼 산책로 대신 차도를 고를 수 있음).
사전 준비: pip install geopandas networkx / segment_stats.py가 만든 osm_graph_2500_v2.graphml (git에 없음, sidewalk·surface 태그 포함)
사용 (safety/ 폴더에서): python check_walk.py [지도.graphml]
2026-11-17 종로·중구 결과: 조명 평균 79·표준편차 16, 보행 평균 60·표준편차 7.9, 상관 -0.32, 계단 경고 77개"""
import ast, random, sys, collections
import networkx as nx, pandas as pd, geopandas as gpd
from shapely import wkt
from shapely.geometry import LineString
from safety import SafetyIndex

GRAPH = sys.argv[1] if len(sys.argv) > 1 else "osm_graph_2500_v2.graphml"   # 중심 (37.5685, 126.9850) 반경 2.5km
NAMED = {"청계천 청계광장→동대문": ((37.5692, 126.9779), (37.5707, 127.0071)),
         "남산 북측순환로 남산도서관→국립극장": ((37.5530, 126.9810), (37.5537, 127.0020)),
         "시청→경복궁 (세종대로)": ((37.5663, 126.9779), (37.5759, 126.9768)),
         "종로3가→혜화 (골목)": ((37.5704, 126.9918), (37.5820, 127.0016)),
         "명동→남산타워": ((37.5636, 126.9850), (37.5512, 126.9882))}   # (위도, 경도)

G = nx.read_graphml(GRAPH)
lit = lambda v: ast.literal_eval(v) if isinstance(v, str) and v.startswith("[") else v   # graphml엔 합쳐진 구간의 태그 리스트가 문자열로 저장됨
nodes = {n: (float(d["x"]), float(d["y"])) for n, d in G.nodes(data=True)}
rows, geom_of, U = [], {}, nx.Graph()
for u, v, d in G.edges(data=True):
    g = wkt.loads(d["geometry"]) if "geometry" in d else LineString([nodes[u], nodes[v]])
    rows.append(dict({c: lit(d.get(c)) for c in ("highway", "lit", "sidewalk", "sidewalk:both", "surface")}, geometry=g))
    geom_of[(u, v)] = g
    U.add_edge(u, v, length=float(d["length"]))
idx = SafetyIndex(gpd.GeoDataFrame(rows, crs=4326), pd.read_csv("서울_보안등.csv"))


def coords_of(path):
    out = []
    for u, v in zip(path, path[1:]):
        c = list((geom_of.get((u, v)) or geom_of[(v, u)]).coords)
        d = lambda p: (p[0] - nodes[u][0]) ** 2 + (p[1] - nodes[u][1]) ** 2
        if d(c[0]) > d(c[-1]):        # u에서 시작하도록 방향 보정
            c = c[::-1]
        out += c if not out else c[1:]
    return out


def nearest(lat, lon):
    return min(nodes, key=lambda n: (nodes[n][0] - lon) ** 2 + (nodes[n][1] - lat) ** 2)


for name, (a, b) in NAMED.items():
    r = idx.grade_course(coords_of(nx.shortest_path(U, nearest(*a), nearest(*b), weight="length")), night=True)
    print(f"\n■ {name}: 조명 {r['score']}({r['level']}) / 보행 {r['walk_score']}")
    print("  보행 구간:", " → ".join(f"{s['grade']} {s['end_m'] - s['start_m']}m" for s in r["walk_segments"]))
    for w in r["warnings"]:
        print("  -", w)

random.seed(0)
res, grades, warn = [], collections.Counter(), collections.Counter()
ns = list(nodes)
while len(res) < 300:
    a, b = random.sample(ns, 2)
    try:
        path = nx.shortest_path(U, a, b, weight="length")
    except nx.NetworkXNoPath:
        continue
    if not 1500 <= nx.path_weight(U, path, "length") <= 5000:
        continue
    r = idx.grade_course(coords_of(path))
    res.append((r["score"], r["walk_score"]))
    for s in r["walk_segments"]:
        grades[s["grade"]] += s["end_m"] - s["start_m"]
    for w in r["warnings"]:
        for k in ("인도가 없는", "계단", "비포장"):
            warn[k] += k in w
df = pd.DataFrame(res, columns=["조명", "보행"])
print("\n■ 무작위 경로 300개 (1.5~5km)")
print(df.describe().round(1).to_string())
print("조명·보행 상관:", round(df.corr().iloc[0, 1], 2))
print("보행 80/60 기준 등급 비율:", pd.cut(df["보행"], [-1, 59.5, 79.5, 101], labels=["주의", "보통", "좋음"]).value_counts(normalize=True).round(2).to_dict())
tot = sum(grades.values())
print("보행 등급 길이 비율:", {k: f"{v / tot:.0%}" for k, v in grades.most_common()})
print("경고 수:", dict(warn))
