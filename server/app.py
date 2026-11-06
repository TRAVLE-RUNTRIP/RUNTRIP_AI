"""RUN+Trip AI 서버 (API 명세 B파트). 실행: uvicorn server.app:app --port 8000  (레포 루트에서)"""
import logging
import math
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator
from starlette.exceptions import HTTPException

from server.scoring import Scorer, UnknownPlace

log = logging.getLogger("runtrip.ai")
state = {}


@asynccontextmanager
async def lifespan(app):
    state["scorer"] = Scorer()          # 서버 시작 시 서빙 파일을 한 번만 읽음
    yield


app = FastAPI(title="RUN+Trip AI", lifespan=lifespan)


def error(status, code, message):
    return JSONResponse(status_code=status, content={"code": code, "message": message})


@app.exception_handler(RequestValidationError)
async def on_validation(request: Request, exc: RequestValidationError):
    first = exc.errors()[0]
    return error(400, "VALIDATION_ERROR", f"{'.'.join(map(str, first['loc'][1:]))}: {first['msg']}")


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


class RecommendRequest(BaseModel):
    preferences: list[Literal["NIGHT_VIEW", "ATTRACTION", "NATURE"]] = Field(min_length=1, max_length=3)
    isNight: bool
    candidates: list[Candidate]

    @field_validator("preferences")
    @classmethod
    def unique(cls, v):
        if len(set(v)) != len(v):
            raise ValueError("같은 취향이 중복됐어요")
        return v


class PlaceScore(BaseModel):
    placeId: str
    score: float


class RecommendResponse(BaseModel):
    scores: list[PlaceScore]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/recommend", response_model=RecommendResponse)
def recommend(req: RecommendRequest):
    """B1. 후보 장소 점수 (지금은 규칙 기준선, #7에서 MLP로 교체). 점수가 높을수록 추천"""
    ids = [c.placeId for c in req.candidates]
    try:
        s = state["scorer"].score(req.preferences, req.isNight, ids, [c.detourRatio for c in req.candidates])
    except UnknownPlace as e:
        return error(422, "UNKNOWN_PLACE", f"AI 서버에 없는 장소예요 (places.csv 버전 확인): {', '.join(e.ids[:5])}")
    return {"scores": [{"placeId": p, "score": float(v)} for p, v in zip(ids, s)]}
