# RBI daily rates fetcher (findings Tier 2 #8; ops manual §12.1). Parses the
# RBI mobile-site "Current Rates" widget — official source, no key, no session.
# Build on TX2; import on pi1/pi2/pi3 (job is unpinned).
#   docker build -t local/rbi-fetcher:v1 .
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]" requests lxml
COPY rbi.py ./
CMD ["python", "rbi.py"]
