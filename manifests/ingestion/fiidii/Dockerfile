# ARM64 FII/DII image. Same build/distribute pattern (native TX2 docker build,
# ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/fiidii-fetcher:v1 .
#   docker save local/fiidii-fetcher:v1 | gzip > fiidii-fetcher-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests "psycopg[binary]"
COPY fiidii-fetcher.py .
CMD ["python", "fiidii-fetcher.py"]
