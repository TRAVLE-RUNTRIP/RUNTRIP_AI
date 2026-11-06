"""장소 조합·순서 결정 (API 명세 B2). 목표 거리 ±10% 안에서 점수 합이 최대인 조합과 순서.

노드: 0 = 출발지, 1..n = 장소(placeIds 순서), n+1 = 도착지 (순환이면 출발지와 같은 좌표)
두 솔버를 이어서 씀 (2026-11-06, 실제 OSRM 거리표 48건 비교 결과 server/bench_optimize.py):
1) Routing ('코스 생성 로직 개선안 (확정)' 8장): AddDisjunction(penalty = 점수 × 1000), 거리 상한 하드·하한 소프트.
   첫 해를 빨리 찾지만 최적은 보장하지 않음
2) CP-SAT: 같은 문제를 회로 제약(AddCircuit)으로 정확히 풀고, Routing 해를 힌트로 받아 남은 시간 동안 개선
→ 둘 중 점수 합이 큰 쪽. 결과가 ±10% 밖이거나 장소가 0곳이면 found = False
점수가 음수인 장소도 점수 합에 그대로 반영(넣을수록 손해) → 점수 합을 더 높이거나(더 좋은 장소로 가는 길목) 거리를 맞출 때만 들어감.
완전히 빼지 않는 이유: 빼면 거리를 못 맞춰 코스가 안 나오는 경우가 늘어서
excludedCombos: 조합의 활성 변수 합 ≤ 장소 수 − 1 (개선안 10장)
"""
import time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2
from ortools.sat.python import cp_model

SCORE_SCALE = 1000        # penalty는 정수만 받음 (개선안 8장)
TOLERANCE = 0.1           # 목표 거리 ±10%
SHORT_PENALTY = 100       # Routing: 하한보다 1m 짧을 때마다 손해. 점수 합(최대 수천)보다 커서 하한을 거의 지킴
TIE_BREAK_M = 100         # Routing: 거리 보조 비용 100m당 1. 점수보다 훨씬 작아 같은 점수면 덜 돌아가는 순서
ROUTING_SHARE = 0.3       # 제한 시간 중 Routing 몫 (500ms면 150ms), 나머지는 CP-SAT
MARGIN_MS = 30            # 결과 정리·응답에 남기는 시간


def bounds(target_km):
    return round(target_km * 1000 * (1 - TOLERANCE)), round(target_km * 1000 * (1 + TOLERANCE))


def weights(scores):
    """점수 × 1000 (음수 그대로). 음수 장소는 넣을수록 손해라, 점수 합을 더 높이거나 거리를 맞출 때만 들어감.
    0에 아주 가까운 음수(−0.0004 등)도 0이 되지 않게 최소 −1"""
    return [min(-1, round(s * SCORE_SCALE)) if s < 0 else round(s * SCORE_SCALE) for s in scores]


def penalties(scores):
    # Routing penalty는 음수를 받지 않아 0으로 (= 넣을 이유가 없는 장소). 마지막 비교는 weights로 함
    return [max(0, w) for w in weights(scores)]


def usable(combo, pos):
    """이번 후보에 없는 장소가 섞인 조합은 나올 수 없어 무시"""
    return bool(combo) and all(p in pos for p in combo)


