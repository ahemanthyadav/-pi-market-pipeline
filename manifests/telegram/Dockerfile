# ARM64 telegram image — one image, two entrypoints (ADR 0009 family):
#   CronJob telegram-digest → CMD below (digest.py)
#   Deployment telegram-bot  → args: ["python", "bot.py"] (two-way listener)
# Same build/distribute pattern (native TX2 docker build, tarball import —
# pinned node pi1 only, see cronjob.yaml/deployment.yaml):
#   docker build -t local/telegram-digest:v2 .
#   docker save local/telegram-digest:v2 | gzip > telegram-digest-v2.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]" requests
COPY digest.py bot.py ./
CMD ["python", "digest.py"]
