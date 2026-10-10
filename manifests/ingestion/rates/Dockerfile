# ARM64 FRED rates image. Same build/distribute pattern (native TX2 docker build,
# ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/rates-fetcher:v1 .
#   docker save local/rates-fetcher:v1 | gzip > rates-fetcher-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir fredapi pandas "psycopg[binary]"
COPY rates-fetcher.py .
CMD ["python", "rates-fetcher.py"]
