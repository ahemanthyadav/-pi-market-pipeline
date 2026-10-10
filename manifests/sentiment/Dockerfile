# ARM64 FinBERT sentiment image. Built NATIVELY on the TX2 (aarch64 docker).
# Deliberately CPU inference: JetPack 4.6.1's CUDA-10.2/Python-3.6 era cannot
# run modern torch/transformers, but a python:3.11 container with PyTorch CPU
# aarch64 wheels scores a daily batch in minutes on the TX2's ARM cores.
# FinBERT (~440MB) is baked in at build time for deterministic offline runs.
#
#   docker build -t local/sentiment-fetcher:v1 .
#   docker save local/sentiment-fetcher:v1 | gzip > sentiment-fetcher-v1.tar.gz
#   # TX2 only (nodeSelector keeps it there):
#   k3s ctr -n k8s.io images import sentiment-fetcher-v1.tar.gz
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir "psycopg[binary]" && \
    pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch && \
    pip install --no-cache-dir transformers tokenizers safetensors huggingface-hub
RUN python -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; \
    AutoTokenizer.from_pretrained('ProsusAI/finbert'); \
    AutoModelForSequenceClassification.from_pretrained('ProsusAI/finbert')"
COPY sentiment-score.py .
CMD ["python", "sentiment-score.py"]
