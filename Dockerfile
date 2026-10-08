FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user; /app/data holds the SQLite database (mounted as a volume).
RUN useradd --create-home --uid 1000 helpdesk \
    && mkdir -p /app/data \
    && chown helpdesk:helpdesk /app/data
USER helpdesk

ENV DATABASE_URL=sqlite:////app/data/helpdesk.db

EXPOSE 8000 8501

# Applies migrations, loads demo data if the database is empty and starts the API.
CMD ["sh", "-c", "python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
