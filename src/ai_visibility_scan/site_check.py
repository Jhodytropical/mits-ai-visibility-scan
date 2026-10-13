"""Read-only checks of a business website for the signals AI search engines use to find and trust it.

Each check returns {"id", "label", "status": pass|warn|fail, "detail", "fix"}. Only public pages are fetched.
"""
from __future__ import annotations

import json
import re
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
AI_CRAWLERS = {
    "OAI-SearchBot": "ChatGPT search", "ChatGPT-User": "ChatGPT browsing", "GPTBot": "OpenAI training",
    "Claude-SearchBot": "Claude search", "ClaudeBot": "Anthropic training", "PerplexityBot": "Perplexity",
    "Google-Extended": "Gemini training",
}
SEARCH_CRAWLERS = ("OAI-SearchBot", "ChatGPT-User", "Claude-SearchBot", "PerplexityBot")
LOCAL_TYPES = re.compile(r"(LocalBusiness|Service|Store|Contractor|Business|Restaurant|Dentist|Attorney|"
                         r"Plumber|Electrician|HVAC|Roofing|Clinic|Physician|Agency|Organization)", re.I)


def _get(url: str, **kw) -> requests.Response | None:
    try:
        return requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True, **kw)
    except requests.RequestException:
        return None


def _jsonld_nodes(html: str) -> list[dict]:
    nodes = []
    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            data = json.loads(raw.strip())
        except ValueError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                nodes.append(n)
                stack += n.get("@graph", []) if isinstance(n.get("@graph"), list) else []
            elif isinstance(n, list):
                stack += n
    return nodes


def check(website: str, phone_digits: str = "") -> list[dict]:
    results: list[dict] = []
    add = lambda i, label, status, detail, fix="": results.append(  # noqa: E731
        {"id": i, "label": label, "status": status, "detail": detail, "fix": fix})

    home = _get(website)
    if home is None or home.status_code >= 400:
        add("reachable", "Website loads", "fail", f"Homepage did not load ({getattr(home, 'status_code', 'no response')}).",
            "Fix the website first: AI engines cannot recommend what they cannot read.")
        return results
    html, final = home.text, home.url
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
    add("reachable", "Website loads", "pass", f"{final} returned {home.status_code}.")
    add("https", "Secure (HTTPS)", "pass" if final.startswith("https://") else "fail",
        "Served over HTTPS." if final.startswith("https://") else "Site is not on HTTPS.",
        "Install an SSL certificate and redirect http to https.")

    # Can AI crawlers read the site?
    rp = robotparser.RobotFileParser()
    robots = _get(urljoin(base, "/robots.txt"))
    rp.parse(robots.text.splitlines() if robots is not None and robots.status_code == 200 else [])
    blocked = [a for a in AI_CRAWLERS if not rp.can_fetch(a, final)]
    blocked_search = [a for a in blocked if a in SEARCH_CRAWLERS]
    if blocked_search:
        add("crawlers", "AI search crawlers allowed", "fail",
            "robots.txt blocks: " + ", ".join(f"{a} ({AI_CRAWLERS[a]})" for a in blocked_search) + ".",
            "Allow the AI *search* crawlers in robots.txt (training crawlers can stay blocked if you prefer).")
    elif blocked:
        add("crawlers", "AI search crawlers allowed", "pass",
            "Search crawlers allowed; training-only crawlers blocked: " + ", ".join(blocked) + " (a business choice).")
    else:
        add("crawlers", "AI search crawlers allowed", "pass", "No AI crawler is blocked in robots.txt.")

    # Structured business data
    nodes = _jsonld_nodes(html)
    types = []
    for n in nodes:
        t = n.get("@type")
        types += t if isinstance(t, list) else [t] if t else []
    biz = [n for n in nodes if any(LOCAL_TYPES.search(str(t)) for t in
                                   (n.get("@type") if isinstance(n.get("@type"), list) else [n.get("@type")]))]
    if not biz:
        add("schema", "Business schema (JSON-LD)", "fail",
            f"No LocalBusiness-type structured data on the homepage (found: {', '.join(map(str, types)) or 'none'}).",
            "Add LocalBusiness JSON-LD (name, address, phone, hours, service area, sameAs links to your profiles).")
    else:
        b = biz[0]
        missing = [f for f in ("address", "telephone", "openingHoursSpecification", "areaServed", "sameAs")
                   if not b.get(f) and not (f == "openingHoursSpecification" and b.get("openingHours"))]
        add("schema", "Business schema (JSON-LD)", "pass" if not missing else "warn",
            f"Found {b.get('@type')}." + (f" Missing: {', '.join(missing)}." if missing else " Core fields present."),
            "Complete the schema: " + ", ".join(missing) + "." if missing else "")
        # No review-markup check: Google ignores self-serving review markup on LocalBusiness pages (2026-10-13);
        # reviews count where they live (Google, Yelp, industry sites) — covered by the report's listings fix.

    # Name / phone consistency on the page
    text = re.sub(r"<[^>]+>", " ", html)
    if phone_digits:
        on_page = phone_digits[-10:] in re.sub(r"\D", "", text)
        add("phone", "Phone number visible on homepage", "pass" if on_page else "fail",
            "Phone number found in page text." if on_page else "Phone number not found in homepage text.",
            "Put the phone number in plain text (not only in an image) in the header or footer.")

    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)', html, re.I)
    add("meta", "Title and description say what + where", "pass" if title and desc else "warn",
        f"Title: {title.group(1).strip()[:90] if title else 'missing'} · Description: "
        f"{'present' if desc else 'missing'}.",
        "Write a title and meta description naming your service and city (e.g. 'AC Repair in Hollywood, FL').")

    llms = _get(urljoin(base, "/llms.txt"))
    ok_llms = llms is not None and llms.status_code == 200 and "<html" not in llms.text[:500].lower()
    add("llms", "llms.txt summary file", "pass" if ok_llms else "warn",
        "llms.txt present." if ok_llms else "No /llms.txt.",
        "Optional, low-cost: publish /llms.txt summarizing services, area and contact. "
        "Adoption by AI engines is unconfirmed; treat as hygiene, not a ranking lever.")

    sm = _get(urljoin(base, "/sitemap.xml"))
    ok_sm = sm is not None and sm.status_code == 200 and ("<urlset" in sm.text[:2000] or "<sitemapindex" in sm.text[:2000])
    add("sitemap", "Sitemap", "pass" if ok_sm else "warn", "sitemap.xml found." if ok_sm else "No /sitemap.xml.",
        "Publish a sitemap and submit it in Google Search Console and Bing Webmaster Tools.")
    return results
