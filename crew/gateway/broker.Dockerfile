FROM python:3.13-slim
WORKDIR /app
# Static docker CLI only (no engine) — used to `docker exec` into instances.
# Arch follows the build platform (docker sets TARGETARCH: amd64/arm64) so the
# image builds correctly on x86_64 and Apple-Silicon hosts alike.
ARG DOCKER_VER=27.3.1
ARG TARGETARCH
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && DARCH="$(case "${TARGETARCH:-amd64}" in arm64) echo aarch64;; *) echo x86_64;; esac)" \
    && curl -fsSL "https://download.docker.com/linux/static/stable/${DARCH}/docker-${DOCKER_VER}.tgz" \
       | tar -xz -C /tmp \
    && mv /tmp/docker/docker /usr/local/bin/docker \
    && rm -rf /tmp/docker \
    && apt-get purge -y curl && apt-get autoremove -y && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY crew ./crew
RUN pip install --no-cache-dir "aiohttp>=3.10" "pyyaml>=6.0" "filelock>=3.13" \
    && pip install --no-cache-dir -e .
ENV CREW_BROKER_SOCK=/run/crew-broker/broker.sock
ENTRYPOINT ["crew-gateway-broker"]
