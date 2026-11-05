"""결과표 작성 + 선정 규칙 적용 → results/summary.md (노션 6장 표에 그대로 붙여넣기)"""
import json
import config as C

NAMES = {"baseline": "규칙 기준선", "A": "A. Pointwise", "B": "B. Pairwise", "C": "C. Listwise"}
OWNER = {"baseline": "장현서", "A": "팀원1", "B": "팀원2", "C": "장현서"}


def fmt(v):
    return f"{v['mean']:.4f} ± {v['std']:.4f}" if isinstance(v, dict) else f"{v:.4f}"


def main():
    rows, res = [], {}
    for k in ["baseline", "A", "B", "C"]:
        p = C.RESULT_DIR / f"{k}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())
        res[k] = r
        m = r if k == "baseline" else r["test"]
        hp = "-" if k == "baseline" else ", ".join(f"{a}={b}" for a, b in r["best_hp"].items())
        rows.append(f"| {NAMES[k]} | {OWNER[k]} | {fmt(m['ndcg@5'])} | {fmt(m['hit@5'])} | "
                    f"{fmt(m['taste_match'])} | {fmt(m['infer_ms'])} | {hp} |  |")

    head = ("| 모델 | 담당 | NDCG@5 | HitRate@5 | 취향 일치율 | 추론 시간(ms) | 최적 하이퍼파라미터 | 메모 |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- |")
    text = "## 결과 (test, 시드 3개 평균 ± 표준편차)\n\n" + head + "\n" + "\n".join(rows) + "\n\n"

    # 선정 규칙: ① 기준선보다 높은 후보만 ② 최고 NDCG ③ 0.01 미만 차이면 단순한 쪽(A→B→C)
    if "baseline" in res:
        base = res["baseline"]["ndcg@5"]
        alive = [k for k in "ABC" if k in res and res[k]["test"]["ndcg@5"]["mean"] > base]
        if not alive:
            text += "**결론**: 모든 후보가 규칙 기준선보다 낮음 → 데이터·피처 보완 또는 다른 모델 검토\n"
        else:
            top = max(res[k]["test"]["ndcg@5"]["mean"] for k in alive)
            pick = next(k for k in alive if top - res[k]["test"]["ndcg@5"]["mean"] < C.SIMPLER_WINS_MARGIN)
            text += f"**선정**: {NAMES[pick]} (기준선 {base:.4f} 대비 통과 후보: {', '.join(alive)})\n"
            stds = [res[k]["test"]["ndcg@5"]["std"] for k in alive]
            if max(stds) > C.SIMPLER_WINS_MARGIN:
                text += "\n주의: 시드 간 표준편차가 0.01보다 커서, 후보 간 차이가 우연일 수 있어요.\n"
    (C.RESULT_DIR / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
