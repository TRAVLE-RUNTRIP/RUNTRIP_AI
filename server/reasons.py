"""/reasons (API 명세 B3): Gemini로 장소별 추천 이유 한 문장을 만들고, 받은 근거만 썼는지 검증한다.
검증에 실패한 장소는 reason = null (Spring이 장소 개요로 대체). Gemini 호출 자체가 실패하면 GeminiError → 오류 응답.
키: 환경 변수 GEMINI_API_KEY (Compose는 레포 루트 .env에서 읽음)"""
import json
import os
import re
import urllib.error
import urllib.request

# 2026-11-24 비교 (장소 3곳): 3.5-flash-lite 1.4~1.8초 · 2.5-flash 2.1초(생각 끔, 켜면 5.6초) · 3.5-flash 2.7~3.0초, 문장 품질 비슷
# ponytail: thinkingLevel은 Gemini 3 계열 설정. GEMINI_MODEL을 2.x로 바꾸면 thinkingConfig도 thinkingBudget: 0으로
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
URL = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent"
TIMEOUT_S = 4                     # BE 제한 5초 안에 오류 응답까지 끝내도록
MAX_LEN = 80                      # 한 문장 안팎
PREF_KO = {"NIGHT_VIEW": "야경", "ATTRACTION": "관광 명소", "NATURE": "자연·공원"}
NIGHT_WORDS = ("야경", "조명", "불빛", "야간", "밤")     # night_spot 근거나 개요에 없으면 지어낸 것
NIGHT_EVIDENCE = "night_spot"

SCHEMA = {"type": "OBJECT", "properties": {"reasons": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
    "placeId": {"type": "STRING"}, "reason": {"type": "STRING"}, "usedEvidence": {"type": "ARRAY", "items": {"type": "STRING"}}},
    "required": ["placeId", "reason", "usedEvidence"]}}}, "required": ["reasons"]}


class GeminiError(Exception):
    pass


def prompt(preferences, is_night, places):
    lines = [
        "러닝 코스 앱에서, 코스에 들어간 장소마다 왜 이 장소를 넣었는지 한 문장으로 설명해 주세요.",
        f"사용자 취향: {', '.join(PREF_KO[p] for p in preferences)} / 시간: {'밤' if is_night else '낮'}",
        "규칙:",
        f"- 장소마다 {MAX_LEN}자 이내 한 문장, '~해요' 말투",
        "- 그 장소의 '개요'와 '근거'에 있는 사실만 씁니다. 숫자·연도·시설·이름은 개요에 있는 것만 씁니다",
        f"- 근거에 {NIGHT_EVIDENCE}가 없으면 야경·조명·밤 풍경을 말하지 않습니다 (개요에 있으면 가능)",
        "- usedEvidence에는 문장에 실제로 쓴 근거를 받은 그대로 적습니다 (1개 이상)",
        "- 아래 장소만, 받은 placeId 그대로 답합니다",
        "",
    ]
    for p in places:
        lines.append(json.dumps({"placeId": p.placeId, "name": p.name, "overview": p.overview or "", "evidence": p.evidence}, ensure_ascii=False))
    return "\n".join(lines)


def call_gemini(text):
    """Gemini generateContent (JSON 응답 강제) → 응답 JSON 문자열"""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise GeminiError("GEMINI_API_KEY가 설정되지 않았어요")
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.3, "responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "thinkingConfig": {"thinkingLevel": "minimal"}}}   # 생각을 켜면 5초 제한을 넘김
    req = urllib.request.Request(URL.format(MODEL), json.dumps(body).encode(), {"Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return json.load(r)["candidates"][0]["content"]["parts"][0]["text"]
    except urllib.error.HTTPError as e:
        raise GeminiError(f"Gemini HTTP {e.code}") from e
    except (OSError, KeyError, IndexError, ValueError) as e:      # 시간 초과·연결 실패·응답 모양이 다름
        raise GeminiError(f"Gemini 호출 실패: {type(e).__name__}") from e


def check(reason, used, place):
    """받은 근거만 썼는지. 통과하면 None, 아니면 실패 이유"""
    if not isinstance(reason, str) or not reason.strip() or len(reason) > MAX_LEN:
        return "빈 문장이거나 너무 김"
    if not used or not set(used) <= set(place.evidence):
        return "받지 않은 근거"
    source = f"{place.name} {place.overview or ''}"
    if any(n not in source for n in re.findall(r"\d+", reason)):
        return "개요에 없는 숫자"
    if any(w in reason for w in NIGHT_WORDS) and NIGHT_EVIDENCE not in place.evidence and not any(w in source for w in NIGHT_WORDS):
        return "근거 없는 야경·조명"
    return None


def make_reasons(preferences, is_night, places):
    """요청 순서대로 [{placeId, reason, usedEvidence}]. 요청에 없는 장소는 버리고, 답이 없거나 검증 실패면 reason = null"""
    try:
        out = json.loads(call_gemini(prompt(preferences, is_night, places)))["reasons"]
    except (ValueError, KeyError, TypeError) as e:
        raise GeminiError(f"Gemini 응답 형식 오류: {type(e).__name__}") from e
    got = {r.get("placeId"): r for r in out if isinstance(r, dict)}
    res = []
    for p in places:
        r = got.get(p.placeId, {})
        used = r.get("usedEvidence") if isinstance(r.get("usedEvidence"), list) else []
        ok = p.placeId in got and check(r.get("reason"), used, p) is None
        res.append({"placeId": p.placeId, "reason": r["reason"].strip() if ok else None, "usedEvidence": used if ok else []})
    return res
