# ARM64 health-monitor image. Build natively on the TX2 (python:3.12-slim
# base is already cached there from the fetcher builds):
#   docker build -t local/pipeline-health:v1 .
# Distribute to Pi workers WITHOUT a registry:
#   docker save local/pipeline-health:v1 | gzip > pipeline-health-v1.tar.gz
#   k3s ctr -n k8s.io images import pipeline-health-v1.tar.gz  # on each Pi
FROM python:3.12-slim
WORKDIR /app
# requirements.lock (AR-5): exact set frozen from v4; v5 (2026-10-18) is the first build from it.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY pipeline-health.py .
CMD ["python", "pipeline-health.py"]
