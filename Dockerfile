# ---------- 阶段 1：构建前端静态产物 ----------
FROM node:22-alpine AS panel-builder
WORKDIR /build
COPY panel/package.json panel/package-lock.json ./
RUN npm ci
COPY panel ./
RUN npm run build

# ---------- 阶段 2：运行时（Python + FFmpeg + Node） ----------
FROM python:3.12-slim

# FFmpeg 负责录制；Node.js 供 streamget 为抖音/斗鱼等平台计算签名
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg nodejs \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV RECORDER_HOST=0.0.0.0 \
    RECORDER_PORT=8000

COPY pyproject.toml ./
RUN pip install --no-cache-dir uv \
    && uv venv /app/.venv \
    && VIRTUAL_ENV=/app/.venv uv pip install -r pyproject.toml

COPY app ./app
COPY scripts ./scripts
COPY main.py ./
COPY --from=panel-builder /build/out ./panel/out

ENV PATH="/app/.venv/bin:$PATH"
VOLUME ["/app/data"]
EXPOSE 8000

CMD ["python", "main.py"]
