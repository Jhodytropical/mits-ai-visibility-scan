"""Read-only checks of a business website for the signals AI search engines use to find and trust it.

Each check returns {"id", "label", "status": pass|warn|fail, "detail", "fix"}. Only public pages are fetched.
"""
from __future__ import annotations
import html as html_lib

import json
import re
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests

from . import pagespeed

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
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20, allow_redirects=True, **kw)
    except requests.RequestException:
        return None
    _fix_encoding(r)
    return r


def _fix_encoding(r) -> None:
    """Without a charset in Content-Type, requests decodes text/* as Latin-1, so UTF-8 titles read as mojibake
    (perimeter-os.com, djhyvyb.com, 2026-10-31). Browsers use the page's <meta charset>; so do we."""
    if "charset" in (r.headers.get("Content-Type") or "").lower():
        return
    m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', r.content[:4096], re.I)
    if m:
        r.encoding = m.group(1).decode("ascii", "ignore")


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


FIELDS = ("address", "telephone", "openingHoursSpecification", "areaServed", "sameAs")
# Business type (2026-11-01, from screening our own sites: Perimeter OS and PianoBoss were marked down for missing hours and
# service area, which a software product does not have). "online" = software / product / online-only business: it is asked
# for the organization fields instead. The field list is our choice (MITS policy), not a Google requirement.
BUSINESS_TYPES = ("local", "online")
ONLINE_TYPES = re.compile(r"(Organization|Corporation|SoftwareApplication|WebApplication|MobileApplication|Product|Brand|"
                          r"OnlineBusiness|OnlineStore)", re.I)
ONLINE_FIELDS = ("name", "url", "logo", "sameAs")


def _business_type(value: str) -> str:
    v = (value or "local").strip().lower()
    v = "online" if v in ("software", "product", "saas") else v
    if v not in BUSINESS_TYPES:
        raise ValueError(f"business_type must be one of {BUSINESS_TYPES}, got {value!r}")
    return v
PLACEHOLDER = re.compile(r"your (?:law )?(?:firm|business|company|practice|street)[\w ]*here|yourfirmwebsite|yourwebsite\.com|"
                         r"example\.com|lorem ipsum|555-01\d\d", re.I)


def _types(n: dict) -> list:
    t = n.get("@type")
    return t if isinstance(t, list) else [t] if t else []


def schema_result(html: str, business_type: str = "local") -> tuple[str, str, str]:
    """(status, detail, fix) for the homepage's business data. Reads every JSON-LD business node (an Organization node
    often comes before the Dentist/LegalService one), schema.org microdata, and notices JSON-LD added by a script."""
    nodes = _jsonld_nodes(html)
    if _business_type(business_type) == "online":
        return _online_schema_result(html, nodes)
    biz = [n for n in nodes if any(LOCAL_TYPES.search(str(t)) for t in _types(n))]
    if biz:
        found = ", ".join(dict.fromkeys(str(t) for n in biz for t in _types(n)))
        if PLACEHOLDER.search(json.dumps(biz)):
            return ("warn", f"Found {found}, but it holds template placeholders (for example 'Your … Here') instead of your details.",
                    "Replace the template values with your real business name, address, phone and website.")
        have = {f for n in biz for f in FIELDS if n.get(f) or (f == "openingHoursSpecification" and n.get("openingHours"))}
        missing = [f for f in FIELDS if f not in have]
        return ("pass" if not missing else "warn",
                f"Found {found}." + (f" Missing: {', '.join(missing)}." if missing else " Core fields present."),
                "Complete the schema: " + ", ".join(missing) + "." if missing else "")
    micro = [t for t in re.findall(r'itemtype=["\']https?://schema\.org/(\w+)["\']', html, re.I) if LOCAL_TYPES.search(t)]
    if micro:
        props = {p.lower() for p in re.findall(r'itemprop=["\'](\w+)["\']', html, re.I)}
        have = {f for f in FIELDS if f.lower() in props or (f == "address" and "streetaddress" in props)
                or (f == "openingHoursSpecification" and "openinghours" in props)}
        missing = [f for f in FIELDS if f not in have]
        found = ", ".join(dict.fromkeys(micro))
        return ("pass" if not missing else "warn",
                f"Found {found} (microdata)." + (f" Missing: {', '.join(missing)}." if missing else " Core fields present."),
                "Complete the business data: " + ", ".join(missing) + "." if missing else "")
    static_removed = re.sub(r'<script[^>]+application/ld\+json[^>]*>.*?</script>', " ", html, flags=re.S | re.I)
    if re.search(r"application/ld\+json", static_removed, re.I):
        return ("warn", "Business schema is added by a script after the page loads; search tools that don't run scripts can't read it.",
                "Put the LocalBusiness JSON-LD directly in the page's HTML instead of adding it with a script.")
    types = [str(t) for n in nodes for t in _types(n)]
    return ("fail", f"No LocalBusiness-type structured data on the homepage (found: {', '.join(types) or 'none'}).",
            "Add LocalBusiness JSON-LD (name, address, phone, hours, service area, sameAs links to your profiles).")


