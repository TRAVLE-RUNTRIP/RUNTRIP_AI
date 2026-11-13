"""팀원 채점 결과와 Claude 점수 비교.

실행: python data/review/compare_review.py data/review/이민구.xlsx [다른 팀원 시트.xlsx ...]
      새 장소 검수: ... --key data/review/answer_key_new.csv 시트.xlsx
지표: 정확히 일치, ±1점 이내, 가중 카파(quadratic weighted kappa, 1=완전 일치, 0=우연 수준)
"""
import argparse, csv
from pathlib import Path

KEY = Path(__file__).parent / "answer_key.csv"


def read(path, col):
    """채점 시트(.xlsx) 또는 CSV에서 {번호: 점수}"""
    if str(path).endswith(".xlsx"):
        from openpyxl import load_workbook
        rows = load_workbook(path, read_only=True).active.iter_rows(values_only=True)
        header = list(next(rows))
        recs = [dict(zip(header, r)) for r in rows]
    else:
        with open(path, encoding="utf-8-sig") as f:
            recs = list(csv.DictReader(f))
    return {str(r["번호"]): int(r[col]) for r in recs if r[col] is not None and str(r[col]).strip()}


def weighted_kappa(a, b, k=4):
    n = len(a)
    obs = [[0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[x][y] += 1
    ra = [sum(row) for row in obs]
    rb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    w = lambda i, j: (i - j) ** 2 / (k - 1) ** 2
    o = sum(w(i, j) * obs[i][j] for i in range(k) for j in range(k)) / n
    e = sum(w(i, j) * ra[i] * rb[j] for i in range(k) for j in range(k)) / n ** 2
    return 1 - o / e, obs


def compare(name_a, a, name_b, b):
    ids = sorted(set(a) & set(b), key=int)
    x, y = [a[i] for i in ids], [b[i] for i in ids]
    exact = sum(p == q for p, q in zip(x, y)) / len(ids)
    within1 = sum(abs(p - q) <= 1 for p, q in zip(x, y)) / len(ids)
    kappa, obs = weighted_kappa(x, y)
    print(f"\n[{name_a} vs {name_b}] {len(ids)}쌍: 정확히 일치 {exact:.0%}, ±1점 이내 {within1:.0%}, 가중 카파 {kappa:.2f}")
    print(f"  행={name_a} 점수, 열={name_b} 점수")
    for i, row in enumerate(obs):
        print(f"  {i}점: {row}")
    gaps = [(i, a[i], b[i]) for i in ids if abs(a[i] - b[i]) >= 2]
    if gaps:
        print("  2점 이상 차이 (번호, 앞, 뒤):", gaps)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheets", nargs="+")
    ap.add_argument("--key", default=KEY)
    args = ap.parse_args()
    claude = read(args.key, "Claude 점수")
    sheets = {Path(p).stem: read(p, "팀원 점수(0~3)") for p in args.sheets}
    for name, s in sheets.items():
        compare(name, s, "Claude", claude)
    names = list(sheets)
    for i in range(len(names)):  # 팀원끼리도 비교 (사람 간 일치도 = 목표치의 상한)
        for j in range(i + 1, len(names)):
            compare(names[i], sheets[names[i]], names[j], sheets[names[j]])


if __name__ == "__main__":
    main()
