"""RUN+Trip AI 서버 (API 명세 B파트). 실행: uvicorn server.app:app --port 8000  (레포 루트에서)"""
import logging
import math
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator, model_validator
from starlette.exceptions import HTTPException

from server.optimize import solve
from server.reasons import GeminiError, make_reasons
from server.safety_course import grade, load_index
from server.scoring import Scorer, UnknownPlace

log = logging.getLogger("runtrip.ai")
state = {}


@asynccontextmanager
async def lifespan(app):
    state["scorer"] = Scorer()          # 서버 시작 시 서빙 파일을 한 번만 읽음
    state["safety"] = load_index()      # 서울 도로·보안등 (약 3초)
    yield


app = FastAPI(title="RUN+Trip AI", lifespan=lifespan)


def error(status, code, message):
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@app.exception_handler(RequestValidationError)
async def on_validation(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    field = ".".join(map(str, first["loc"][1:]))          # 요청 전체 검사(model_validator) 오류는 필드가 없음
    msg = first["msg"].removeprefix("Value error, ")
    return error(400, "VALIDATION_ERROR", f"{field}: {msg}" if field else msg)


@app.exception_handler(HTTPException)
async def on_http(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        return error(404, "RESOURCE_NOT_FOUND", "없는 API 주소예요")
    if exc.status_code == 405:
        return error(405, "METHOD_NOT_ALLOWED", "지원하지 않는 메서드예요")
    return error(exc.status_code, "SERVER_ERROR", str(exc.detail))


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    log.exception("처리하지 못한 오류")
    return error(500, "SERVER_ERROR", "AI 서버 오류예요")


class Candidate(BaseModel):
    placeId: str
    detourRatio: float = Field(ge=0)

    @field_validator("detourRatio")
    @classmethod
    def finite(cls, v):
        if not math.isfinite(v):
            raise ValueError("유한한 값이어야 해요")
        return v


class PrefRequest(BaseModel):
    preferences: list[Literal["NIGHT_VIEW", "ATTRACTION", "NATURE"]] = Field(min_length=1, max_length=3)
    isNight: bool

    @field_validator("preferences")
    @classmethod
    def unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("같은 취향이 중복됐어요")
        return v


class RecommendRequest(PrefRequest):
    candidates: list[Candidate] = Field(max_length=2000)   # 장소는 1,480곳뿐이라 정상 요청은 넘지 않음 (API 명세 B1)


class PlaceScore(BaseModel):
    placeId: str
    score: float


class RecommendResponse(BaseModel):
    scores: list[PlaceScore]


class OptimizeRequest(BaseModel):
    targetKm: float = Field(gt=0, le=50)
    maxPlaces: int = Field(ge=1, le=10)
    timeLimitMs: int = Field(ge=1, le=5000)
    placeIds: list[str] = Field(min_length=1, max_length=50)   # BE는 점수 상위 40곳을 보냄 (명세 B2). 후보 수를 바꾸면(#9) 같이 조정
    scores: list[float]
    distanceMatrixM: list[list[int]]
    excludedCombos: list[list[str]] = []

    @model_validator(mode="after")
    def shapes(self):
        n = len(self.placeIds)
        if len(set(self.placeIds)) != n:
            raise ValueError("placeIds에 같은 장소가 중복됐어요")
        if len(self.scores) != n or not all(math.isfinite(s) for s in self.scores):
            raise ValueError("scores는 placeIds와 개수가 같은 유한한 값이어야 해요")
        if len(self.distanceMatrixM) != n + 2 or any(len(r) != n + 2 for r in self.distanceMatrixM):
            raise ValueError(f"distanceMatrixM은 {n + 2}×{n + 2}이어야 해요 (출발지 + 장소 {n}곳 + 도착지)")
        if any(v < 0 for r in self.distanceMatrixM for v in r):
            raise ValueError("distanceMatrixM에 음수가 있어요")
        return self


class OptimizeResponse(BaseModel):
    found: bool
    orderedPlaceIds: list[str]
    totalKm: float | None


class ReasonPlace(BaseModel):
    placeId: str
    name: str = Field(min_length=1)
    overview: str | None = None          # 개요가 없는 장소도 근거만으로 설명
    evidence: list[str] = Field(min_length=1, max_length=10)


class ReasonsRequest(PrefRequest):
    places: list[ReasonPlace] = Field(min_length=1, max_length=10)   # 코스 장소는 maxPlaces(최대 10) 이하

    @field_validator("places")
    @classmethod
    def unique_places(cls, v):
        if len({p.placeId for p in v}) != len(v):
            raise ValueError("같은 장소가 중복됐어요")
        return v


class Reason(BaseModel):
    placeId: str
    reason: str | None
    usedEvidence: list[str]


class ReasonsResponse(BaseModel):
    reasons: list[Reason]


class SafetyRequest(BaseModel):
    path: list[tuple[float, float]] = Field(min_length=2, max_length=20000)   # [lat, lng]. OSRM 16km 경로가 약 400점
    isNight: bool

    @field_validator("path")
    @classmethod
    def coords(cls, v):
        if not all(math.isfinite(a) and math.isfinite(b) and -90 <= a <= 90 and -180 <= b <= 180 for a, b in v):
            raise ValueError("[위도, 경도] 범위의 유한한 값이어야 해요")
        if len(set(v)) < 2:
            raise ValueError("서로 다른 점이 2개 이상이어야 해요")
        return v


class SafetySegment(BaseModel):
    fromIndex: int
    toIndex: int
    grade: str


class SafetyResponse(BaseModel):
    score: int | None
    level: str | None
    coverage: float
    estimated: float
    hasLowSegment: bool
    segments: list[SafetySegment]
    warnings: list[str]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    """B1. 후보 장소 점수 0~1 (MLP, 모델이 없으면 규칙 기준선). 점수가 높을수록 추천"""
    ids = [c.placeId for c in req.candidates]
    try:
        s = state["scorer"].score(req.preferences, req.isNight, ids, [c.detourRatio for c in req.candidates])
    except UnknownPlace as e:
        return error(422, "UNKNOWN_PLACE", f"AI 서버에 없는 장소예요 (places.csv 버전 확인): {', '.join(e.ids[:5])}")
    return {"scores": [{"placeId": p, "score": float(v)} for p, v in zip(ids, s, strict=True)]}


@app.post("/optimize", response_model=OptimizeResponse)
def optimize(req: OptimizeRequest):
    """B2. 목표 거리 ±10% 안에서 점수 합이 최대인 장소 조합·순서 (OR-Tools). 못 찾으면 found = false"""
    found, order, total_m = solve(req.targetKm, req.maxPlaces, req.timeLimitMs, req.placeIds, req.scores,
                                  req.distanceMatrixM, req.excludedCombos)
    return {"found": found, "orderedPlaceIds": order, "totalKm": round(total_m / 1000, 2) if found else None}


@app.post("/reasons", response_model=ReasonsResponse)
def reasons(req: ReasonsRequest):
    """B3. 장소별 추천 이유 (Gemini + 근거 검증). 검증 실패 장소는 reason = null → Spring이 개요로 대체"""
    try:
        return {"reasons": make_reasons(req.preferences, req.isNight, req.places)}
    except GeminiError as e:
        log.warning("추천 이유 생성 실패: %s", e)
        return error(502, "REASON_FAILED", "추천 이유를 만들지 못했어요")


@app.post("/safety", response_model=SafetyResponse)
def safety(req: SafetyRequest):
    """B4. 경로 조명 환경 점수 (경로는 바꾸지 않음). 보안등 자료 밖은 '자료없음', 자료 밖이 절반 넘으면 level '자료부족'"""
    return grade(state["safety"], req.path, req.isNight)
