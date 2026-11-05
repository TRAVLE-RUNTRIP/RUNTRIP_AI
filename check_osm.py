import osmnx as ox

ox.settings.useful_tags_way = list(set(ox.settings.useful_tags_way + ["sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"]))   # 기본값엔 sidewalk가 없어 항상 0%로 나옴

for name, pt in {"시청(중구)": (37.5663, 126.9779), "홍대입구(마포)": (37.5572, 126.9245), "여의도(영등포)": (37.5284, 126.9328), "서울숲(성동)": (37.5444, 127.0374), "잠실(송파)": (37.5133, 127.1002), "강남역(강남)": (37.4979, 127.0276)}.items():
    G = ox.graph_from_point(pt, dist=2000, network_type="all")
    e = ox.graph_to_gdfs(G, nodes=False)
    hw = e["highway"].apply(lambda v: v[0] if isinstance(v, list) else v)
    print(f"\n[{name}] 전체 구간 {len(e)}개")
    print(hw.value_counts().head(8))
    road = e[hw.isin(["primary", "secondary", "tertiary", "residential", "unclassified", "living_street"])]
    share = road["sidewalk"].notna().mean() if "sidewalk" in road.columns else 0
    print(f"차도 구간 {len(road)}개 중 sidewalk 태그 있는 비율: {share:.0%}")
