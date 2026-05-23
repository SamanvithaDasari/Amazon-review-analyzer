"""
Amazon.in product review scraper.

Best-effort scrape of the assignment's iPhone 12 product URL. Handles:
  - rotating user agents and realistic browser headers
  - exponential backoff on transient failures
  - polite random delays between page fetches
  - graceful detection of CAPTCHA / block responses
  - structured logging

IMPORTANT DESIGN NOTE:
amazon.in does not expose color or storage variant at the per-review
level for this product. Amazon uses a parent-child ASIN model where a
single review pool is aggregated across all variant child ASINs. The
'Colour: X | Size: Y' annotation that appears on some Amazon products
is not present on this product's reviews. Therefore the scraper does
not attempt to extract these fields; they remain NULL in the database.

Fields extracted per review:
  - review_title
  - review_text
  - rating (1-5)
  - verified_purchase (bool)
  - review_date (string, for bonus temporal analysis)
"""
import json
import logging
import random
import time
from pathlib import Path
from typing import List, Dict, Optional

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from .config import PRODUCT_URL, RAW_SCRAPED_JSON

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP layer
# ---------------------------------------------------------------------------
_UA = UserAgent()

HEADERS_TEMPLATE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def fresh_headers() -> dict:
    """Return a fresh header dict with a randomized User-Agent."""
    return {**HEADERS_TEMPLATE, "User-Agent": _UA.random}


def is_block_page(html: str) -> bool:
    """Heuristic: does this HTML look like a CAPTCHA or anti-bot block page?"""
    lower = html.lower()
    return (
        "captcha" in lower
        or "enter the characters you see below" in lower
        or "automated access" in lower
        or "robot check" in lower
        or "type the characters" in lower
    )


def fetch_with_retry(url: str, max_retries: int = 4) -> Optional[str]:
    """
    GET `url` with retries and exponential backoff.

    Returns HTML string on success, or None if all retries failed.
    """
    for attempt in range(1, max_retries + 1):
        try:
            log.info("GET %s (attempt %d/%d)", url, attempt, max_retries)
            r = requests.get(url, headers=fresh_headers(), timeout=20)

            if r.status_code == 200 and not is_block_page(r.text):
                return r.text

            log.warning(
                "blocked or bad status: status=%s, block_page=%s",
                r.status_code, is_block_page(r.text),
            )
        except requests.RequestException as e:
            log.warning("network error: %s", e)

        # Exponential backoff with jitter
        sleep_for = random.uniform(3, 8) * attempt
        log.info("backing off %.1fs", sleep_for)
        time.sleep(sleep_for)

    return None


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------
def _safe_text(el) -> Optional[str]:
    """Return el's text or None if el is falsy. Collapses whitespace."""
    return el.get_text(" ", strip=True) if el else None


def _parse_rating(block) -> Optional[int]:
    """
    Extract a 1-5 star rating from a review block.

    Amazon renders ratings with class 'a-icon-star' and a hidden span like
    '5.0 out of 5 stars'. We try a few selectors for robustness.
    """
    rating_el = (
        block.select_one('i[data-hook="review-star-rating"] span')
        or block.select_one('i[data-hook="cmps-review-star-rating"] span')
        or block.select_one('i.a-icon-star span.a-icon-alt')
    )
    if not rating_el:
        return None
    txt = rating_el.get_text(strip=True)  # e.g., "5.0 out of 5 stars"
    try:
        return int(float(txt.split()[0]))
    except (ValueError, IndexError):
        return None


def parse_reviews(html: str) -> List[Dict]:
    """
    Extract all review dicts from a single page of HTML.

    Returns a list of dicts. Color and storage are intentionally NOT
    extracted — see module docstring for rationale.

    Selectors updated 2026-05-23 to match amazon.in's current markup:
    Amazon moved from kebab-case (`review-title`, `review-body`) to
    camelCase (`reviewTitle`, `reviewRichContentContainer`) hooks.
    """
    soup = BeautifulSoup(html, "lxml")
    reviews: List[Dict] = []

    for block in soup.select('div[data-hook="review"]'):
        try:
            # Title: now lives inside h5[data-hook="reviewTitle"]
            # We try the new (camelCase) hook first, then fall back to
            # the legacy (kebab-case) one in case Amazon flips back.
            title_el = (
                block.select_one('h5[data-hook="reviewTitle"]')
                or block.select_one('a[data-hook="review-title"] span:not([class])')
                or block.select_one('span[data-hook="review-title"]')
            )

            # Body: now under div[data-hook="reviewRichContentContainer"]
            # The text is wrapped in <p><span>...</span></p> blocks.
            body_el = (
                block.select_one('div[data-hook="reviewRichContentContainer"]')
                or block.select_one('span[data-hook="review-body"] span')
                or block.select_one('span[data-hook="review-body"]')
            )

            # These three are unchanged in the current markup
            verified_el = block.select_one('span[data-hook="avp-badge"]')
            date_el = block.select_one('span[data-hook="review-date"]')

            rating = _parse_rating(block)
            text = _safe_text(body_el)

            # Required fields — skip the block if these aren't present
            if not text or rating is None:
                continue

            reviews.append({
                "review_title": _safe_text(title_el),
                "review_text": text,
                "rating": rating,
                "verified_purchase": verified_el is not None,
                "review_date": _safe_text(date_el),
                "source": "amazon_in_scraped",
            })
        except Exception as e:
            log.debug("skipping a review block: %s", e)

    return reviews

# ---------------------------------------------------------------------------
# Top-level loop
# ---------------------------------------------------------------------------
def scrape_product(url: str = PRODUCT_URL, max_pages: int = 10) -> List[Dict]:
    """
    Walk through the product's review pages until we run out, get blocked,
    or hit max_pages.
    """
    all_reviews: List[Dict] = []

    for page in range(1, max_pages + 1):
        sep = "&" if "?" in url else "?"
        page_url = f"{url}{sep}pageNumber={page}"

        html = fetch_with_retry(page_url)
        if not html:
            log.error("blocked or failed on page %d, stopping", page)
            break

        page_reviews = parse_reviews(html)
        if not page_reviews:
            log.info("no reviews parsed on page %d, stopping", page)
            break

        log.info("page %d: %d reviews", page, len(page_reviews))
        all_reviews.extend(page_reviews)

        # Polite delay between page fetches
        if page < max_pages:
            delay = random.uniform(4, 9)
            log.info("sleeping %.1fs before next page", delay)
            time.sleep(delay)

    return all_reviews


def main():
    """Entry point when run via `python -m src.scraper`."""
    Path(RAW_SCRAPED_JSON).parent.mkdir(parents=True, exist_ok=True)
    reviews = scrape_product()
    with open(RAW_SCRAPED_JSON, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)
    log.info("saved %d reviews to %s", len(reviews), RAW_SCRAPED_JSON)


if __name__ == "__main__":
    main()