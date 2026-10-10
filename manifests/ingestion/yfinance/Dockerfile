# ARM64 ingestion image. Built NATIVELY on the TX2 (aarch64 docker, no QEMU):
#   docker build -t local/yfinance-fetcher:v1 .
# Distributed to Pi workers WITHOUT a registry (none deployed yet):
#   docker save local/yfinance-fetcher:v1 | gzip > yfinance-fetcher-v1.tar.gz
#   # on each of pi1/pi2/pi3:
#   k3s ctr -n k8s.io images import yfinance-fetcher-v1.tar.gz
# Pods use imagePullPolicy: Never (see cronjob.yaml) so the kubelet never
# contacts a registry. Rebuild + re-import on all three Pis to update.
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir yfinance pandas "psycopg[binary]"
COPY yfinance-fetcher.py .
CMD ["python", "yfinance-fetcher.py"]
