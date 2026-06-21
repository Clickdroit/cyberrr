FROM python:3.12-slim

# System deps
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    libssl-dev \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir "pip<24.1" && pip install --no-cache-dir -r requirements.txt

# Install spaCy English model (lightweight for NER)
RUN python -m spacy download en_core_web_sm || true

# Install Sherlock separately (ensure latest)
RUN pip install --no-cache-dir sherlock-project || true

# Copy app
COPY app/ ./app/

# Create data directories
RUN mkdir -p /data/reports /data/db /app/config

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
