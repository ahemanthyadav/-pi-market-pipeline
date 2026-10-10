# Headline entity/event extractor (v1). Tiny by design — no pandas, no ML:
# gazetteer regex + psycopg only (ADR 0010). Built natively on the TX2; the
# CronJob is TX2-pinned, so the image lives on TX2's containerd only.
#   docker build -t local/headline-ner:v3 .
#   k3s ctr -n k8s.io images import headline-ner-v1.tar.gz   # on TX2
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]"
COPY headline_ner.py ./
CMD ["python", "headline_ner.py"]
