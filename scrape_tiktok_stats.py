# scrape_tiktok_stats.py
# Requires:
#   - requirements.txt with: playwright==1.47.0
#   - chromium installed at build: python -m playwright install chromium
#   - Python 3.11 (e.g., runtime.txt -> python-3.11.9)

import re
import json
import time
import random
import datetime
from typing import Tuple, Optional, List
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

TEST_HANDLES = ["cookitgirleats", "gb.storiess", "foodyfetish"]


def parse_compact_num(s: str) -> Optional[int]:
    """
    Convert '1.2M' / '3,456' / '8.7k' to int.
    Returns None if unknown format.
    """
    if not s:
        return None
    s = s.strip().lower().replace(",", "")
    m = re.match(r"^([\d\.]+)\s*([kmb])?$", s)
    if not m:
        return None
    val = float(m.group(1))
    suf = (m.group(2) or "").lower()
    mult = {"k": 1e3, "m": 1e6, "b": 1e9}.get(suf, 1)
    return int(val * mult)


def extract_stats_from_dom(page) -> Tuple[Optional[int], Optional[int]]:
    """
    Prefer DOM selectors TikTok renders after hydration.
    Returns (followers, total_likes) or (None, None) if not found.
    """
    try:
        # These data-e2e selectors are stable across recent TikTok updates.
        f_txt = page.locator('[data-e2e="followers-count"]').inner_text(timeout=5000)
        l_txt = page.locator('[data-e2e="likes-count"]').inner_text(timeout=5000)
        return parse_compact_num(f_txt), parse_compact_num(l_txt)
    except Exception:
        return None, None


def extract_stats_from_json(html: str) -> Tuple[Optional[int], Optional[int]]:
    """
    Fallback: parse JSON blobs TikTok embeds.
    Try __NEXT_DATA__ first, then legacy SIGI_STATE.
    Returns (followers, total_likes) or (None, None).
    """
    # 1) Next.js data blob
    m = re.search(r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S | re.I)
    if m:
        try:
            j = json.loads(m.group(1))
            user_info = (j.get("props", {}).get("pageProps", {}).get("userInfo", {}) or {})
            st = user_info.get("stats", {}) or {}
            followers = st.get("followerCount")
            likes = st.get("heart")
            if followers is not None or likes is not None:
                return followers, likes
        except Exception:
            pass

    # 2) Legacy SIGI_STATE fallback
    m = re.search(r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>', html, re.S | re.I)
    if m:
        try:
            data = json.loads(m.group(1))
            users = data.get("UserModule", {}).get("users", {})
            stats = data.get("UserModule", {}).get("stats", {})
            if users and stats:
                uid = next(iter(users))
                st = stats.get(uid, {})
                followers = st.get("followerCount")
                likes = st.get("heart")
                if followers is not None or likes is not None:
                    return followers, likes
        except Exception:
            pass

    return None, None


def classify_status(html: str, followers: Optional[int], likes: Optional[int]) -> str:
    """
    Decide status string based on what we found.
    """
    if followers is not None or likes is not None:
        return "ok"

    text = (html or "").lower()
    if "this account is private" in text:
        return "private"
    if "couldn't find this account" in text or "page not available" in text:
        return "not_found"
    return "error"


def polite_sleep(min_s=1.0, max_s=2.5):
    time.sleep(min_s + random.random() * (max_s - min_s))


def scrape_handles(handles: List[str]) -> List[dict]:
    today = datetime.date.today().isoformat()
    rows = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        )
        page = ctx.new_page()

        for h in handles:
            url = f"https://www.tiktok.com/@{h}?lang=en"
            followers = likes = None
            status = "error"

            try:
                # Use networkidle to allow hydration to complete
                page.goto(url, wait_until="networkidle", timeout=45000)

                # Best-effort cookie/consent click (if present)
                try:
                    page.locator('[data-e2e="cookie-banner-accept-button"]').click(timeout=2000)
                    polite_sleep(0.5, 1.0)
                except Exception:
                    pass

                # Try DOM first
                followers, likes = extract_stats_from_dom(page)

                # If DOM failed, fall back to JSON blobs
                if followers is None and likes is None:
                    html = page.content()
                    followers, likes = extract_stats_from_json(html)
                else:
                    html = page.content()

                # Final status assessment
                status = classify_status(html, followers, likes)

            except PWTimeout:
                status = "timeout"
            except Exception as e:
                status = f"error ({type(e).__name__})"

            rows.append(
                {
                    "handle": h,
                    "followers": followers,
                    "total_likes": likes,
                    "date_scraped": today,
                    "status": status,
                }
            )
            polite_sleep()

        browser.close()

    return rows


if __name__ == "__main__":
    data = scrape_handles(TEST_HANDLES)
    for r in data:
        print(r)
