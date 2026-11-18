FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home appuser && mkdir /data && chown appuser:appuser /data
USER appuser
ENV LINKLANE_DATA_DIR=/data PYTHONUNBUFFERED=1
EXPOSE 8787
CMD ["python", "-m", "linklane", "--host", "0.0.0.0"]
