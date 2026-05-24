---
title: Amazon Review Analyzer
emoji: 📊
colorFrom: indigo
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: NLP pipeline over 657 iPhone 12 reviews from amazon.in
---

# Amazon Review Analyzer

End-to-end NLP pipeline over **657 authenticated reviews** of the Apple iPhone 12 (ASIN B08L5TNJHG) scraped from amazon.in. Features VADER + DistilBERT sentiment classification, TF-IDF keyword extraction, and aspect-based sentiment scoring across 9 product features.

Built as an ML Engineer take-home submission.

## Stack

- **FastAPI** — REST API with auto-generated OpenAPI docs
- **Flask + Jinja2** — server-rendered dashboard
- **SQLite** — review storage
- **Playwright** — authenticated scraping (offline, data in repo)
- **VADER + DistilBERT-SST2** — sentiment models
- **TF-IDF (scikit-learn)** — keyword extraction
- **Docker** — single-container deployment

## Pages

- `/` — Dashboard with stats, distributions, keywords, aspects
- `/test-sentiment` — Live sentiment classifier (try VADER vs DistilBERT)
- `/browse-reviews` — Filterable review browser with multi-keyword search
- `/api-docs` — Human-readable API reference
- `/docs` — Auto-generated Swagger UI

## Source

GitHub: [SamanvithaDasari/amazon-review-analyzer](https://github.com/SamanvithaDasari/amazon-review-analyzer)
