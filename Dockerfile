FROM python:3.11-slim

WORKDIR /app

# Dependencias de sistema:
# libgomp1: required by onnxruntime (chromadb) and llama.cpp
# curl, tar, gzip, procps: para download do llama-server e gestao de processos
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgomp1 \
    curl \
    tar \
    gzip \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Baixa e instala o binario pre-compilado oficial do llama.cpp (llama-server)
ARG LLAMA_CPP_VERSION=b11045
RUN curl -fsSL -o /tmp/llama.tar.gz "https://github.com/ggml-org/llama.cpp/releases/download/${LLAMA_CPP_VERSION}/llama-${LLAMA_CPP_VERSION}-bin-ubuntu-x64.tar.gz" \
    && tar -xzf /tmp/llama.tar.gz -C /tmp \
    && cp -a /tmp/llama-${LLAMA_CPP_VERSION}/llama-server /usr/local/bin/ \
    && cp -a /tmp/llama-${LLAMA_CPP_VERSION}/*.so* /usr/local/lib/ \
    && cp -a /tmp/llama-${LLAMA_CPP_VERSION}/*.so* /usr/local/bin/ \
    && ldconfig \
    && chmod +x /usr/local/bin/llama-server \
    && rm -rf /tmp/llama*

ENV GGML_BACKEND_PATH=/usr/local/lib \
    LD_LIBRARY_PATH=/usr/local/lib:/usr/local/bin:$LD_LIBRARY_PATH

COPY requirements.txt .
RUN pip install --no-cache-dir 'bcrypt<4.0.0' && pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root user for production security and /data directories
RUN useradd -m -u 1000 orion \
    && mkdir -p /data/db /data/chroma /data/models /data/logs \
    && chown -R orion:orion /app /data

USER orion

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
