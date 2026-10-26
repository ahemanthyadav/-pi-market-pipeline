# ARM64 NSE indices image. Same build/distribute pattern as the yfinance fetcher
# (native TX2 docker build, ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/nse-fetcher:v7 .
#   docker save local/nse-fetcher:v7 | gzip > nse-fetcher-v7.tar.gz
FROM python:3.12-slim
WORKDIR /app
# requirements.lock (AR-5): installed from the lock since v5 (2026-10-26).
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY nse-indices.py .
CMD ["python", "nse-indices.py"]
