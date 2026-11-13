"""팀원 검수용 채점 시트 생성: Claude 점수를 가리고 (쿼리, 장소) 100쌍을 뽑는다.

- Claude 점수별 25쌍씩 층화 추출 (0~3점이 고르게 나오게), 같은 장소는 한 번만
- label_review_sheet.xlsx: 팀원이 '팀원 점수' 열만 채움 (0~3 목록에서 선택)
- answer_key.csv: Claude 점수 (채점이 끝날 때까지 열지 않기)
- --new: 나중에 채점한 장소(labeling/scores/batch_12~16)만, 점수별 10쌍 → *_new.xlsx/csv (기존 검수 파일 유지)
"""
import argparse, csv, json, math, random
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

DATA = Path(__file__).parent.parent
OUT = Path(__file__).parent
SEED, PER_LABEL = 7, 25
NEW_BATCHES, NEW_PER_LABEL = range(12, 17), 10
DESC_WIDTH = 100
HEADER = ["번호", "취향", "시간대", "목표 거리(km)", "우회 거리(km)", "우회/목표", "장소", "카테고리", "야경명소",
          "장소 설명", "팀원 점수(0~3)", "메모"]


def main(new=False):
    rng = random.Random(SEED)
    per_label, suffix = (NEW_PER_LABEL, "_new") if new else (PER_LABEL, "")
    only = {l.split(",")[0] for b in NEW_BATCHES
            for l in (DATA / f"labeling/scores/batch_{b}.csv").read_text(encoding="utf-8").splitlines() if l} if new else None
    with (DATA / "places.csv").open(encoding="utf-8-sig") as f:
        places = {p["place_id"]: p for p in csv.DictReader(f)}
    queries = {json.loads(l)["query_id"]: json.loads(l) for l in (DATA / "queries.jsonl").read_text(encoding="utf-8").splitlines() if l}
    labels = [json.loads(l) for l in (DATA / "labels.jsonl").read_text(encoding="utf-8").splitlines() if l]

    by_label = {k: [] for k in range(4)}
    for r in labels:
        q = queries[r["query_id"]]
        for c in q["candidates"]:
            if only is not None and c["place_id"] not in only:
                continue
            by_label[r["labels"][c["place_id"]]].append((q, c))

    picked, used = [], set()
    for k in range(4):
        rng.shuffle(by_label[k])
        n = 0
        for q, c in by_label[k]:
            if c["place_id"] in used:
                continue
            used.add(c["place_id"])
            picked.append((q, c, k))
            n += 1
            if n == per_label:
                break
    rng.shuffle(picked)

    sheet = OUT / f"label_review_sheet{suffix}.xlsx"
    key = OUT / f"answer_key{suffix}.csv"
    wb = Workbook()
    ws = wb.active
    ws.title = "채점"
    ws.append(HEADER)
    with key.open("w", encoding="utf-8-sig", newline="") as fk:
        wk = csv.writer(fk)
        wk.writerow(["번호", "query_id", "place_id", "Claude 점수"])
        for i, (q, c, k) in enumerate(picked, 1):
            p = places[c["place_id"]]
            ws.append([i, " + ".join(q["prefs"]), "밤" if q["time_slot"] == "night" else "낮", q["target_km"],
                       round(c["detour_km"], 2), f"{c['detour_km'] / q['target_km']:.0%}", p["title"], p["category"],
                       "예" if p["night_spot"] == "1" else "", p["overview"], None, None])
            wk.writerow([i, q["query_id"], c["place_id"], k])
    format_sheet(ws, len(picked))
    wb.save(sheet)
    print(f"채점 시트 {len(picked)}쌍 → {sheet}\n정답 키 → {key} (채점 끝날 때까지 열지 않기)")


def format_sheet(ws, n):
    """긴 설명이 셀 안에 다 보이게 줄 바꿈·열 너비·행 높이 설정, 점수 칸은 0~3 목록"""
    for col, width in zip("ABCDEFGHIJKL", [6, 18, 7, 9, 9, 8, 18, 10, 8, DESC_WIDTH, 10, 20]):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=1, max_row=n + 1):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="DDEBF7")
    for r in range(2, n + 2):
        lines = math.ceil(len(ws.cell(r, 10).value) / (DESC_WIDTH * 0.5)) + 1  # 한글은 글자당 약 2칸
        ws.row_dimensions[r].height = min(409, 15 * lines)                     # 엑셀 행 높이 최대 409
        ws.cell(r, 11).fill = PatternFill("solid", fgColor="FFF2CC")           # 채울 칸 표시
    dv = DataValidation(type="list", formula1='"0,1,2,3"', allow_blank=True)
    ws.add_data_validation(dv)
    dv.add(f"K2:K{n + 1}")
    ws.freeze_panes = "B2"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", action="store_true", help="batch_12~16 장소만 (점수별 10쌍)")
    main(ap.parse_args().new)
