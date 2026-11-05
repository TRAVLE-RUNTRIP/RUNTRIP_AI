"""TourAPI 수집 결과 + 서울시 야경명소 CSV → data/places.csv

합치기 규칙 (Notion '데이터·API 구성' 3장):
- 둘 다 있음(좌표 MATCH_M 이내 + 이름 유사): TourAPI 개요 뒤에 야경명소 소개를 덧붙이고 night_spot=1
- 야경명소에만 있음: 새 장소로 추가, night_spot=1, category는 CSV 분류로 (공원/광장 → 자연·공원, 나머지 → 관광 명소)
- TourAPI에만 있음: 그대로
category는 관광 명소 / 자연·공원 / 기타 3개. 야경 여부는 night_spot으로 따로 표시한다.
"""
import csv, html, json, math, re
from difflib import SequenceMatcher
from pathlib import Path

HERE = Path(__file__).parent
NIGHT_CSV = HERE.parent / "서울시 야경명소 정보.csv"
MATCH_M = 300
EXACT_M = 1500  # 공원·하천처럼 넓은 장소는 대표 좌표가 서로 멀 수 있음
# 자동 매칭이 놓치는 경우 수동 지정 (야경명소 장소명 → TourAPI title)
MANUAL = {"창덕궁": "창덕궁과 후원 [유네스코 세계유산]", "청계천": "청계천", "석촌호수 루미나리에(송파나루공원)": "석촌호수"}
DROP_LCLS3 = {"VE050100"}  # 관광특구(지역 단위)


def category(lcls3):
    if lcls3.startswith(("NA", "VE03")) or lcls3 in {"VE040300", "LS011900", "LS010200"}:
        return "자연·공원"
    if lcls3.startswith(("HS", "VE01", "VE02")) or lcls3 in {"VE040100", "VE040200", "EX061000", "EX070100"}:
        return "관광 명소"
    if lcls3.startswith("VE07") and lcls3 != "VE070400":
        return "관광 명소"
    return "기타"


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def norm(name):
    return re.sub(r"\(.*?\)|[\s\-·]", "", name)


def match_score(night_name, tour_name, dist):
    """0이면 매칭 안 함. 이름 완전 일치는 EXACT_M까지, 나머지는 MATCH_M 이내에서 유사도로."""
    a, b = norm(night_name), norm(tour_name)
    if a == b:
        return 2.0 if dist <= EXACT_M else 0
    if dist > MATCH_M:
        return 0
    ratio = SequenceMatcher(None, a, b).ratio()
    # 야경명소 이름이 TourAPI 이름을 포함 (예: '낙산공원 - 한양도성 성곽길' ⊃ '낙산공원')
    if len(b) >= 3 and b in a:
        return 1.0 + ratio
    # TourAPI 이름이 더 구체적인 경우(예: '세빛섬 튜브스터')는 유사도가 높을 때만
    return ratio if ratio >= 0.75 else 0


def meters(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    h = math.sin((lat2 - lat1) * p / 2) ** 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lng2 - lng1) * p / 2) ** 2
    return 12742000 * math.asin(math.sqrt(h))


def main():
    tour = json.loads((HERE / "raw/tourapi_list.json").read_text(encoding="utf-8"))
    overviews = {}
    for line in (HERE / "raw/tourapi_overview.jsonl").read_text(encoding="utf-8").splitlines():
        if line:
            r = json.loads(line)
            overviews[r["contentid"]] = r["overview"]

    places = []
    for p in tour:
        if p["lclsSystm3"] in DROP_LCLS3:
            continue
        places.append({
            "place_id": f"T{p['contentid']}", "contentid": p["contentid"], "title": p["title"],
            "category": category(p["lclsSystm3"]), "night_spot": 0, "source": "tourapi",
            "lcls3": p["lclsSystm3"], "contenttypeid": p["contenttypeid"],
            "lat": float(p["mapy"]), "lng": float(p["mapx"]),
            "overview": clean(overviews.get(p["contentid"], "")),
            "firstimage": p.get("firstimage", ""), "cpyrht": p.get("cpyrhtDivCd", ""),
        })

    with NIGHT_CSV.open(encoding="cp949") as f:
        night = list(csv.DictReader(f))
    matched = 0
    for n in night:
        lat, lng, intro = float(n["위도"]), float(n["경도"]), clean(n["내용"])
        cands = []
        for p in places:
            if p["source"] == "seoul_night":
                continue
            d = meters(lat, lng, p["lat"], p["lng"])
            s = 3.0 if MANUAL.get(n["장소명"]) == p["title"] else match_score(n["장소명"], p["title"], d)
            if s:
                cands.append((s, -d, p))
        if cands:
            _, neg_d, p = max(cands, key=lambda x: x[:2])
            d = -neg_d
            p["overview"] = f"{p['overview']} {intro}".strip()
            p["night_spot"], p["source"] = 1, "both"
            matched += 1
            print(f"  매칭: {n['장소명']} ↔ {p['title']} ({d:.0f}m)")
        else:
            places.append({
                "place_id": f"N{n['번호']}", "contentid": "", "title": n["장소명"],
                "category": "자연·공원" if n["분류"] == "공원/광장" else "관광 명소",
                "night_spot": 1, "source": "seoul_night",
                "lcls3": "", "contenttypeid": "", "lat": lat, "lng": lng,
                "overview": intro, "firstimage": "", "cpyrht": "",
            })

    out = HERE / "places.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(places[0]))
        w.writeheader()
        w.writerows(places)

    from collections import Counter
    print(f"\n야경명소 {len(night)}곳: 매칭 {matched} / 신규 {len(night) - matched}")
    print(f"places.csv: {len(places)}곳 → {out}")
    print("카테고리:", dict(Counter(p["category"] for p in places)))
    print("개요 없음:", sum(1 for p in places if not p["overview"]))


if __name__ == "__main__":
    main()
