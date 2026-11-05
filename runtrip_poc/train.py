"""공통 학습 루프. 손실 함수만 후보별로 다르고 나머지는 모두 같아요.
사용: python train.py --cand A   (B, C도 동일)
흐름: [하이퍼파라미터 그리드 × 시드 3개]를 valid로만 비교 → 최적 설정 1개로 test를 딱 한 번 평가
출력: results/{cand}.json, checkpoints/{cand}.pt
"""
import argparse, itertools, json, time
import numpy as np
import torch
import config as C
from common import set_seed
from model import Scorer
from losses import LOSSES
from metrics import all_metrics, ndcg_at_k


def load(name):
    d = dict(np.load(C.FEAT_DIR / f"{name}.npz"))
    t = {k: torch.from_numpy(d[k]) for k in ("X", "rel", "mask")}
    return d, t


def make_optimizer(params, lr):
    opt_cls = getattr(torch.optim, C.OPTIMIZER)
    return opt_cls(params, lr=lr, weight_decay=C.WEIGHT_DECAY)


@torch.no_grad()
def predict(model, X):
    model.eval()
    return model(X).numpy()


def train_one(cand, hp, seed, tr, va_np, va_t):
    """시드 하나·설정 하나로 학습. valid NDCG@5가 PATIENCE 에폭 동안 안 오르면 조기 종료"""
    set_seed(seed)
    loss_fn = LOSSES[cand]
    model = Scorer(tr["X"].shape[-1], dropout=hp["dropout"])
    opt = make_optimizer(model.parameters(), hp["lr"])
    n = len(tr["X"])
    best, best_state, wait = -1.0, None, 0
    for epoch in range(C.MAX_EPOCHS):
        model.train()
        perm = torch.randperm(n)
        for i in range(0, n, C.BATCH_SIZE):
            b = perm[i:i + C.BATCH_SIZE]
            loss = loss_fn(model(tr["X"][b]), tr["rel"][b], tr["mask"][b])
            opt.zero_grad()
            loss.backward()          # 역전파: 손실의 기울기 계산
            opt.step()               # 경사하강: 기울기 반대 방향으로 가중치 업데이트
        score = ndcg_at_k(predict(model, va_t["X"]), va_np["rel"], va_np["mask"])
        if score > best:
            best, best_state, wait = score, {k: v.clone() for k, v in model.state_dict().items()}, 0
        else:
            wait += 1
            if wait >= C.PATIENCE:
                break
    model.load_state_dict(best_state)
    return model, best, epoch + 1


def infer_ms(model, X, runs=200):
    """후보 20개 쿼리 1건의 CPU 추론 시간 (중앙값, ms)"""
    model.eval()
    x = X[:1]
    times = []
    with torch.no_grad():
        for _ in range(runs):
            t0 = time.perf_counter()
            model(x)
            times.append((time.perf_counter() - t0) * 1000)
    return float(np.median(times))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cand", choices=list(LOSSES), required=True)
    args = ap.parse_args()
    torch.set_num_threads(1)  # 서빙 환경(CPU 1코어 가정)에 맞춰 추론 시간 측정

    _, tr = load("train")
    va_np, va_t = load("valid")

    # 1) 그리드 탐색: valid로만 비교 (test는 아직 안 봄)
    grid = [dict(zip(C.GRID, v)) for v in itertools.product(*C.GRID.values())]
    log = []
    for hp in grid:
        vals = [train_one(args.cand, hp, s, tr, va_np, va_t)[1] for s in C.SEEDS]
        log.append({**hp, "valid_ndcg_mean": float(np.mean(vals)), "valid_ndcg_std": float(np.std(vals))})
        print(f"[{args.cand}] {hp}  valid NDCG@5 = {np.mean(vals):.4f} ± {np.std(vals):.4f}")
    best_hp = max(log, key=lambda r: r["valid_ndcg_mean"])
    best_hp = {k: best_hp[k] for k in C.GRID}

    # 2) 최적 설정으로 test를 딱 한 번 평가 (시드 3개)
    te_np, te_t = load("test")
    per_seed, models = [], []
    for s in C.SEEDS:
        model, _, epochs = train_one(args.cand, best_hp, s, tr, va_np, va_t)
        m = all_metrics(predict(model, te_t["X"]), te_np)
        m["infer_ms"] = infer_ms(model, te_t["X"])
        m["epochs"] = epochs
        per_seed.append(m)
        models.append(model)

    summary = {k: {"mean": float(np.mean([r[k] for r in per_seed])),
                   "std": float(np.std([r[k] for r in per_seed]))}
               for k in ("ndcg@5", "hit@5", "taste_match", "infer_ms")}
    res = {"model": args.cand, "best_hp": best_hp, "test": summary,
           "per_seed": per_seed, "grid_log": log}
    C.RESULT_DIR.mkdir(parents=True, exist_ok=True)
    (C.RESULT_DIR / f"{args.cand}.json").write_text(json.dumps(res, ensure_ascii=False, indent=2))
    C.CKPT_DIR.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": models[0].state_dict(), "hp": best_hp,
                "d": tr["X"].shape[-1]}, C.CKPT_DIR / f"{args.cand}.pt")
    print(f"[{args.cand}] best {best_hp} → test NDCG@5 {summary['ndcg@5']['mean']:.4f} ± {summary['ndcg@5']['std']:.4f}")


if __name__ == "__main__":
    main()
