FROM python:3.12-slim

# Install system deps needed by Playwright Chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl gnupg2 ca-certificates fonts-liberation \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxrandr2 libgbm1 libpango-1.0-0 \
    libcairo2 libasound2 libxshmfence1 libx11-xcb1 \
    libxfixes3 libdbus-1-3 libatspi2.0-0 libx11-6 \
    libxcb1 libxext6 libwayland-client0 && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium with all deps
RUN playwright install --with-deps chromium

COPY . .

# Verify the app can import without errors
RUN python -c "from main import app; print('SlabIQ app OK')"

# Render sets PORT env var
CMD ["sh", "-c", "echo 'Starting SlabIQ on port ${PORT:-10000}...' && python -c 'from main import app; print(\"Import OK\")' && uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --log-level info"]