def routing_solve(target_km, max_places, time_ms, place_ids, scores, dist, excluded):
    n = len(place_ids)
    lo, hi = bounds(target_km)
    manager = pywrapcp.RoutingIndexManager(n + 2, 1, [0], [n + 1])
    routing = pywrapcp.RoutingModel(manager)
    node = manager.IndexToNode

    dist_cb = routing.RegisterTransitCallback(lambda i, j: dist[node(i)][node(j)])
    routing.SetArcCostEvaluatorOfAllVehicles(
        routing.RegisterTransitCallback(lambda i, j: dist[node(i)][node(j)] // TIE_BREAK_M))
    routing.AddDimension(dist_cb, 0, hi, True, "dist")
    routing.GetDimensionOrDie("dist").SetCumulVarSoftLowerBound(routing.End(0), lo, SHORT_PENALTY)
    count_cb = routing.RegisterUnaryTransitCallback(lambda i: 1 if 1 <= node(i) <= n else 0)
    routing.AddDimension(count_cb, 0, max_places, True, "count")
    for k, w in enumerate(penalties(scores)):
        routing.AddDisjunction([manager.NodeToIndex(k + 1)], w)

    pos = {p: k + 1 for k, p in enumerate(place_ids)}
    for combo in excluded:
        if usable(combo, pos):
            active = [routing.ActiveVar(manager.NodeToIndex(pos[p])) for p in set(combo)]
            routing.solver().Add(routing.solver().Sum(active) <= len(active) - 1)

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(max(1, time_ms))
    sol = routing.SolveWithParameters(params)
    if sol is None:
        return None
    order, i = [], routing.Start(0)
    while not routing.IsEnd(i):
        i = sol.Value(routing.NextVar(i))
        if 1 <= node(i) <= n:
            order.append(place_ids[node(i) - 1])
    return order


def cpsat_solve(target_km, max_places, time_ms, place_ids, scores, dist, excluded, hint):
    n = len(place_ids)
    S, E = 0, n + 1
    lo, hi = bounds(target_km)
    md = cp_model.CpModel()
    arcs, used = [], []                       # used: 실제로 걷는 간선 (거리 합에 들어감)
    active = {}
    for i in range(1, n + 1):
        skip = md.NewBoolVar(f"skip{i}")      # 자기 자신으로 가는 간선 = 들르지 않음
        arcs.append((i, i, skip))
        active[i] = skip.Not()
    for i in range(n + 2):
        for j in range(n + 2):
            if i != j and j != S and i != E:  # 출발지로 들어가거나 도착지에서 나가는 간선은 없음
                x = md.NewBoolVar(f"x{i}_{j}")
                arcs.append((i, j, x))
                used.append((i, j, x))
    arcs.append((E, S, md.NewConstant(1)))   # 도착지 → 출발지를 이어 하나의 회로로 만듦 (거리에 넣지 않음)
    md.AddCircuit(arcs)
    total = sum(dist[i][j] * x for i, j, x in used)
    md.Add(total >= lo)
    md.Add(total <= hi)
    md.Add(sum(active.values()) >= 1)
    md.Add(sum(active.values()) <= max_places)
    pos = {p: k + 1 for k, p in enumerate(place_ids)}
    for combo in excluded:
        if usable(combo, pos):
            md.Add(sum(active[pos[p]] for p in set(combo)) <= len(set(combo)) - 1)
    w = weights(scores)
    md.Maximize(10000 * sum(w[i - 1] * active[i] for i in active) - total)   # 점수 합 우선(음수는 손해), 같으면 짧은 쪽
    if hint:
        seq = [S, *[pos[p] for p in hint], E]
        on = set(zip(seq, seq[1:]))
        for i, j, x in arcs[:-1]:
            md.AddHint(x, (i, j) in on if i != j else i not in seq)

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = max(0.01, time_ms / 1000)
    solver.parameters.num_workers = 8
    if solver.Solve(md) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None
    nxt = {i: j for i, j, x in used if solver.BooleanValue(x)}
    order, i = [], S
    while (i := nxt[i]) != E:
        order.append(place_ids[i - 1])
    return order


def solve(target_km, max_places, time_limit_ms, place_ids, scores, dist, excluded=()):
    """dist: (n+2)×(n+2) 정수 m. 반환: (found, 방문 순서 placeIds, 총 거리 m)"""
    t0 = time.perf_counter()
    first = routing_solve(target_km, max_places, round(time_limit_ms * ROUTING_SHARE), place_ids, scores, dist, excluded)
    lo, hi = bounds(target_km)
    idx = {p: k + 1 for k, p in enumerate(place_ids)}

    def length(order):
        seq = [0, *[idx[p] for p in order], len(place_ids) + 1]
        return sum(dist[a][b] for a, b in zip(seq, seq[1:]))

    def ok(order):
        return order is not None and 1 <= len(order) <= max_places and lo <= length(order) <= hi

    first = first if ok(first) else None
    left = time_limit_ms - (time.perf_counter() - t0) * 1000 - MARGIN_MS
    better = cpsat_solve(target_km, max_places, left, place_ids, scores, dist, excluded, first) if left > 10 else None
    w = weights(scores)
    gain = lambda o: sum(w[idx[p] - 1] for p in o)        # 실제 점수 합 (음수 장소가 끼면 그만큼 낮게 봄)
    candidates = [o for o in (better, first) if ok(o)]
    if not candidates:
        return False, [], 0
    best = max(candidates, key=gain)          # 같은 점수면 앞쪽(CP-SAT, 거리까지 고려)
    return True, best, length(best)
