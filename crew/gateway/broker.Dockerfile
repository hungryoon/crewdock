FROM python:3.13-slim
WORKDIR /app
# Static docker CLI only (no engine) — used to `docker exec` into instances.
ARG DOCKER_VER=27.3.1
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_VER}.tgz" \
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
