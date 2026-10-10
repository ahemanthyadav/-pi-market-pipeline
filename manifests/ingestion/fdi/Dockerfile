# ARM64 FDI-watch image (reporter only — see fdi-watch.py header for why
# monthly FDI is not auto-imported). Same build/distribute pattern:
#   docker build -t local/fdi-watch:v1 .
#   docker save local/fdi-watch:v1 | gzip > fdi-watch-v1.tar.gz
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir requests
COPY fdi-watch.py .
CMD ["python", "fdi-watch.py"]
