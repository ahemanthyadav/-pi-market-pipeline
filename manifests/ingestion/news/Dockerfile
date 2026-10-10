# ARM64 news image. Same build/distribute pattern (native TX2 docker build,
# ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/news-fetcher:v1 .
#   docker save local/news-fetcher:v1 | gzip > news-fetcher-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir feedparser "psycopg[binary]"
COPY news-fetcher.py .
CMD ["python", "news-fetcher.py"]
