# AI 서버 이미지. 레포 루트에서 빌드 (compose.yaml이 context: . 로 빌드)
FROM python:3.13-slim
WORKDIR /app
COPY server/requirements.txt server/
RUN pip install --no-cache-dir -r server/requirements.txt
# 점수 계산이 poc/의 피처·규칙 기준선 코드를 그대로 씀
COPY poc/features.py poc/evaluate.py poc/
COPY server/ server/
# root가 아닌 사용자로 실행 (파일은 root 소유로 둬서 서버가 앱·서빙 파일을 고칠 수 없음)
RUN useradd --system --no-create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