def _online_schema_result(html: str, nodes: list[dict]) -> tuple[str, str, str]:
    """Schema check for an online / software business: an Organization or product node with name, url, logo, sameAs."""
    org = [n for n in nodes if any(ONLINE_TYPES.search(str(t)) or LOCAL_TYPES.search(str(t)) for t in _types(n))]
    if org:
        found = ", ".join(dict.fromkeys(str(t) for n in org for t in _types(n)))
        if PLACEHOLDER.search(json.dumps(org)):
            return ("warn", f"Found {found}, but it holds template placeholders instead of your details.",
                    "Replace the template values with your real company name, website and profile links.")
        have = {f for n in org for f in ONLINE_FIELDS if n.get(f) or (f == "logo" and n.get("image"))}
        missing = [f for f in ONLINE_FIELDS if f not in have]
        return ("pass" if not missing else "warn",
                f"Found {found} (checked as an online/software business: address, hours and service area not required)."
                + (f" Missing: {', '.join(missing)}." if missing else " Core fields present."),
                "Complete the schema: " + ", ".join(missing) + "." if missing else "")
    static_removed = re.sub(r'<script[^>]+application/ld\+json[^>]*>.*?</script>', " ", html, flags=re.S | re.I)
    if re.search(r"application/ld\+json", static_removed, re.I):
        return ("warn", "Company schema is added by a script after the page loads; search tools that don't run scripts can't read it.",
                "Put the Organization JSON-LD directly in the page's HTML instead of adding it with a script.")
    types = [str(t) for n in nodes for t in _types(n)]
    return ("fail", f"No Organization or product structured data on the homepage (found: {', '.join(types) or 'none'}).",
            "Add Organization JSON-LD (name, url, logo, sameAs links to your profiles); for a product also SoftwareApplication.")


def _description(html: str) -> str | None:
    for tag in re.findall(r"<meta\b[^>]*>", html, re.I):
        if re.search(r'name=["\']description["\']', tag, re.I):
            m = re.search(r'content=["\']([^"\']*)', tag, re.I)
            if m:
                return html_lib.unescape(m.group(1)).strip()
    return None


def meta_result(html: str, city: str = "") -> tuple[str, str, str]:
    """(status, detail, fix): a title and a description exist, and one of them names the city."""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    t = re.sub(r"\s+", " ", html_lib.unescape(title.group(1))).strip() if title else ""
    desc = _description(html)
    town = city.split(",")[0].strip()
    towns = {town.lower()} | ({"miami"} if "miami" in town.lower() else set())
    named = not town or any(x and x in f"{t} {desc or ''}".lower() for x in towns)
    detail = f"Title: {t[:90] or 'missing'} · Description: {'present' if desc else 'missing'}."
    example = f"Your Service in {city}" if city else "AC Repair in Hollywood, FL"
    if not t or not desc:
        return "warn", detail, f"Write a {'title and ' if not t else ''}meta description naming your service and city (e.g. '{example}')."
    if not named:
        return "warn", detail + f" Neither mentions {town}.", f"Name your city in the title or description (e.g. '{example}')."
    return "pass", detail, ""


