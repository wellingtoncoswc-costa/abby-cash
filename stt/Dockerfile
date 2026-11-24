FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.115.6 "uvicorn[standard]==0.34.0" python-multipart==0.0.20 faster-whisper==1.1.1
COPY main.py .
ENV HF_HOME=/models STT_MODEL=small
RUN mkdir /models && chown nobody /models
USER nobody
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
