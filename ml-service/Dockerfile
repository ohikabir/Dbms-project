# --- SupplyNext ML service ------------------------------------------------
# python:3.12-slim keeps the image small while still having prebuilt wheels
# available for numpy/pandas/statsmodels (building those from source would
# turn a one-minute build into a fifteen-minute one).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies are copied and installed BEFORE the source. Docker caches each
# layer, so editing a .py file no longer re-runs the whole pip install.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

# Run as a non-root user: if the app is ever compromised, the attacker lands
# as an unprivileged account rather than as root inside the container.
RUN useradd --create-home --uid 1000 mlservice && chown -R mlservice:mlservice /app
USER mlservice

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
