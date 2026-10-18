# Single toolkit image for the whole stock-screener layer (v1).
# One image = ONE no-registry cycle (build → tarball → import on pi1/pi2/pi3)
# instead of six; each CronJob picks its script via `command`.
# Build natively on the TX2:
#   docker build -t local/screener:v1 .
# Distribute:
#   docker save local/screener:v1 | gzip > screener-v1.tar.gz
#   k3s ctr -n k8s.io images import screener-v1.tar.gz   # on each Pi
FROM python:3.12-slim
WORKDIR /app
# requirements.lock (AR-5): the exact set frozen from the running v9 image — build context must contain it.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY *.py ./
CMD ["python", "universe_refresh.py"]