def noindex_result(html: str, headers=None) -> tuple[str, str, str] | None:
    """(status, detail, fix) only when the homepage tells search engines not to index it; None (no row) otherwise."""
    meta = re.search(r'<meta[^>]+name=["\'](?:robots|googlebot)["\'][^>]*content=["\'][^"\']*noindex', html, re.I) or \
        re.search(r'<meta[^>]+content=["\'][^"\']*noindex[^"\']*["\'][^>]*name=["\'](?:robots|googlebot)', html, re.I)
    header = "noindex" in ((headers or {}).get("X-Robots-Tag", "") or "").lower()
    if not (meta or header):
        return None
    return ("fail", "The homepage tells search engines not to list it (" + ("meta robots tag" if meta else "X-Robots-Tag header") + ").",
            "Remove the noindex setting (often a 'discourage search engines' box left on in WordPress) unless it is intentional.")


def alt_result(html: str) -> tuple[str, str, str] | None:
    """(status, detail, fix) for image descriptions. Counts only <img> tags with NO alt attribute: alt="" is the correct
    markup for decorative images. None (no row) when the homepage has fewer than 3 images."""
    imgs = re.findall(r"<img\b[^>]*>", html, re.I)
    if len(imgs) < 3:
        return None
    missing = [i for i in imgs if not re.search(r"\balt\s*=", i, re.I)]
    share = len(missing) / len(imgs)
    detail = f"{len(missing)} of {len(imgs)} homepage images have no description (alt text)."
    return ("warn" if share >= 0.25 else "pass", detail,
            "Add a short description to each meaningful image (what it shows, e.g. 'Dr. Lopez with a patient in our Coral Gables "
            "office'); search and AI tools can't see images, and screen readers read these aloud." if share >= 0.25 else "")


BROKEN = (404, 410) + tuple(range(500, 600))  # 401/403/429 are usually bot protection, not a broken page


def broken_links_result(html: str, final: str, limit: int = 25, head=None) -> tuple[str, str, str] | None:
    """(status, detail, fix) for the homepage's own links: up to `limit` same-site links, broken = 404/410/5xx.
    None when the homepage has no same-site links to test."""
    head = head or (lambda u: requests.head(u, headers={"User-Agent": UA}, timeout=10, allow_redirects=True))
    host = urlparse(final).netloc
    base = re.search(r'<base\b[^>]*href=["\']([^"\']+)', html, re.I)  # <base href> changes what relative links point to
    root = urljoin(final, base.group(1)) if base else final
    links = list(dict.fromkeys(urljoin(root, m).split("#")[0] for m in re.findall(r'<a\b[^>]*href=["\']([^"\'#][^"\']*)', html, re.I)
                               if not m.startswith(("mailto:", "tel:", "javascript:", "sms:"))
                               and not re.search(r"[{}$<>&()]|Href|\.link$|^\w+(\.\w+){2,}$|cdn-cgi/", m)))
    # skipped: template placeholders (not real links) and Cloudflare's email-protection link (404 to any non-browser)
    links = [u for u in links if urlparse(u).netloc == host and u.rstrip("/") != final.rstrip("/")][:limit]
    if not links:
        return None
    bad = []
    for u in links:
        try:
            r = head(u)
            if r.status_code in (405, 501) or r.status_code in BROKEN:  # some servers mishandle HEAD: confirm with a real GET
                r = _get(u) or r
        except requests.RequestException:
            continue
        if r.status_code in BROKEN:
            bad.append((u, r.status_code))
    if not bad:
        return "pass", f"All {len(links)} homepage links we tested work.", ""
    shown = "; ".join(f"{urlparse(u).path or '/'} ({c})" for u, c in bad[:3])
    return ("fail", f"{len(bad)} of {len(links)} homepage links we tested lead to an error page: {shown}"
                    + ("…" if len(bad) > 3 else "") + ".",
            "Fix or remove the broken links (point them to the right page, or redirect the old address).")


FIELD_WORDS = {"FAST": "fast", "AVERAGE": "average", "SLOW": "slow"}


