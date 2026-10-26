# ARM64 factor-returns image (G-20). Same build/distribute pattern as the other
# fetchers (native TX2 docker build, ctr import on pi1/pi2/pi3, Never pull):
#   cp ../../_common/mdjob.py .   # copied into the context at build time (AR-2)
#   docker build -t local/factors-fetcher:v1 .
#   docker save local/factors-fetcher:v1 | gzip > factors-fetcher-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
# requirements.lock (AR-5): installed from the lock from day one.
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY factors-fetcher.py mdjob.py ./
CMD ["python", "factors-fetcher.py"]
