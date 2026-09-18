FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home pulsar
COPY --chown=pulsar:pulsar backend/ /app/
USER pulsar
EXPOSE 8000
ENTRYPOINT ["sh", "/app/entrypoint.sh"]
