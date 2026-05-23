"""
Sentiment analysis: VADER (primary) and HuggingFace DistilBERT (secondary).

VADER is rule-based, fast, deterministic, and designed for product
reviews / social media. We use it as the primary model: scoring every
row in the database, and as the default for the /api/sentiment endpoint.

DistilBERT-SST2 is a transformer fine-tuned for binary sentiment. It's
slower and bigger (~250MB), but understands context better. We expose
it as an opt-in via the API's `model=hf` parameter.

Why both: demonstrates awareness of lexicon-vs-transformer tradeoffs.
The README compares their accuracy against manually labeled reviews.
"""
from dataclasses import dataclass, asdict
from functools import lru_cache
from typing import Literal

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from .config import HF_SENTIMENT_MODEL


@dataclass
class SentimentResult:
    """Unified output structure for both VADER and HuggingFace."""
    sentiment: Literal["positive", "negative", "neutral"]
    compound_score: float
    positive: float
    negative: float
    neutral: float
    model: str

    def to_dict(self):
        return asdict(self)


# ---------------------------------------------------------------------------
# VADER (primary)
# ---------------------------------------------------------------------------
_vader = SentimentIntensityAnalyzer()


def vader_sentiment(text: str) -> SentimentResult:
    """
    Score `text` with VADER.

    Returns a SentimentResult with:
      - sentiment: "positive" / "negative" / "neutral" (thresholded)
      - compound_score: -1 to +1 normalized
      - positive / negative / neutral: proportion of each (sum to 1.0)
    """
    scores = _vader.polarity_scores(text or "")
    compound = scores["compound"]

    # Standard VADER thresholds for 3-class labels
    if compound >= 0.05:
        label = "positive"
    elif compound <= -0.05:
        label = "negative"
    else:
        label = "neutral"

    return SentimentResult(
        sentiment=label,
        compound_score=compound,
        positive=scores["pos"],
        negative=scores["neg"],
        neutral=scores["neu"],
        model="vader",
    )


# ---------------------------------------------------------------------------
# HuggingFace DistilBERT (secondary)
# ---------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _hf_pipeline():
    """
    Lazy-load the HuggingFace pipeline. Cached so we only load once per
    process. First call takes ~5-10 seconds (model download + load);
    subsequent calls are ~50-100ms each on CPU.
    """
    from transformers import pipeline
    return pipeline("sentiment-analysis", model=HF_SENTIMENT_MODEL)


def hf_sentiment(text: str) -> SentimentResult:
    """
    Score `text` with DistilBERT-SST2.

    The model is binary (POSITIVE / NEGATIVE only). We coerce its
    output into our 3-class schema (no neutral predictions from this
    model, but the API contract is uniform).
    """
    if not text or not text.strip():
        return SentimentResult("neutral", 0.0, 0.0, 0.0, 1.0, "distilbert-sst2")

    # Truncate to model's max length (~512 tokens). Longer texts get cut.
    out = _hf_pipeline()(text[:512])[0]
    label = out["label"].lower()  # "positive" or "negative"
    score = float(out["score"])    # confidence in the predicted label

    return SentimentResult(
        sentiment="positive" if label == "positive" else "negative",
        compound_score=score if label == "positive" else -score,
        positive=score if label == "positive" else 1 - score,
        negative=score if label == "negative" else 1 - score,
        neutral=0.0,
        model="distilbert-sst2",
    )


# ---------------------------------------------------------------------------
# Unified interface
# ---------------------------------------------------------------------------
def analyze(text: str, model: str = "vader") -> SentimentResult:
    """Dispatch to the requested model. Default: vader."""
    if model == "hf":
        return hf_sentiment(text)
    return vader_sentiment(text)


# ---------------------------------------------------------------------------
# Batch scoring: populate the database
# ---------------------------------------------------------------------------
def score_all_reviews(force: bool = False) -> int:
    """
    Score every row in the reviews table with VADER and write back to
    sentiment_label and sentiment_score columns.

    If force=False (default), only scores rows where sentiment_label is
    currently NULL. If force=True, re-scores everything.

    Returns the number of rows scored.
    """
    from .database import get_conn

    with get_conn() as conn:
        if force:
            rows = conn.execute(
                "SELECT id, review_text FROM reviews"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, review_text FROM reviews WHERE sentiment_label IS NULL"
            ).fetchall()

        scored = 0
        for row in rows:
            result = vader_sentiment(row["review_text"])
            conn.execute(
                "UPDATE reviews SET sentiment_label = ?, sentiment_score = ? WHERE id = ?",
                (result.sentiment, result.compound_score, row["id"]),
            )
            scored += 1

    return scored


if __name__ == "__main__":
    # Make this runnable as: python -m src.sentiment
    # Scores all unscored reviews with VADER.
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    log = logging.getLogger(__name__)

    log.info("scoring all unscored reviews with VADER")
    n = score_all_reviews()
    log.info("scored %d rows", n)