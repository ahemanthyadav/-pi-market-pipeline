# ARM64 Treasury-yields image. Same build/distribute pattern (native TX2 docker
# build, ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/yields-fetcher:v1 .
#   docker save local/yields-fetcher:v1 | gzip > yields-fetcher-v1.tar.gz
# Deps identical to yfinance-fetcher (see ../yfinance/requirements.lock).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir yfinance pandas "psycopg[binary]"
COPY yields-fetcher.py .
CMD ["python", "yields-fetcher.py"]
