# Orin Nano STT/TTS Node — Join & Deploy Runbook

> **Purpose:** Add a Jetson Orin Nano as a k3s worker node dedicated to STT/TTS
> inference for the voice layer, then deploy `stt-service` and `tts-service`.
>
> **Constraints honored:** no registry (`imagePullPolicy: Never`), images built on
> TX2, distributed as tarballs, Orin Nano is ARM64 (same as TX2 — no
> cross-architecture build needed), TimescaleDB stays on TX2, pi1 is protected
> from OOM, pi2 is never touched beyond the existing control plane.
>
> **Prerequisites:** Orin Nano (4 GB or 8 GB) on the LAN, reachable from pi2
> (k3s API at pi2:6443), SSH access from admin workstation, JetPack 5/6 installed.

---

## Phase 0 — Pre-flight on admin workstation

```bash
export KUBECONFIG=~/.kube/pi-cluster.yaml
kubectl get nodes
# Expect: pi1, pi2 (cordoned), pi3, ahytx2-desktop all Ready

# Node token from the control plane (pi2)
python3 ops-tools/runcmd.py pi2 pi2 'cat /var/lib/rancher/k3s/server/node-token'

# Verify Orin Nano is reachable from admin (substitute real alias/IP from .hosts.env)
python3 ops-tools/runcmd.py orin orin 'uptime; free -m | head -2'
# Expect: load < 2, 4 GB or 8 GB RAM showing
```

---

## Phase 1 — Join Orin Nano to k3s

Run on the admin workstation. Replace `<NODE_TOKEN>` with the value from Phase 0.

```bash
# 1. Install k3s agent on Orin Nano (no extra flags — standard worker join)
python3 ops-tools/runcmd.py orin orin \
  'curl -sfL https://get.k3s.io | K3S_URL=https://pi2:6443 K3S_TOKEN=<NODE_TOKEN> sh -'

# 2. Wait for the node to appear, then label + taint it
kubectl wait --for=condition=Ready node/orin-nano --timeout=300s

kubectl label nodes orin-nano hardware=orin
kubectl taint nodes orin-nano hardware=orin:NoSchedule

# 3. Verify
kubectl get nodes orin-nano --show-labels
kubectl describe node orin-nano | grep -A5 Taints
```

**What this gives you:** a k3s worker that only runs pods with `nodeSelector: hardware=orin` and a matching toleration. Nothing else schedules there by default, protecting the Orin Nano from unrelated workloads.

> **Note:** If your Orin Nano hostname isn't `orin-nano`, substitute it everywhere and add the alias to `.hosts.env` (gitignored).

---

## Phase 2 — Build STT/TTS images on TX2

Per the §6 image cycle: build on TX2, tarball, distribute, import.

### 2a. Create the voice build context

```bash
mkdir -p manifests/voice/stt-service
mkdir -p manifests/voice/tts-service
```

### 2b. STT Dockerfile (`manifests/voice/stt-service/Dockerfile`)

```dockerfile
FROM python:3.11-slim

# faster-whisper runs Whisper with CTranslate2; CUDA wheels need libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 libcuda1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY stt_server.py .

EXPOSE 8000
CMD ["python", "stt_server.py"]
```

`manifests/voice/stt-service/requirements.lock`:
```
faster-whisper==1.1.1
uvicorn==0.30.6
fastapi==0.115.0
python-multipart==0.0.9
```

### 2c. TTS Dockerfile (`manifests/voice/tts-service/Dockerfile`)

```dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY tts_server.py .

EXPOSE 8001
CMD ["python", "tts_server.py"]
```

`manifests/voice/tts-service/requirements.lock`:
```
piper-tts==1.2.0
uvicorn==0.30.6
fastapi==0.115.0
python-multipart==0.0.9
```

### 2d. Build, tarball, distribute (run on admin workstation)

