"""
Playwright loader: click-based "Show more" + filter variation.

For each (sortBy × starFilter) combination, loads the reviews page
and clicks "Show more reviews" until the button disappears, accumulating
reviews. Dedupes across combos so the same review isn't counted twice.

Run:
    python -m src.playwright_loader

Output: data/playwright_reviews.json
"""
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Set, Tuple

from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, TimeoutError as PWTimeout

from .scraper import parse_reviews

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ASIN = "B08L5TNJHG"
OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "playwright_reviews.json"
PAGE_TIMEOUT_MS = 60000
MAX_CLICKS_PER_COMBO = 25

# All filter combos to iterate
FILTER_COMBOS: List[Dict] = []
for sort in ["helpful", "recent"]:
    for star in ["all_stars", "five_star", "four_star",
                 "three_star", "two_star", "one_star"]:
        FILTER_COMBOS.append({"sortBy": sort, "filterByStar": star})

SHOW_MORE_SELECTORS = [
    'a[data-hook="show-more-button"]',
    'button[data-hook="show-more-button"]',
    'a:has-text("Show more reviews")',
    'button:has-text("Show more reviews")',
    'a:has-text("See more reviews")',
    'button:has-text("See more reviews")',
]


def build_url(asin: str, combo: Dict) -> str:
    base = f"https://www.amazon.in/product-reviews/{asin}/"
    parts = ["ie=UTF8", "reviewerType=all_reviews", f"sortBy={combo['sortBy']}"]
    if combo["filterByStar"] != "all_stars":
        parts.append(f"filterByStar={combo['filterByStar']}")
    return f"{base}?{'&'.join(parts)}"


def review_fingerprint(r: Dict) -> str:
    return hashlib.sha256(
        f"{r.get('review_title') or ''}|"
        f"{(r.get('review_text') or '')[:200]}|"
        f"{r.get('rating', 0)}".encode("utf-8")
    ).hexdigest()


async def amazon_login(page: Page, email: str, password: str) -> None:
    log.info("navigating to amazon.in")
    await page.goto("https://www.amazon.in/", timeout=PAGE_TIMEOUT_MS)
    log.info("opening sign-in")
    try:
        await page.click("#nav-link-accountList", timeout=10000)
    except PWTimeout:
        await page.click("a[data-nav-role='signin']", timeout=10000)

    log.info("entering email")
    await page.wait_for_selector("#ap_email_login, #ap_email", timeout=PAGE_TIMEOUT_MS)
    email_input = (await page.query_selector("#ap_email_login")
                   or await page.query_selector("#ap_email"))
    await email_input.fill(email)
    await page.click("#continue, input[type='submit'][aria-labelledby*='continue']",
                     timeout=10000)

    log.info("entering password")
    await page.wait_for_selector("#ap_password", timeout=PAGE_TIMEOUT_MS)
    await page.fill("#ap_password", password)
    await page.click("#signInSubmit", timeout=10000)

    log.info("waiting for post-login signal")
    try:
        await page.wait_for_selector(
            "#nav-link-accountList-nav-line-1, #auth-mfa-otpcode, input[name='otpCode']",
            timeout=20000)
    except PWTimeout:
        pass

    content = await page.content()
    if any(k in content.lower() for k in ["enter otp", "verification code",
                                            "one-time password",
                                            "two-step verification"]):
        otp = input("\n>>> Enter the OTP Amazon sent you: ").strip()
        for s in ["#auth-mfa-otpcode", "input[name='otpCode']",
                  "input[type='tel']", "input[type='text']"]:
            try:
                await page.fill(s, otp, timeout=5000); break
            except PWTimeout: continue
        for s in ["#auth-signin-button", "input[type='submit']",
                  "button[type='submit']"]:
            try:
                await page.click(s, timeout=5000); break
            except PWTimeout: continue
        try:
            await page.wait_for_selector("#nav-link-accountList-nav-line-1",
                                         timeout=20000)
        except PWTimeout:
            log.warning("could not confirm login after OTP")

    try:
        await page.wait_for_selector("#nav-link-accountList-nav-line-1",
                                     timeout=10000)
        name = await page.text_content("#nav-link-accountList-nav-line-1")
        log.info("logged in as: %s", (name or "?").strip())
    except PWTimeout:
        log.warning("could not confirm login — proceeding")


async def find_show_more_button(page: Page):
    """Return the first visible show-more button element, or None."""
    for selector in SHOW_MORE_SELECTORS:
        try:
            el = await page.query_selector(selector)
            if el and await el.is_visible():
                return el, selector
        except Exception:
            continue
    return None, None


