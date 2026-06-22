FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY crew ./crew
RUN pip install --no-cache-dir "aiohttp>=3.10" "pyyaml>=6.0" "filelock>=3.13" \
    && pip install --no-cache-dir -e .
ENV CREW_ROOT=/crew CREW_ROUTER_PORT=9400
ENTRYPOINT ["crew-gateway-router"]
