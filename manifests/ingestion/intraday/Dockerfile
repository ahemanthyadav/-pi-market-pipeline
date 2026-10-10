# ARM64 intraday-fetcher image. Build natively on the TX2 (base layers cached):
#   docker build -t local/intraday-fetcher:v1 .
# Distribute to Pi workers WITHOUT a registry:
#   docker save local/intraday-fetcher:v1 | gzip > intraday-fetcher-v1.tar.gz
#   k3s ctr -n k8s.io images import intraday-fetcher-v1.tar.gz  # on each Pi
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir yfinance pandas "psycopg[binary]"
COPY intraday-fetcher.py .
CMD ["python", "intraday-fetcher.py"]
