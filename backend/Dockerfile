FROM python:3.11-slim

WORKDIR /app

# gcc for any source-built wheels; curl so compose can healthcheck the API.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Normalise line endings — the repo is developed on Windows and a CRLF
# shebang makes the entrypoint fail with "no such file or directory".
RUN sed -i 's/\r$//' docker-entrypoint.sh && chmod +x docker-entrypoint.sh

EXPOSE 8000

# The entrypoint runs `alembic upgrade head` before handing off to this CMD.
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