```bash
# Build STT image on TX2
python3 ops-tools/runcmd.py tx2 ahytx2 \
  'cd /home/ahytx2 && rm -rf stt-build && mkdir stt-build && \
   cp /tmp/stt-service/* stt-build/ && \
   docker build -t local/stt-service:v1 stt-build && \
   docker save local/stt-service:v1 | gzip > /mnt/tx2-ssd/image-tarballs/stt-service-v1.tar.gz'

# Build TTS image on TX2
python3 ops-tools/runcmd.py tx2 ahytx2 \
  'cd /home/ahytx2 && rm -rf tts-build && mkdir tts-build && \
   cp /tmp/tts-service/* tts-build/ && \
   docker build -t local/tts-service:v1 tts-build && \
   docker save local/tts-service:v1 | gzip > /mnt/tx2-ssd/image-tarballs/tts-service-v1.tar.gz'

# Regenerate checksums (never prune-all)
python3 ops-tools/runcmd.py tx2 ahytx2 \
  'cd /mnt/tx2-ssd/image-tarballs && sha256sum *.tar.gz > SHA256SUMS.all && sha256sum -c SHA256SUMS.all'

# Pull tarballs to admin, push to Orin Nano
python3 ops-tools/getfile.py tx2 ahytx2 \
  /home/ahytx2/stt-service-v1.tar.gz /tmp/stt-service-v1.tar.gz
python3 ops-tools/getfile.py tx2 ahytx2 \
  /home/ahytx2/tts-service-v1.tar.gz /tmp/tts-service-v1.tar.gz

python3 ops-tools/putfile.py orin orin /tmp/stt-service-v1.tar.gz /home/orin/stt-service-v1.tar.gz
python3 ops-tools/putfile.py orin orin /tmp/tts-service-v1.tar.gz /home/orin/tts-service-v1.tar.gz

# Import into Orin Nano containerd
python3 ops-tools/runcmd.py orin orin \
  'echo @@PW@@ | sudo -S /usr/local/bin/k3s ctr -n k8s.io images import /home/orin/stt-service-v1.tar.gz && \
   echo @@PW@@ | sudo -S /usr/local/bin/k3s ctr -n k8s.io images import /home/orin/tts-service-v1.tar.gz && \
   rm /home/orin/stt-service-v1.tar.gz /home/orin/tts-service-v1.tar.gz'

# Verify images landed
python3 ops-tools/runcmd.py orin orin \
  'echo @@PW@@ | sudo -S /usr/local/bin/k3s ctr -n k8s.io images ls | grep -E "stt-service|tts-service"'
```

### 2e. Regenerate `SHA256SUMS.all` on TX2 (already done above)

The tarball archive now includes `stt-service-v1.tar.gz` and `tts-service-v1.tar.gz` alongside the 6 live images.

---

## Phase 3 — Deploy manifests

Apply from admin workstation:

```bash
export KUBECONFIG=~/.kube/pi-cluster.yaml
kubectl apply -f manifests/voice/stt-service-deployment.yaml
kubectl apply -f manifests/voice/tts-service-deployment.yaml
kubectl apply -f manifests/voice/stt-service-svc.yaml
kubectl apply -f manifests/voice/tts-service-svc.yaml
```

Verify pods land on Orin Nano:

```bash
kubectl -n market-data get pods -o wide -l app=stt-service
kubectl -n market-data get pods -o wide -l app=tts-service
# Expect NODE = orin-nano for both

kubectl -n market-data wait --for=condition=Ready pod -l app=stt-service --timeout=120s
kubectl -n market-data wait --for=condition=Ready pod -l app=tts-service --timeout=120s
```

---

## Phase 4 — Wire the Telegram bot to STT/TTS (on pi1)

The `telegram-bot` Deployment (image `local/telegram-digest:v37`, pinned pi1) needs
voice-message handling added to `bot.py`:

1. On receiving a voice message, download the `.ogg` file via Telegram File API
2. POST the audio to `http://stt-service.market-data.svc.cluster.local:8000/transcribe`
3. Take the returned text and run it through the existing command resolver
4. POST the answer text to `http://tts-service.market-data.svc.cluster.local:8001/speak`
5. `sendVoice` the returned `.ogg` back to the chat

No new DB privileges needed — reads still go through `telegram_app` (SELECT + `watchlist`/`bot_users`).

> **Important:** Do not add a new k8s Service type `LoadBalancer` or `NodePort`. Use ClusterIP
> (`stt-service.market-data.svc.cluster.local`) — reachable only inside the cluster, consistent
> with your Tailscale-only perimeter.

---

## Phase 5 — Smoke test

```bash
# From admin workstation
kubectl -n market-data port-forward svc/stt-service 8000:8000 &
STT_PID=$!
kubectl -n market-data port-forward svc/tts-service 8001:8001 &
TTS_PID=$!

# STT test
curl -X POST http://localhost:8000/transcribe -F "audio=@/tmp/test.ogg"
# Expect: {"text": "what is tcs trading at"}

# TTS test
curl -X POST http://localhost:8001/speak -H "Content-Type: application/json" \
  -d '{"text": "TCS is trading at 3350, up 1.2 percent today"}' --output /tmp/answer.ogg
# Expect: valid OGG/Opus audio file

kill $STT_PID $TTS_PID
```

Then end-to-end: send a voice message on Telegram → bot transcribes → answers → sends voice reply.

---

## Rollback

```bash
kubectl -n market-data delete -f manifests/voice/stt-service-deployment.yaml
kubectl -n market-data delete -f manifests/voice/tts-service-deployment.yaml
kubectl -n market-data delete -f manifests/voice/stt-service-svc.yaml
kubectl -n market-data delete -f manifests/voice/tts-service-svc.yaml

# Remove taint/label if retiring the node entirely
kubectl taint nodes orin-nano hardware=orin:NoSchedule-
kubectl label nodes orin-nano hardware-
kubectl delete node orin-nano
```

---

## Docs to update

- `docs/system-architecture-visual.md` — add Orin Nano node + STT/TTS to deployment view and data flow
- `docs/node-roles.md` — document orin-nano as STT/TTS-only worker
- `docs/pending-tasks.md` — new project entry: "Add Orin Nano STT/TTS node" (size: 2–3 sessions)
- `docs/market-data-pipeline-operations-manual.md` — §6 image cycle now includes voice images
