"""서울 전체 도로 지도를 AI 서버 /safety가 읽을 파일(서울_도로.parquet)로 저장합니다. 한 번만 실행하면 됩니다.
원본은 OSRM과 같은 osrm/south-korea-latest.osm.pbf (경로를 만든 지도와 같은 길을 판정, 인터넷 불필요). GDAL OSM 드라이버로 읽음
사전 준비: pip install geopandas pyarrow   (pyogrio에 GDAL 포함) / README 1장대로 받은 osrm/south-korea-latest.osm.pbf
사용 (safety/ 폴더에서): python build_roads.py [pbf 경로]
열: highway, lit, sidewalk, sidewalk:both, surface, geometry(EPSG:4326). SafetyIndex가 쓰는 태그만 남김.
OSM way 단위 그대로 (교차로에서 자르지 않음): SafetyIndex는 가까운 길·큰길 띠만 보므로 판정은 같음"""
import re
import sys
import time
import geopandas as gpd
import pyogrio

PBF = sys.argv[1] if len(sys.argv) > 1 else "../osrm/south-korea-latest.osm.pbf"
OUT = "서울_도로.parquet"
TAGS = ["lit", "sidewalk", "sidewalk:both", "surface"]
SKIP = {"abandoned", "construction", "no", "planned", "platform", "proposed", "raceway", "razed"}   # OSMnx network_type="all"과 같은 제외 목록


def tag(other, key):
    """GDAL other_tags('"k"=>"v","k2"=>"v2"')에서 값 하나"""
    m = re.search(rf'"{re.escape(key)}"=>"([^"]*)"', other) if isinstance(other, str) else None   # 태그 없으면 NaN
    return m.group(1) if m else None


if __name__ == "__main__":
    t = time.time()
    area = gpd.read_file("서울_구경계.geojson").to_crs(5179).union_all().buffer(300)   # 경계 근처 경로도 판정
    poly = gpd.GeoSeries([area], crs=5179).to_crs(4326)
    e = pyogrio.read_dataframe(PBF, layer="lines", bbox=tuple(poly.total_bounds), where="highway IS NOT NULL", columns=["highway", "other_tags"])
    e = e[~e["highway"].isin(SKIP) & (e["other_tags"].map(lambda o: tag(o, "area")) != "yes")]
    e = e[e.intersects(poly.iloc[0])]
    for k in TAGS:
        e[k] = e["other_tags"].map(lambda o, k=k: tag(o, k)).astype("string")
    e = e[["highway"] + TAGS + ["geometry"]].reset_index(drop=True)
    e.to_parquet(OUT)
    print(f"{len(e):,}개 길, {time.time() - t:.0f}초 → {OUT}")
    print(e["highway"].value_counts().head(10).to_string())
    print("태그 있는 비율:", {k: f"{e[k].notna().mean():.0%}" for k in TAGS})
