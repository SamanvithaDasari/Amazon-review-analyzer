FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    HF_HOME=/app/.cache/huggingface \
    TRANSFORMERS_CACHE=/app/.cache/huggingface

WORKDIR /app

# System deps for some Python wheels and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps — cached layer
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m spacy download en_core_web_sm
RUN python -c "import nltk; nltk.download('vader_lexicon'); nltk.download('stopwords'); nltk.download('punkt'); nltk.download('punkt_tab')"

# Pre-download DistilBERT so first request isn't a 30s wait

# App code
COPY src/ ./src/
COPY templates/ ./templates/
COPY static/ ./static/
COPY data/ ./data/
# Build the reviews.db from raw JSON sources and score with VADER
RUN python -m src.parse_raw && python -m src.sentiment
COPY docker-entrypoint.sh .

RUN chmod +x docker-entrypoint.sh

# Make sure caches are writable on HF Spaces (which runs as non-root)
RUN chmod -R 777 /app/.cache 2>/dev/null || true

EXPOSE 7860

CMD ["./docker-entrypoint.sh"]
