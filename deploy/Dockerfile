FROM python:3.12.12-slim-bookworm

ARG VCS_REF=unverified
LABEL org.opencontainers.image.revision=$VCS_REF
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY deploy/requirements.lock /tmp/requirements.lock
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TIMEOUT=120
ARG PIP_RETRIES=5
RUN python -m pip install --no-cache-dir \
    --index-url "$PIP_INDEX_URL" --timeout "$PIP_TIMEOUT" --retries "$PIP_RETRIES" \
    -r /tmp/requirements.lock \
    && groupadd --gid 10001 vd10 \
    && useradd --uid 10001 --gid 10001 --no-create-home vd10 \
    && mkdir -p /var/lib/vd10/mqtt_history \
    && chown -R 10001:10001 /var/lib/vd10
COPY backend/ ./backend/
COPY data/ ./data/
COPY knowledge/ ./knowledge/
COPY schemas/ ./schemas/
COPY *.html *.js *.css ./
USER 10001:10001
EXPOSE 8877
CMD ["python", "-m", "uvicorn", "backend.server:app", "--host", "0.0.0.0", "--port", "8877", "--workers", "1", "--no-proxy-headers"]
