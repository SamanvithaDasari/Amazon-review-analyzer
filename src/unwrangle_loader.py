"""
Fetch reviews from Unwrangle's Amazon Reviews API using cookie auth.

Reads UNWRANGLE_API_KEY and AMAZON_IN_COOKIE from environment / .env.
Outputs data/unwrangle_reviews.json in our internal schema.

Run:
    python -m src.unwrangle_loader
"""
import json
import logging
import os
import sys
from pathlib import Path
from typing import Dict

import requests
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

API_URL = "https://data.unwrangle.com/api/getter/"
ASIN = "B08L5TNJHG"
COUNTRY = "in"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "unwrangle_reviews.json"


def fetch_reviews(api_key: str, cookie: str, max_pages: int = 10) -> Dict:
    params = {
        "platform": "amazon_reviews",
        "asin": ASIN,
        "country_code": COUNTRY,
        "page": 1,
        "max_pages": max_pages,
        "cookie": cookie,
        "api_key": api_key,
    }
    log.info("calling Unwrangle: ASIN=%s country=%s max_pages=%d", ASIN, COUNTRY, max_pages)
    resp = requests.get(API_URL, params=params, timeout=180)
    log.info("HTTP %s", resp.status_code)
    if resp.status_code != 200:
        log.error("response: %s", resp.text[:500])
        resp.raise_for_status()
    data = resp.json()
    if not data.get("success"):
        log.error("API returned success=false: %s", json.dumps(data)[:500])
        raise RuntimeError(f"API call failed: {data.get('message', 'unknown')}")
    log.info(
        "fetched %d reviews across %s pages, credits used: %s, remaining: %s",
        len(data.get("reviews", [])),
        data.get("pages_fetched"),
        data.get("credits_used"),
        data.get("remaining_credits"),
    )
    return data


def normalize_review(raw: Dict) -> Dict:
    variant = raw.get("variant") or {}
    meta = raw.get("meta_data") or {}
    return {
        "review_title": raw.get("review_title"),
        "review_text": raw.get("review_text") or "",
        "rating": raw.get("rating"),
        "verified_purchase": bool(meta.get("verified_purchase", False)),
        "review_date": raw.get("date"),
        "color": variant.get("color"),
        "storage_variant": variant.get("size"),
        "source": "unwrangle_amazon_in",
    }


def main():
    api_key = os.environ.get("UNWRANGLE_API_KEY")
    cookie = os.environ.get("AMAZON_IN_COOKIE")
    if not api_key:
        log.error("UNWRANGLE_API_KEY missing")
        sys.exit(1)
    if not cookie:
        log.error("AMAZON_IN_COOKIE missing")
        sys.exit(1)
    log.info("credentials present (api_key=%d chars, cookie=%d chars)",
             len(api_key), len(cookie))

    data = fetch_reviews(api_key, cookie, max_pages=10)
    raw_reviews = data.get("reviews", [])
    normalized = [normalize_review(r) for r in raw_reviews]

    coverage = {
        "color_populated": sum(1 for r in normalized if r.get("color")),
        "size_populated": sum(1 for r in normalized if r.get("storage_variant")),
        "verified": sum(1 for r in normalized if r.get("verified_purchase")),
    }
    log.info("coverage: %s", coverage)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=False)
    log.info("saved %d reviews to %s", len(normalized), OUTPUT_PATH)


if __name__ == "__main__":
    main()