"""
Selenium + undetected-chromedriver loader for amazon.in reviews.

You log in manually within the visible browser. Script waits for
actual review cards (not just URL match) before iterating filters.

Run:
    python -m src.selenium_loader
"""
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Set, Tuple

import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ASIN = "B08L5TNJHG"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "selenium_reviews.json"
LOGIN_WAIT_SECONDS = 180  # 3 minutes — plenty for manual login + OTP
PAGE_DWELL_SECONDS = 6
MAX_PAGES = 10
CHROME_MAJOR = 148

FILTER_COMBOS = []
for sort in ["recent", "helpful"]:
    for star in ["all_stars", "five_star", "four_star", "three_star", "two_star", "one_star"]:
        FILTER_COMBOS.append({"sortBy": sort, "filterByStar": star})


def build_url(asin: str, page: int, combo: Dict) -> str:
    base = f"https://www.amazon.in/product-reviews/{asin}"
    parts = [
        "ie=UTF8",
        "reviewerType=all_reviews",
        f"pageNumber={page}",
        f"sortBy={combo['sortBy']}",
    ]
    if combo["filterByStar"] != "all_stars":
        parts.append(f"filterByStar={combo['filterByStar']}")
    return f"{base}?{'&'.join(parts)}"


def extract_review(card) -> Dict:
    def safe(selector):
        try:
            return card.find_element(By.CSS_SELECTOR, selector).text.strip()
        except Exception:
            return ""

    review_id = card.get_attribute("id") or ""

    title_text = safe('[data-hook="review-title"]')
    if title_text:
        lines = [ln for ln in title_text.split("\n") if "out of 5 stars" not in ln.lower()]
        title_text = " ".join(lines).strip()

    rating_text = safe('[data-hook="review-star-rating"]')
    m = re.search(r"([\d.]+)\s*out of 5", rating_text)
    try:
        rating = int(float(m.group(1))) if m else None
    except Exception:
        rating = None

    body = safe('[data-hook="review-body"]')
    date = safe('[data-hook="review-date"]')
    verified = bool(card.find_elements(By.CSS_SELECTOR, '[data-hook="avp-badge"]'))

    return {
        "review_id": review_id,
        "review_title": title_text or None,
        "review_text": body,
        "rating": rating,
        "verified_purchase": verified,
        "review_date": date or None,
        "source": "amazon_in_selenium",
    }


def load_existing(path: Path) -> Tuple[List[Dict], Set[str]]:
    if not path.exists():
        return [], set()
    try:
        data = json.load(open(path, encoding="utf-8"))
        seen = {r.get("review_id") for r in data if r.get("review_id")}
        log.info("resuming from %d existing reviews", len(data))
        return data, seen
    except Exception as e:
        log.warning("could not load existing: %s", e)
        return [], set()


