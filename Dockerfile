FROM python:3.12-slim

WORKDIR /app

ARG DENO_VERSION=2.7.11

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    curl \
    unzip \
    && architecture="$(dpkg --print-architecture)" \
    && case "$architecture" in \
         amd64) deno_target="x86_64-unknown-linux-gnu" ;; \
         arm64) deno_target="aarch64-unknown-linux-gnu" ;; \
         *) echo "Unsupported Deno architecture: $architecture" >&2; exit 1 ;; \
       esac \
    && curl -fsSL \
      "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-${deno_target}.zip" \
      -o /tmp/deno.zip \
    && unzip -q /tmp/deno.zip -d /usr/local/bin \
    && chmod 0755 /usr/local/bin/deno \
    && deno --version \
    && rm -f /tmp/deno.zip \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
RUN pip install --no-cache-dir "torch==2.11.0" \
    --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir ".[web]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
