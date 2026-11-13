"""공통 학습 루프. valid NDCG@5 기준으로 가장 좋은 epoch를 고른다.

실행 예: python poc/train.py --loss C --lr 1e-3 --dropout 0.1 --seed 0
         (튜닝이 끝난 설정으로만) python poc/train.py --loss C --lr 1e-3 --dropout 0.1 --seed 0 --test
결과: poc/runs/{loss}_lr{lr}_do{dropout}_s{seed}[_pb{bonus}].json, 같은 이름 .pt (최적 epoch 가중치, /recommend 서빙용)
최종 설정(#6): --loss A --lr 1e-3 --dropout 0.1 --pref-bonus 2.0 (서빙 점수 = 모델 점수 + 2 × 취향 일치)
"""
import argparse, json, random, time
from pathlib import Path

import numpy as np
import torch

import evaluate as ev
from losses import LOSSES, make_optimizer
from model import Scorer

RUNS = Path(__file__).parent / "runs"


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def predict(model, X):
    model.eval()
    with torch.no_grad():
        return model(torch.from_numpy(X)).numpy()


def inference_ms(model, X, n=200):
    """후보 최대 20개짜리 쿼리 1건을 CPU에서 점수 매기는 평균 시간"""
    model.eval()
    x = torch.from_numpy(X[:1])
    with torch.no_grad():
        start = time.perf_counter()
        for _ in range(n):
            model(x)
    return (time.perf_counter() - start) / n * 1000


def main(args):
    set_seed(args.seed)
    Xtr, rtr, mtr = ev.load("train")
    Xva, rva, mva = ev.load("valid")
    train = [torch.from_numpy(a) for a in (Xtr, rtr, mtr)]

    model = Scorer(Xtr.shape[-1], args.dropout)
    opt = make_optimizer(args.loss, model.parameters(), args.lr)
    loss_fn = LOSSES[args.loss]

    best, best_state, wait = -1.0, None, 0
    for epoch in range(1, args.epochs + 1):
        model.train()
        for i in torch.randperm(len(Xtr)).split(args.batch):
            x, rel, mask = (t[i] for t in train)
            loss = loss_fn(model(x), rel, mask)
            opt.zero_grad()
            loss.backward()
            opt.step()
        ndcg = ev.ndcg_at_k(predict(model, Xva), rva, mva)
        if ndcg > best:
            best, best_state, wait = ndcg, {k: v.clone() for k, v in model.state_dict().items()}, 0
            best_epoch = epoch
        else:
            wait += 1
            if wait >= args.patience:
                break

    model.load_state_dict(best_state)
    # 취향 일치 장소 가산점: 학습·epoch 선택에는 쓰지 않고 최종 점수에만 더한다 (서빙도 같은 식)
    score = lambda X: predict(model, X) + args.pref_bonus * ev.pref_match(X)
    result = {"args": vars(args), "best_epoch": best_epoch,
              "valid": ev.evaluate(score(Xva), Xva, rva, mva)}
    if args.test:
        Xte, rte, mte = ev.load("test")
        result["test"] = ev.evaluate(score(Xte), Xte, rte, mte)
        result["inference_ms"] = inference_ms(model, Xte)

    RUNS.mkdir(exist_ok=True)
    pb = f"_pb{args.pref_bonus}" if args.pref_bonus else ""
    out = RUNS / f"{args.loss}_lr{args.lr}_do{args.dropout}_s{args.seed}{pb}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    torch.save({"state_dict": best_state, "d": Xtr.shape[-1], "dropout": args.dropout}, out.with_suffix(".pt"))
    print(json.dumps({k: v for k, v in result.items() if k != "args"}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--loss", choices=LOSSES, required=True)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--patience", type=int, default=10)
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--pref-bonus", type=float, default=0.0, help="취향 일치 장소 가산점 (valid로 정함)")
    main(ap.parse_args())
