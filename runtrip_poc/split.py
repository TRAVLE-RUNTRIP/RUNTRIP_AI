"""페르소나 기준 train/valid/test 분할.
사용: python split.py   (data/queries.jsonl → data/split/{train,valid,test}.jsonl)"""
import random
from collections import defaultdict
import config as C
from common import read_jsonl, write_jsonl, persona_key


def main():
    queries = read_jsonl(C.DATA_DIR / "queries.jsonl")
    groups = defaultdict(list)
    for q in queries:
        groups[persona_key(q["persona"])].append(q)

    keys = sorted(groups)
    random.Random(C.SPLIT_SEED).shuffle(keys)
    n = len(keys)
    n_tr, n_va = round(n * C.SPLIT_RATIO[0]), round(n * C.SPLIT_RATIO[1])
    parts = {"train": keys[:n_tr], "valid": keys[n_tr:n_tr + n_va], "test": keys[n_tr + n_va:]}

    for name, ks in parts.items():
        rows = [q for k in ks for q in groups[k]]
        write_jsonl(C.DATA_DIR / "split" / f"{name}.jsonl", rows)
        print(f"{name:5s}: 페르소나 {len(ks):4d}개, 쿼리 {len(rows):5d}건")

    # 누수 검사: 같은 페르소나가 두 분할에 동시에 있으면 안 됨
    tr, va, te = (set(v) for v in parts.values())
    assert not (tr & va or tr & te or va & te), "페르소나가 분할 사이에 겹쳐요"
    if n < 30:
        print("경고: 페르소나 종류가 적어 분할 비율이 크게 흔들릴 수 있어요. 취향·거리·시간대 조합을 늘려 주세요.")


if __name__ == "__main__":
    main()
