"""
Parse raw scraped/manual data and load it into SQLite.

Takes data/raw_scraped.json (and optionally data/raw_manual.csv if it
exists), normalizes each row, deduplicates, and inserts into
data/reviews.db.

Run from project root:
    python -m src.parse_raw

Idempotent: re-running clears the reviews table and re-inserts from the
current state of the raw files. So you can drop a new raw_manual.csv
into data/ later, re-run this, and the DB reflects the new state.
"""
import csv
import json
import logging
import re
from pathlib import Path
from typing import Dict, List

from .config import RAW_SCRAPED_JSON, RAW_MANUAL_CSV
from pathlib import Path

# Playwright-scraped reviews (authenticated, large dataset)
PLAYWRIGHT_REVIEWS_JSON = Path(__file__).resolve().parent.parent / "data" / "playwright_reviews.json"
from .database import init_db, get_conn, insert_review

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def clean_text(s) -> str:
    """Collapse whitespace, strip. '' for None/falsy."""
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip()


def normalize_bool(v) -> bool:
    """Coerce various truthy reps to bool."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1", "y", "verified"}
    return bool(v)


def parse_review_date(raw) -> str | None:
    txt = clean_text(raw)
    return txt or None


def load_scraped() -> List[Dict]:
    if not Path(RAW_SCRAPED_JSON).exists():
        log.warning("scraped JSON not found at %s", RAW_SCRAPED_JSON)
        return []
    with open(RAW_SCRAPED_JSON, encoding="utf-8") as f:
        return json.load(f)

def load_playwright() -> List[Dict]:
    """Load Playwright-scraped reviews if present."""
    if not Path(PLAYWRIGHT_REVIEWS_JSON).exists():
        log.info("no playwright JSON at %s (skipping)", PLAYWRIGHT_REVIEWS_JSON)
        return []
    with open(PLAYWRIGHT_REVIEWS_JSON, encoding="utf-8") as f:
        rows = json.load(f)
    log.info("loaded %d rows from playwright JSON", len(rows))
    return rows
def load_manual() -> List[Dict]:
    """Load optional manual CSV; returns empty if absent."""
    if not Path(RAW_MANUAL_CSV).exists():
        log.info("no manual CSV at %s (skipping)", RAW_MANUAL_CSV)
        return []
    rows = []
    with open(RAW_MANUAL_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["source"] = "manual"
            rows.append(row)
    log.info("loaded %d rows from manual CSV", len(rows))
    return rows


def clean_review(raw: Dict) -> Dict | None:
    """Normalize one raw review. Returns None for invalid rows."""
    try:
        text = clean_text(raw.get("review_text"))
        if not text:
            return None
        rating = int(raw["rating"])
        if rating not in range(1, 6):
            return None
        return {
            "review_title": clean_text(raw.get("review_title")) or None,
            "review_text": text,
            "rating": rating,
            "storage_variant": None,
            "color": None,
            "verified_purchase": normalize_bool(raw.get("verified_purchase")),
            "review_date": parse_review_date(raw.get("review_date")),
            "source": raw.get("source", "unknown"),
            "variant_inferred": False,
        }
    except (KeyError, ValueError, TypeError) as e:
        log.warning("dropping invalid row: %s", e)
        return None


def dedupe(reviews: List[Dict]) -> List[Dict]:
    """Drop duplicates by (first 200 chars text, rating)."""
    seen, out = set(), []
    for r in reviews:
        key = (r["review_text"][:200].lower(), r["rating"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def main():
    log.info("initializing database schema")
    init_db()

    raw = load_scraped() + load_playwright() + load_manual()
    log.info("total raw rows loaded: %d", len(raw))

    cleaned = [c for c in (clean_review(r) for r in raw) if c is not None]
    log.info("after cleaning: %d valid rows", len(cleaned))

    cleaned = dedupe(cleaned)
    log.info("after dedup: %d unique rows", len(cleaned))

    with get_conn() as conn:
        conn.execute("DELETE FROM reviews")
        for r in cleaned:
            insert_review(conn, r)
        total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        rows = conn.execute(
            "SELECT source, COUNT(*) FROM reviews GROUP BY source"
        ).fetchall()
    log.info("database now contains %d rows", total)
    for source, count in rows:
        log.info("  source=%s: %d", source, count)


if __name__ == "__main__":
    main()