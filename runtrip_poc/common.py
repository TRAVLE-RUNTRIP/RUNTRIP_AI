"""데이터 로드, 시드 고정, 페르소나 키 등 공통 유틸."""
import json, math, random
import numpy as np


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def persona_key(persona):
    """'같은 페르소나' 정의: config.PERSONA_KEY_FIELDS 값이 모두 같으면 같은 페르소나.
    분할할 때 이 키 단위로 나눠서 train/test에 같은 페르소나가 섞이지 않게 해요."""
    import config as C
    parts = []
    for f in C.PERSONA_KEY_FIELDS:
        v = persona[f]
        parts.append("+".join(sorted(v)) if isinstance(v, list) else str(v))
    return "|".join(parts)


def haversine_km(lat1, lng1, lat2, lng2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def set_seed(seed):
    random.seed(seed)
    np.random.seed(seed)
    try:
        import torch
        torch.manual_seed(seed)
        torch.use_deterministic_algorithms(True, warn_only=True)
    except ImportError:
        pass
