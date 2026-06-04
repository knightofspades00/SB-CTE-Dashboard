# syntax=docker/dockerfile:1
#
# Pathways to Positions — production image.
#
# Lightweight Python 3.12 slim base. Deliberately does NOT include the
# Playwright Chromium runtime — the daily "Hiring now" scrape runs out of band
# (GitHub Actions or a separate scheduled task) and commits its result into
# database/currently_hiring.json, which this container reads at boot.
#
# Build:  docker build -t pathways-to-positions .
# Run:    docker run -p 8000:8000 pathways-to-positions
# Health: curl http://localhost:8000/health

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    FLASK_ENV=production \
    DATABASE_PATH=database/cte_dashboard.db

WORKDIR /app

# Pull in just the requirements first so layer caching survives source-only edits.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Bring in the rest of the code.
COPY . .

# Initialise the SQLite database from the bundled xlsx + county data at build
# time so the first request after boot doesn't have to wait for the import.
RUN python database/bootstrap.py

# Render injects $PORT; gunicorn picks it up via the shell-expanded command.
EXPOSE 8000
CMD ["sh", "-c", "gunicorn --workers 2 --bind 0.0.0.0:${PORT} --access-logfile - --error-logfile - 'app:create_app()'"]