async def click_until_done(page: Page, combo_label: str) -> int:
    """Click 'Show more' until exhausted. Return click count."""
    clicks = 0
    consecutive_failures = 0

    for attempt in range(MAX_CLICKS_PER_COMBO):
        cards = await page.query_selector_all('[data-hook="review"]')
        log.info("  [%s] attempt %d: %d cards visible",
                 combo_label, attempt + 1, len(cards))

        try:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)
        except Exception:
            pass

        button, selector_used = await find_show_more_button(page)
        if not button:
            log.info("  [%s] no show-more button — done", combo_label)
            break

        try:
            await button.click(timeout=10000)
            consecutive_failures = 0
            clicks += 1
        except Exception as e:
            log.warning("  [%s] click failed: %s", combo_label, e)
            consecutive_failures += 1
            if consecutive_failures >= 3:
                log.info("  [%s] 3 consecutive failures — stopping", combo_label)
                break
            continue

        old_count = len(cards)
        for _ in range(20):
            await page.wait_for_timeout(500)
            cards_now = await page.query_selector_all('[data-hook="review"]')
            if len(cards_now) > old_count:
                break
        else:
            log.info("  [%s] no new reviews after click — stopping", combo_label)
            break

        await page.wait_for_timeout(2000)

    return clicks


async def scrape_combo(page: Page, combo: Dict,
                       seen: Set[str], all_reviews: List[Dict]) -> int:
    """Load a combo URL, click show-more until done, parse, dedup, return count added."""
    url = build_url(ASIN, combo)
    combo_label = f"{combo['sortBy']}/{combo['filterByStar']}"
    log.info("=== combo: %s ===", combo_label)
    log.info("  GET %s", url)

    try:
        await page.goto(url, timeout=PAGE_TIMEOUT_MS)
    except PWTimeout:
        log.warning("  nav timeout — continuing")

    try:
        await page.wait_for_selector('[data-hook="review"]', timeout=15000)
    except PWTimeout:
        log.warning("  no reviews on initial load — skipping combo")
        return 0

    clicks = await click_until_done(page, combo_label)
    log.info("  [%s] %d clicks done", combo_label, clicks)

    # CAPTCHA check
    html = await page.content()
    if any(s in html.lower() for s in ["enter the characters", "captcha", "robot check"]):
        log.error("  [%s] CAPTCHA — skipping", combo_label)
        return 0

    page_reviews = parse_reviews(html)
    new_count = 0
    for r in page_reviews:
        r["source"] = f"playwright_{combo['sortBy']}_{combo['filterByStar']}"
        fp = review_fingerprint(r)
        if fp in seen:
            continue
        seen.add(fp)
        all_reviews.append(r)
        new_count += 1
    log.info("  [%s] parsed %d, new %d (overall total %d)",
             combo_label, len(page_reviews), new_count, len(all_reviews))
    return new_count


async def main():
    email = os.environ.get("AMAZON_EMAIL")
    password = os.environ.get("AMAZON_PASSWORD")
    if not email or not password:
        log.error("AMAZON_EMAIL and AMAZON_PASSWORD required in .env")
        sys.exit(1)

    all_reviews: List[Dict] = []
    seen: Set[str] = set()

    # Resume from existing
    if OUTPUT_PATH.exists():
        try:
            for r in json.load(open(OUTPUT_PATH)):
                fp = review_fingerprint(r)
                if fp not in seen:
                    seen.add(fp); all_reviews.append(r)
            log.info("resumed from %d existing reviews", len(all_reviews))
        except Exception as e:
            log.warning("could not load existing: %s", e)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=150)
        ctx = await browser.new_context(
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            locale="en-IN")
        page = await ctx.new_page()

        try:
            await amazon_login(page, email, password)
        except Exception as e:
            log.error("login failed: %s", e)
            try: await page.screenshot(path="/tmp/amazon_login_error.png", full_page=True)
            except Exception: pass
            await browser.close(); sys.exit(1)

        for combo_idx, combo in enumerate(FILTER_COMBOS, 1):
            log.info(">>> combo %d/%d <<<", combo_idx, len(FILTER_COMBOS))
            try:
                added = await scrape_combo(page, combo, seen, all_reviews)
                log.info(">>> combo %d done: %d new (overall %d) <<<",
                         combo_idx, added, len(all_reviews))
            except Exception as e:
                log.error("combo %d blew up: %s", combo_idx, e)

            # Incremental save after every combo
            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
                json.dump(all_reviews, f, indent=2, ensure_ascii=False)
            log.info("saved %d reviews to %s", len(all_reviews), OUTPUT_PATH)

        await browser.close()

    log.info("FINAL: %d unique reviews", len(all_reviews))


if __name__ == "__main__":
    asyncio.run(main())
