# ARM64 research-watcher image (ADR 0031). House no-registry cycle (§6):
#   docker build -t local/research-fetcher:v1 .
#   docker save local/research-fetcher:v1 | gzip > research-fetcher-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY research-fetcher.py mdjob.py ./
CMD ["python", "research-fetcher.py"]
