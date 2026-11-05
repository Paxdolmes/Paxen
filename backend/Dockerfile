FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# Model libraries otherwise start one thread per host CPU, far more than the container gets (see workers.train_isolated).
ENV OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY paxen ./paxen
# Non-root user that owns /app, so a local SQLite fallback or archive folder can be written if configured.
RUN useradd --create-home paxen && chown -R paxen /app
USER paxen
# API service (default). For the worker service, override the start command with:
#   python -m paxen.worker
ENV PAXEN_RUN_WORKERS=0
CMD ["sh", "-c", "uvicorn paxen.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]
