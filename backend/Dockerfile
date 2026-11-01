FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
ENV EXPLORER_DATA_DIR=/data
VOLUME /data
EXPOSE 8000
# One uvicorn process; analysis workers are spawned child processes (EXPLORER_MAX_WORKERS).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
