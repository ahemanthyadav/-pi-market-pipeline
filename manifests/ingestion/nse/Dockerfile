# ARM64 NSE indices image. Same build/distribute pattern as the yfinance fetcher
# (native TX2 docker build, ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/nse-fetcher:v1 .
#   docker save local/nse-fetcher:v1 | gzip > nse-fetcher-v1.tar.gz
# Deps identical to yfinance-fetcher (see ../yfinance/requirements.lock).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir yfinance pandas "psycopg[binary]"
COPY nse-indices.py .
CMD ["python", "nse-indices.py"]
