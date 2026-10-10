# ARM64 TA-compute image. Same build/distribute pattern (native TX2 docker build,
# ctr import on pi1/pi2/pi3, Never pull):
#   docker build -t local/ta-compute:v1 .
# pandas only (no yfinance needed — reads history from the DB).
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir pandas "psycopg[binary]"
COPY ta-compute.py .
CMD ["python", "ta-compute.py"]
