# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# NOTE: No apt-get install here. `python:3.12-slim` already has everything we
# need — cryptography ships manylinux wheels for 3.12, and the healthcheck
# uses Python's urllib instead of curl. Adding apt-get makes Windows/WSL2
# builds hang on debian mirror DNS/IPv6 issues.

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app ./app
COPY migrations ./migrations

# Database + WAL files live under /app/data (docker volume-mounted)
RUN mkdir -p /app/data
ENV DATABASE_URL=sqlite:////app/data/database.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3).read(); \
sys.exit(0)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
