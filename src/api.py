"""
FastAPI service exposing sentiment analysis and review retrieval.

Endpoints:
  GET  /health             — liveness probe
  POST /api/sentiment      — sentiment analysis for a single review
  GET  /api/reviews        — filtered review retrieval (color/storage/rating)
  GET  /api/stats          — aggregated stats for the dashboard
  GET  /docs               — auto-generated Swagger UI

Run locally:
    uvicorn src.api:app --reload --port 8000
"""
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from .aspects import aspect_sentiments, aspect_summary
from .database import get_conn, query_reviews
from .keywords import top_keywords_overall
from .sentiment import analyze


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Amazon Review Analyzer API",
    description=(
        "Sentiment analysis and review retrieval for iPhone 12 reviews "
        "scraped from amazon.in."
    ),
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------
class SentimentRequest(BaseModel):
    review_text: str = Field(..., min_length=1, max_length=5000,
                             description="The review text to analyze.")
    model: str = Field("vader", pattern="^(vader|hf)$",
                       description="Which model to use: 'vader' (default) or 'hf' (DistilBERT-SST2).")


class SentimentResponse(BaseModel):
    sentiment: str
    compound_score: float
    positive: float
    negative: float
    neutral: float
    model: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health", tags=["meta"])
def health():
    """Alias for /health under /api/ prefix, used by the frontend status indicator."""
    return {"status": "ok"}

@app.get("/api/health")
def health_api():
    """Alias for /health under the /api prefix, used by the frontend status dot."""
    return {"status": "ok"}

@app.post("/api/sentiment", response_model=SentimentResponse, tags=["sentiment"])
def sentiment_endpoint(req: SentimentRequest):
    """
    Analyze sentiment of a single review.

    - **review_text**: the review content (1-5000 chars)
    - **model**: 'vader' (fast, rule-based, default) or 'hf' (DistilBERT-SST2,
      slower but more nuanced; binary only, no neutral predictions)

    Returns: sentiment label, compound score (-1 to +1), and component scores.
    """
    result = analyze(req.review_text, model=req.model)
    return result.to_dict()


@app.get("/api/reviews", tags=["reviews"])
def reviews_endpoint(
    color: Optional[str] = Query(None, description="Filter by color (case-insensitive). NULL in all current rows."),
    storage: Optional[str] = Query(None, description="Filter by storage variant. NULL in all current rows."),
    rating: Optional[int] = Query(None, ge=1, le=5, description="Filter by exact star rating (1-5)."),
    limit: int = Query(20, ge=1, le=100, description="Max rows to return."),
    offset: int = Query(0, ge=0, description="Pagination offset."),
):
    """
    Retrieve reviews matching the given filters.

    All filters are optional and combinable. `color` and `storage_variant`
    are NULL on every row in the current dataset (amazon.in does not
    expose per-review variant metadata — see README).

    Returns: `{total, limit, offset, reviews: [...]}`.
    """
    with get_conn() as conn:
        rows, total = query_reviews(
            conn, color=color, storage=storage, rating=rating,
            limit=limit, offset=offset,
        )
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "reviews": rows,
    }


@app.get("/api/stats", tags=["stats"])
def stats_endpoint():
    """
    Aggregated dashboard stats: counts, sentiment distribution,
    rating distribution, top keywords, aspect-based sentiment.

    Used by the Flask frontend dashboard.
    """
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]

        avg_rating_row = conn.execute("SELECT AVG(rating) FROM reviews").fetchone()
        avg_rating = round(avg_rating_row[0], 2) if avg_rating_row[0] else None

        sentiment_rows = conn.execute("""
            SELECT sentiment_label, COUNT(*) AS c
            FROM reviews WHERE sentiment_label IS NOT NULL
            GROUP BY sentiment_label
        """).fetchall()
        sentiment_distribution = {r["sentiment_label"]: r["c"] for r in sentiment_rows}

        rating_rows = conn.execute("""
            SELECT rating, COUNT(*) AS c FROM reviews GROUP BY rating ORDER BY rating
        """).fetchall()
        rating_distribution = {str(r["rating"]): r["c"] for r in rating_rows}

        all_texts = [
            r["review_text"]
            for r in conn.execute("SELECT review_text FROM reviews").fetchall()
        ]

    # Keywords (overall, since our dataset doesn't have negative class for now)
    keywords = top_keywords_overall(all_texts, top_k=15)

    # Aspect-based sentiment
    aspects = aspect_summary(aspect_sentiments(all_texts))

    return {
        "total_reviews": total,
        "average_rating": avg_rating,
        "sentiment_distribution": sentiment_distribution,
        "rating_distribution": rating_distribution,
        "top_keywords": [{"term": t, "score": s} for t, s in keywords],
        "aspects": aspects,
    }