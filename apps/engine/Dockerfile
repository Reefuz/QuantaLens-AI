FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN useradd --create-home --uid 10001 app
WORKDIR /app

COPY apps/engine/requirements.txt apps/engine/constraints.txt ./
RUN pip install -r requirements.txt -c constraints.txt

COPY apps/engine/ ./
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
