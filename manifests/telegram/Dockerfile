# ARM64 telegram image — one image, three entrypoints (ADR 0009 family):
#   CronJob telegram-digest → CMD below (digest.py)
#   CronJob telegram-alerts → args: ["python", "alerts.py"] (daily change alerts)
#   Deployment telegram-bot  → args: ["python", "bot.py"] (two-way listener)
# stocks.py is the shared stock/watchlist/screener view layer (no entrypoint).
# Same build/distribute pattern (native TX2 docker build, tarball import —
# pinned node pi1 only, see cronjob.yaml/deployment.yaml):
#   docker build -t local/telegram-digest:v4 .
#   docker save local/telegram-digest:v4 | gzip > telegram-digest-v4.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]" requests
COPY digest.py bot.py alerts.py stocks.py ./
CMD ["python", "digest.py"]
