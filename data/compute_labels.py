"""장소 단위 채점(labeling/scores/*.csv) + queries.jsonl → labels.jsonl

규칙 (labeling_guide.md v0.3):
  취향별 기본 점수 → 주간 야경 −1 → 야간 closed_night −1 → 야간 야경 취향 + 야경명소 +1
  → 취향 중 최댓값 → detour_km > 목표거리 × 0.5 이면 −1 → 0~3으로 자름
"""
import csv, json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
PREF_COL = {"야경": 0, "관광 명소": 1, "자연·공원": 2}
DETOUR_RATIO = 0.5


def load_night_spots():
    with (HERE / "places.csv").open(encoding="utf-8-sig") as f:
        return {p["place_id"] for p in csv.DictReader(f) if p["night_spot"] == "1"}


def load_scores():
    scores = {}
    for f in sorted((HERE / "labeling/scores").glob("batch_*.csv")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                pid, n, s, t, c = line.strip().split(",")
                scores[pid] = ([int(n), int(s), int(t)], int(c))
    return scores


def label(base, closed_night, prefs, time_slot, detour_km, target_km, night_spot=False):
    best = 0
    for p in prefs:
        s = base[PREF_COL[p]]
        if p == "야경" and time_slot == "day":
            s -= 1
        if time_slot == "night" and closed_night:
            s -= 1
        if p == "야경" and time_slot == "night" and night_spot:  # 서울시 야경명소는 밤에 우대
            s += 1
        best = max(best, s)
    if detour_km > target_km * DETOUR_RATIO:
        best -= 1
    return max(0, min(3, best))


def main():
    scores = load_scores()
    night_spots = load_night_spots()
    queries = [json.loads(l) for l in (HERE / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l]
    out = []
    for q in queries:
        labels = {
            c["place_id"]: label(*scores[c["place_id"]], q["prefs"], q["time_slot"], c["detour_km"], q["target_km"],
                                 c["place_id"] in night_spots)
            for c in q["candidates"]
        }
        out.append({"query_id": q["query_id"], "labels": labels})
    with (HERE / "labels.jsonl").open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 리포트
    dist = Counter(v for r in out for v in r["labels"].values())
    total = sum(dist.values())
    print(f"labels.jsonl: 쿼리 {len(out)}건, 쌍 {total}개")
    print("점수 분포:", {k: f"{dist[k] / total:.0%}" for k in range(4)})
    no2 = sum(1 for r in out if max(r["labels"].values()) < 2)
    no3 = sum(1 for r in out if max(r["labels"].values()) < 3)
    print(f"2점 이상이 하나도 없는 쿼리: {no2}건 ({no2 / len(out):.0%}), 3점이 없는 쿼리: {no3}건 ({no3 / len(out):.0%})")

    # 기준 예시와 비교
    ex_path = HERE / "labels_examples.jsonl"
    if ex_path.exists():
        computed = {r["query_id"]: r["labels"] for r in out}
        diff = []
        n = 0
        skipped = 0
        for line in ex_path.read_text(encoding="utf-8").splitlines():
            ex = json.loads(line)
            if set(ex["labels"]) != set(computed.get(ex["query_id"], {})):
                skipped += 1  # 쿼리를 다시 생성해 후보가 달라진 예시
                continue
            for pid, v in ex["labels"].items():
                n += 1
                if computed[ex["query_id"]][pid] != v:
                    diff.append((ex["query_id"], pid, v, computed[ex["query_id"]][pid]))
        print(f"기준 예시와 일치: {n - len(diff)}/{n} (후보가 달라져 건너뛴 예시 쿼리 {skipped}건)")
        for d in diff:
            print("  불일치 (쿼리, 장소, 예시, 계산):", d)


if __name__ == "__main__":
    main()