def save(reviews: List[Dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2, ensure_ascii=False)


def is_logged_in_and_on_reviews(driver) -> bool:
    """Strong check: we have review cards AND the URL matches reviews page."""
    url = (driver.current_url or "").lower()
    if ASIN.lower() not in url or "product-reviews" not in url:
        return False
    try:
        cards = driver.find_elements(By.CSS_SELECTOR, '[data-hook="review"]')
        return len(cards) > 0
    except Exception:
        return False


def wait_for_login_then_reviews(driver, timeout: int = LOGIN_WAIT_SECONDS) -> bool:
    """
    Wait until: (a) URL is on the reviews page AND (b) review cards are visible.

    This avoids the bug where the URL briefly matches mid-redirect but no
    reviews are loaded yet.
    """
    print("\n" + "=" * 60)
    print("Browser is opening Amazon login.")
    print("LOG IN MANUALLY in the browser window.")
    print(f"You have {timeout} seconds. After login, Amazon will redirect to")
    print("the reviews page and the script will continue automatically.")
    print("=" * 60 + "\n")

    start = time.time()
    last_log_url = None
    while time.time() - start < timeout:
        elapsed = int(time.time() - start)
        if is_logged_in_and_on_reviews(driver):
            log.info("login detected with reviews visible (after %ds)", elapsed)
            # Extra settling time
            time.sleep(5)
            # Re-verify after settle
            if is_logged_in_and_on_reviews(driver):
                return True
        # Periodic status
        cur_url = driver.current_url[:80] if driver.current_url else ""
        if cur_url != last_log_url and elapsed % 5 == 0:
            log.info("waiting for login... (%ds remaining) url=%s",
                     timeout - elapsed, cur_url)
            last_log_url = cur_url
        time.sleep(1)
    return False


def main():
    all_reviews, seen_ids = load_existing(OUTPUT_PATH)

    log.info("starting Chrome (undetected_chromedriver, version_main=%d)", CHROME_MAJOR)
    driver = uc.Chrome(headless=False, version_main=CHROME_MAJOR)
    log.info("Chrome started")
    time.sleep(2)

    try:
        # Go to reviews page → Amazon will redirect to login
        initial_url = f"https://www.amazon.in/product-reviews/{ASIN}?ie=UTF8&reviewerType=all_reviews"
        log.info("opening %s", initial_url)
        driver.get(initial_url)
        time.sleep(3)

        # Manual login window
        if not wait_for_login_then_reviews(driver, timeout=LOGIN_WAIT_SECONDS):
            log.error("login window expired. final URL: %s", driver.current_url[:120])
            return

        log.info("starting filter iteration")

        for combo_idx, combo in enumerate(FILTER_COMBOS, 1):
            log.info("=== combo %d/%d: %s ===", combo_idx, len(FILTER_COMBOS), combo)
            combo_added = 0

            for page_num in range(1, MAX_PAGES + 1):
                url = build_url(ASIN, page_num, combo)
                log.info("  GET %s", url)
                try:
                    driver.get(url)
                except Exception as e:
                    log.warning("nav error: %s", e)
                    continue

                time.sleep(PAGE_DWELL_SECONDS)

                # Scroll trick
                try:
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(2)
                    driver.execute_script("window.scrollTo(0, 0)")
                    time.sleep(1)
                except Exception:
                    pass

                # Session sanity check
                cur = (driver.current_url or "").lower()
                if "product-reviews" not in cur or ASIN.lower() not in cur:
                    log.warning("session may be lost. URL: %s", driver.current_url[:120])
                    log.info("pausing 60s for you to re-login if needed...")
                    # Give user 60s to manually re-login
                    if not wait_for_login_then_reviews(driver, timeout=60):
                        log.error("could not recover session, stopping")
                        break
                    # After re-login, retry this page
                    driver.get(url)
                    time.sleep(PAGE_DWELL_SECONDS)

                # CAPTCHA detection
                source = driver.page_source.lower()
                if any(s in source for s in ["enter the characters", "captcha", "robot check"]):
                    log.error("CAPTCHA on combo %d page %d — skipping combo", combo_idx, page_num)
                    break

                cards = driver.find_elements(By.CSS_SELECTOR, '[data-hook="review"]')
                log.info("  page %d: %d cards", page_num, len(cards))

                if not cards:
                    log.info("  no cards — stopping this combo")
                    break

                page_added = 0
                for card in cards:
                    try:
                        r = extract_review(card)
                    except Exception as e:
                        log.debug("extract failure: %s", e)
                        continue
                    rid = r.get("review_id")
                    if not rid or rid in seen_ids:
                        continue
                    if not r.get("review_text") or r.get("rating") is None:
                        continue
                    seen_ids.add(rid)
                    all_reviews.append(r)
                    page_added += 1
                combo_added += page_added
                log.info("  page %d: %d new (running total %d)",
                         page_num, page_added, len(all_reviews))

                time.sleep(2)

            log.info("=== combo done: %d new (overall %d) ===", combo_added, len(all_reviews))
            save(all_reviews, OUTPUT_PATH)
            log.info("saved %d reviews to %s", len(all_reviews), OUTPUT_PATH)

        log.info("FINAL: %d unique reviews", len(all_reviews))

    finally:
        try:
            driver.quit()
        except Exception:
            pass


if __name__ == "__main__":
    main()
