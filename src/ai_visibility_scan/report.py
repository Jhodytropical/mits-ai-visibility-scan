"""Render a scan as a one-page, printable HTML report written for the business owner."""
from __future__ import annotations

import datetime as dt
import re
from html import escape as e

CSS = """
:root{--ink:#14213d;--muted:#5b6475;--line:#e3e7ee;--bg:#f6f8fb;--card:#fff;--good:#1a7f4b;--warn:#a86400;--bad:#b42318;--accent:#2457d6}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
main{max-width:920px;margin:0 auto;padding:32px 16px 64px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:16px;flex-wrap:wrap;border-bottom:2px solid var(--ink);padding-bottom:12px}
h1{font-size:26px;margin:0}h2{font-size:18px;margin:32px 0 10px}.muted{color:var(--muted)}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:20px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.stat b{display:block;font-size:34px;line-height:1.1}.stat span{color:var(--muted);font-size:13px}
.verdict{margin-top:16px;padding:16px;border-radius:10px;background:var(--card);border-left:5px solid var(--bad)}
.verdict.ok{border-left-color:var(--good)}.verdict.mid{border-left-color:var(--warn)}
.tw{overflow-x:auto;border:1px solid var(--line);border-radius:10px;background:var(--card)}
table{width:100%;border-collapse:collapse;min-width:520px}
th,td{text-align:left;padding:9px 10px;border-bottom:1px solid var(--line);vertical-align:top;font-size:14px}th{background:#eef2f8;font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.pill{display:inline-block;padding:2px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.named,.pass{background:#e3f4ea;color:var(--good)}.cited,.warn{background:#fff1dc;color:var(--warn)}.absent,.fail,.error{background:#fde7e5;color:var(--bad)}
ol.fix li{margin:0 0 10px}.cta{margin-top:32px;padding:18px;border-radius:10px;background:var(--ink);color:#fff}.cta a{color:#fff}
footer{margin-top:28px;font-size:12px;color:var(--muted)}
@media print{body{background:#fff}.stat,.verdict,.tw{break-inside:avoid}.tw{overflow:visible}table{min-width:0}}
"""


def _pill(cls: str, text: str) -> str:
    return f'<span class="pill {e(cls)}">{e(text)}</span>'


def _cta(c: dict | None) -> str:
    if not c:
        return ""
    tel = "+1" + re.sub(r"\D", "", c["phone"])[-10:] if c.get("phone") else ""
    phone = f' Call or WhatsApp <a href="tel:{e(tel)}">{e(c["phone"])}</a> ·' if tel else ""
    site = re.sub(r"^https?://(www\.)?", "", c.get("url", "")).rstrip("/")
    link = f' <a href="{e(c["url"])}">{e(site)}</a>' if c.get("url") else ""
    return (f'<div class="cta"><b>Want this fixed for you?</b> {e(c["name"])} can make these changes and re-scan monthly so '
            f"you can see whether AI assistants start naming you.{phone}{link}</div>")


def render(d: dict) -> str:
    p, s = d["business"], d["score"]
    when = dt.datetime.fromisoformat(d["scanned_at"]).strftime("%B %-d, %Y")
    n, tot = s["named"], s["answers"] or 1
    pct = round(100 * n / tot)
    tone, line = (("ok", "AI assistants already recommend you. Keep the signals consistent and monitor monthly.") if pct >= 50 else
                  ("mid", "AI assistants mention you sometimes, but competitors get most of the recommendations.") if n else
                  ("", "When customers ask AI assistants for a business like yours, you are not being recommended."))
    engines_used = sorted({r["engine"] for r in d["results"]})
    labels = {"named": "Recommended", "cited": "Source only", "absent": "Not mentioned", "error": "No answer"}

    rows = "".join(
        f"<tr><td>{e(r['prompt'])}</td><td>{e(r['engine'])}</td><td>{_pill(r['status'], labels[r['status']])}</td>"
        f"<td>{e(', '.join(r['businesses'][:5])) or '<span class=muted>—</span>'}</td></tr>" for r in d["results"])
    comp = "".join(f"<tr><td>{e(name)}</td><td>{c} of {tot}</td></tr>" for name, c in d["competitors"]) or \
        "<tr><td colspan=2 class=muted>No other businesses were named.</td></tr>"
    checks = "".join(
        f"<tr><td>{e(c['label'])}</td><td>{_pill(c['status'], c['status'].upper())}</td><td>{e(c['detail'])}</td></tr>"
        for c in d["site"])
    fixes = [c for c in d["site"] if c["status"] == "fail"] + [c for c in d["site"] if c["status"] == "warn"]
    fix_items = "".join(f"<li><b>{e(c['label'])}.</b> {e(c['fix'])}</li>" for c in fixes if c["fix"])
    fix_items += ("<li><b>Reviews and listings.</b> Make sure your Google Business Profile, Bing Places, Yelp and "
                  "industry directories show the same name, address, phone and hours. AI answers lean on these "
                  "third-party sources (the sources column of this scan shows which ones).</li>")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Visibility Scan — {e(p['name'])}</title><style>{CSS}</style></head><body><main>
<header><div><div class="muted">AI Visibility Scan</div><h1>{e(p['name'])}</h1>
<div class="muted">{e(p['category'])} · {e(p['city'])}</div></div><div class="muted">{e(when)}</div></header>

<div class="hero">
 <div class="stat"><b>{n} / {s['answers']}</b><span>AI answers that recommended you by name</span></div>
 <div class="stat"><b>{s['cited']}</b><span>answers that used your site as a source but did not name you</span></div>
 <div class="stat"><b>{s['site_pass']} / {s['site_total']}</b><span>website signals in place</span></div>
</div>
<div class="verdict {tone}"><b>{e(line)}</b><br><span class="muted">45% of US consumers used an AI tool to find a local
business in 2026, up from 6% a year earlier (BrightLocal Local Consumer Review Survey, Feb 2026, 1,002 adults).</span></div>

<h2>Who AI recommends instead</h2>
<div class="tw"><table><tr><th>Business named by AI</th><th>Times named</th></tr>{comp}</table></div>

<h2>What we asked, and what AI said</h2>
<div class="tw"><table><tr><th>Customer question</th><th>Assistant</th><th>You</th><th>Businesses named</th></tr>{rows}</table></div>

<h2>Your website: can AI read and trust it?</h2>
<div class="tw"><table><tr><th>Signal</th><th>Status</th><th>Detail</th></tr>{checks}</table></div>

<h2>What to fix first</h2><ol class="fix">{fix_items}</ol>

{_cta(d.get("cta"))}

<footer><b>How this scan works.</b> We asked {e(', '.join(engines_used))} the questions above on {e(when)} with live
web search turned on, as a customer in {e(p['city'])} would, and recorded whether your business was named.
Models: {e(', '.join(sorted({r['model'] for r in d['results']})))} via their developer APIs. AI answers change from
one run to the next and can differ from the consumer apps{'' if 'ChatGPT' in engines_used else '; ChatGPT was not measured in this edition'}. No one can
guarantee placement in AI answers. The fixes above improve the signals AI tools read; results are measured, not
promised.</footer>
</main></body></html>"""
