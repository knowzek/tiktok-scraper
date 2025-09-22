# scrape_tiktok_stats.py
# pip install playwright pandas
# playwright install chromium

import re, json, time, random, datetime
from playwright.sync_api import sync_playwright

TEST_HANDLES = ["cookitgirleats", "gb.storiess", "foodyfetish"]

def parse_compact_num(s):
    """Turn '1.2M' or '3,456' into an int."""
    s = s.strip().lower().replace(',', '')
    m = re.match(r'^([\d\.]+)\s*([kmb])?$', s)
    if not m:
        return None
    val, suf = float(m.group(1)), m.group(2)
    mult = {'k': 1e3, 'm': 1e6, 'b': 1e9}.get(suf, 1)
    return int(val * mult)

def extract_stats(page_content):
    """Try to pull follower & like counts from TikTok page HTML."""
    # Method 1: TikTok JSON blob
    m = re.search(r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>',
                  page_content, re.S | re.I)
    if m:
        try:
            data = json.loads(m.group(1))
            users = data.get("UserModule", {}).get("users", {})
            stats = data.get("UserModule", {}).get("stats", {})
            if users:
                uid = next(iter(users))
                st = stats.get(uid, {})
                return st.get("followerCount"), st.get("heart")
        except Exception:
            pass
    # Method 2: fallback to visible text
    m1 = re.search(r'Followers[^0-9]*([\d\.,]+[KMBkmb]?)', page_content)
    m2 = re.search(r'Likes[^0-9]*([\d\.,]+[KMBkmb]?)', page_content)
    if m1 and m2:
        return parse_compact_num(m1.group(1)), parse_compact_num(m2.group(1))
    return None, None

def scrape_handles(handles):
    today = datetime.date.today().isoformat()
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36")
        )
        page = ctx.new_page()
        for h in handles:
            url = f"https://www.tiktok.com/@{h}"
            status = "ok"
            followers = likes = None
            try:
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=45000)
                if not resp or resp.status >= 400:
                    status = "not_found" if resp and resp.status == 404 else "error"
                else:
                    html = page.content()
                    text = html.lower()
                    if "this account is private" in text:
                        status = "private"
                    elif "couldn't find this account" in text or "page not available" in text:
                        status = "not_found"
                    else:
                        followers, likes = extract_stats(html)
                        if followers is None and likes is None:
                            status = "error"
                time.sleep(1 + random.random() * 1.5)  # polite delay
            except Exception as e:
                status = f"error ({e})"

            results.append({
                "handle": h,
                "followers": followers,
                "total_likes": likes,
                "date_scraped": today,
                "status": status
            })
        browser.close()
    return results

if __name__ == "__main__":
    data = scrape_handles(TEST_HANDLES)
    for row in data:
        print(row)
