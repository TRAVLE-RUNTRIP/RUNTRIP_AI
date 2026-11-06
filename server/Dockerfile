# AI 서버 이미지. 레포 루트에서 빌드 (compose.yaml이 context: . 로 빌드)
FROM python:3.13-slim
WORKDIR /app
COPY server/requirements.txt server/
RUN pip install --no-cache-dir -r server/requirements.txt
# 점수 계산이 poc/의 피처·규칙 기준선 코드를 그대로 씀
COPY poc/features.py poc/evaluate.py poc/
COPY server/ server/
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