def speed_result(psi: dict) -> tuple[str, str, str] | None:
    """(status, detail, fix) from one PageSpeed mobile run, using Google's own bands (90+ good, 50–89 needs work,
    under 50 poor). None when the run has no score — an unmeasured site gets no row rather than a false failure."""
    lh = (psi or {}).get("lighthouseResult") or {}
    score = ((lh.get("categories") or {}).get("performance") or {}).get("score")
    if score is None:
        return None
    s = round(score * 100)
    lcp = ((lh.get("audits") or {}).get("largest-contentful-paint") or {}).get("displayValue")
    field = FIELD_WORDS.get(((psi.get("loadingExperience") or {}).get("overall_category") or "").upper())
    detail = (f"Mobile score {s}/100 in Google's PageSpeed test" + (f"; the main content appears after {lcp}" if lcp else "")
              + "." + (f" Real Chrome visitors rate it {field}." if field else "")
              + " One lab test; scores move a few points between runs.")
    fix = ("Speed up the mobile site: compress and resize images, remove unused plugins and scripts, and turn on caching. "
           "Google's PageSpeed report lists each item for your web host or developer.")
    return ("pass" if s >= 90 else "warn" if s >= 50 else "fail"), detail, ("" if s >= 90 else fix)


def sitemap_candidates(base: str, robots_text: str = "") -> list[str]:
    declared = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots_text or "")
    return list(dict.fromkeys([urljoin(base, "/sitemap.xml")] + declared[:3]
                              + [urljoin(base, "/sitemap_index.xml"), urljoin(base, "/wp-sitemap.xml")]))


def check(website: str, phone_digits: str = "", city: str = "", business_type: str = "local") -> list[dict]:
    business_type = _business_type(business_type)
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
    status, detail, fix = schema_result(html, business_type)
    add("schema", "Business schema (JSON-LD)" if business_type == "local" else "Company schema (JSON-LD)", status, detail, fix)
        # No review-markup check: Google ignores self-serving review markup on LocalBusiness pages (2026-10-13);
        # reviews count where they live (Google, Yelp, industry sites) — covered by the report's listings fix.

    # Name / phone consistency on the page
    text = re.sub(r"<[^>]+>", " ", html)
    if phone_digits:
        on_page = phone_digits[-10:] in re.sub(r"\D", "", text)
        add("phone", "Phone number visible on homepage", "pass" if on_page else "fail",
            "Phone number found in page text." if on_page else "Phone number not found in homepage text.",
            "Put the phone number in plain text (not only in an image) in the header or footer.")

    status, detail, fix = meta_result(html, city)
    add("meta", "Title and description name your city" if city else "Title and description present", status, detail, fix)

    llms = _get(urljoin(base, "/llms.txt"))
    ok_llms = llms is not None and llms.status_code == 200 and "<html" not in llms.text[:500].lower()
    add("llms", "llms.txt summary file", "pass" if ok_llms else "warn",
        "llms.txt present." if ok_llms else "No /llms.txt.",
        "Optional, low-cost: publish /llms.txt summarizing services, area and contact. "
        "Adoption by AI engines is unconfirmed; treat as hygiene, not a ranking lever.")

    found_sm = None
    for url in sitemap_candidates(base, robots.text if robots is not None and robots.status_code == 200 else ""):
        sm = _get(url)
        if sm is not None and sm.status_code == 200 and ("<urlset" in sm.text[:2000] or "<sitemapindex" in sm.text[:2000]):
            found_sm = url
            break
    add("sitemap", "Sitemap", "pass" if found_sm else "warn",
        f"Sitemap found at {found_sm}." if found_sm else "No sitemap at /sitemap.xml or in robots.txt.",
        "Publish a sitemap and submit it in Google Search Console and Bing Webmaster Tools.")

    for i, label, res in (("noindex", "Homepage listed by search engines", noindex_result(html, home.headers)),
                          ("alt", "Image descriptions (alt text)", alt_result(html)),
                          ("links", "Homepage links work", broken_links_result(html, final))):
        if res:
            add(i, label, *res)

    # Mobile page speed (Google PageSpeed Insights) — only when credentials are configured; unmeasured = no row.
    if pagespeed.configured():
        sp = speed_result(pagespeed.run(final))
        if sp:
            add("speed", "Mobile page speed (Google PageSpeed)", *sp)
    return results
