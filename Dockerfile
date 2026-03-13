FROM python:3.12-slim

WORKDIR /app

# Install system deps for lxml and other native packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libxml2-dev libxslt1-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Verify the app can import without errors
RUN python -c "from main import app; print('SlabIQ app OK')"

# Render sets PORT env var
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --log-level info"]
