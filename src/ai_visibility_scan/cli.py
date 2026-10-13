"""AI Visibility Scan — does AI recommend this local business when a customer asks?

Usage:  ai-visibility-scan profile.json [--engines claude,gemini,chatgpt] [--max-prompts 5] [--out out]
Writes <out>/<slug>-<date>.json and .html. Engines without an API key are skipped. Measured cost (Oct 2026): about
$0.16 per Claude prompt; ChatGPT and Gemini usage is recorded in the JSON — check your provider's billing page.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import engines, report, site_check

DEFAULT_CTA = {"name": "MITS SFL", "phone": "(754) 203-4594", "url": "https://www.mitssfl.net"}
SUFFIXES = re.compile(r"\b(llc|inc|corp|corporation|co|company|ltd|pllc|pa|the)\b\.?", re.I)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", SUFFIXES.sub(" ", s.lower()))).strip()


def build_prompts(p: dict, limit: int) -> list[str]:
    city, cat = p["city"], p["category"]
    svc = p.get("services") or [cat]
    prompts = [
        f"What are the best {cat} companies in {city}? I want someone reliable.",
        f"Who should I call for {svc[0]} in {city}?",
        f"Can you recommend a {cat} company near {city} with good reviews?",
        f"I'm in {city} and need help with {svc[1] if len(svc) > 1 else svc[0]}. Which local company would you recommend?",
    ]
    if p.get("prompt_es"):
        prompts.append(p["prompt_es"])
    prompts += p.get("extra_prompts", [])
    return prompts[:limit]


def mention(p: dict, result: dict, named: list[str]) -> str:
    """named = recommended by name in the answer · cited = only appears in sources · absent."""
    keys = [norm(p["name"])] + [norm(a) for a in p.get("aliases", [])]
    keys = [k for k in keys if len(k) >= 3]
    domain = re.sub(r"^www\.", "", re.sub(r"^https?://", "", p["website"])).split("/")[0].lower()
    has = lambda text: any(re.search(rf"\b{re.escape(k)}\b", norm(text)) for k in keys)  # noqa: E731
    if has(result["answer"]) or domain in result["answer"].lower() or any(has(n) for n in named):
        return "named"
    src = " ".join(f"{s['title']} {s['url']}" for s in result["sources"]).lower()
    if domain in src or has(src):
        return "cited"
    return "absent"


def load_dotenv(path: Path = Path(".env")) -> None:
    """Read KEY=VALUE lines from ./.env into the environment (existing variables win). No dependency needed."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#") and value.strip():
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(prog="ai-visibility-scan",
                                 description="Does AI recommend this local business when a customer asks?")
    ap.add_argument("profile", help="business profile JSON (see examples/profile.example.json)")
    ap.add_argument("--engines", default="claude,gemini,chatgpt")
    ap.add_argument("--max-prompts", type=int, default=5)
    ap.add_argument("--out", default="out", help="output folder (default: ./out)")
    ap.add_argument("--suffix", default="", help="appended to the output file name; use --suffix=-x")
    ap.add_argument("--cta-name", default=DEFAULT_CTA["name"], help="who the report's call-to-action points to")
    ap.add_argument("--cta-phone", default=DEFAULT_CTA["phone"])
    ap.add_argument("--cta-url", default=DEFAULT_CTA["url"])
    ap.add_argument("--no-cta", action="store_true", help="leave the call-to-action box out of the report")
    args = ap.parse_args()

    p = json.loads(Path(args.profile).read_text())
    prompts = build_prompts(p, args.max_prompts)
    city_only, _, region = p["city"].partition(",")
    region = p.get("region", region).strip()
    askers = {"claude": engines.ask_claude, "gemini": engines.ask_gemini, "chatgpt": engines.ask_chatgpt}
    wanted = [e.strip() for e in args.engines.split(",") if e.strip()]
    unknown = [e for e in wanted if e not in askers]
    if unknown:
        ap.error(f"unknown engine(s): {', '.join(unknown)} (choose from {', '.join(askers)})")
    use = [e for e in wanted if engines.available(e)]
    for e in wanted:
        if e not in use:
            print(f"skipping {e}: no API key ({engines.KEYS[engines.ENGINE_KEYS[e]]})", file=sys.stderr)
    if not use:
        ap.error("no engine has an API key — set ANTHROPIC_API_KEY, GEMINI_API_KEY and/or OPENAI_API_KEY")
    jobs = [(e, q) for e in use for q in prompts]
    print(f"Scanning {p['name']}: {len(prompts)} prompts x {len(use)} engines ({', '.join(use)})", file=sys.stderr)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda j: askers[j[0]](j[1], city_only.strip(), region.strip()), jobs))
        site = pool.submit(site_check.check, p["website"], re.sub(r"\D", "", p.get("phone", ""))).result()

    ok = [r for r in results if r["answer"] and not r["error"]]
    # Listing who else was recommended needs Claude; without an Anthropic key the competitor table stays empty.
    named_lists = engines.extract_businesses([r["answer"] for r in ok]) if ok and engines.available("claude") else []
    for r, named in zip(ok, named_lists):
        r["businesses"] = named
    for r in results:
        r.setdefault("businesses", [])
        r["status"] = mention(p, r, r["businesses"]) if r in ok else "error"

    me = [norm(p["name"])] + [norm(a) for a in p.get("aliases", [])]
    competitors = Counter(
        b for r in ok for b in dict.fromkeys(r["businesses"])
        if not any(k and re.search(rf"\b{re.escape(k)}\b", norm(b)) for k in me))
    scored = [r for r in results if r["status"] != "error"]
    data = {
        "business": p, "scanned_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "cta": None if args.no_cta else {"name": args.cta_name, "phone": args.cta_phone, "url": args.cta_url},
        "prompts": prompts, "results": results, "site": site,
        "competitors": competitors.most_common(10),
        "score": {
            "answers": len(scored),
            "named": sum(r["status"] == "named" for r in scored),
            "cited": sum(r["status"] == "cited" for r in scored),
            "errors": len(results) - len(scored),
            "site_pass": sum(c["status"] == "pass" for c in site), "site_total": len(site),
        },
        # Opus 5.5 list price $4/$20 per MTok; web search $10 per 1,000 searches. Extraction call not included.
        "claude_cost_usd": round(sum(r.get("usage", {}).get("input_tokens", 0) * 4e-6
                                     + r.get("usage", {}).get("output_tokens", 0) * 20e-6
                                     + r.get("usage", {}).get("web_searches", 0) * 0.01
                                     for r in results if r["engine"] == "Claude"), 3),
        # ChatGPT: raw usage only (model pricing not recorded here; check the OpenAI billing page).
        "chatgpt_usage": {k: sum(r.get("usage", {}).get(k, 0) for r in results if r["engine"] == "ChatGPT")
                          for k in ("input_tokens", "output_tokens", "web_searches")},
    }
    slug = re.sub(r"[^a-z0-9]+", "-", p["name"].lower()).strip("-")
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = out_dir / f"{slug}-{dt.date.today().isoformat()}{args.suffix}"
    stem.with_suffix(".json").write_text(json.dumps(data, indent=2))
    stem.with_suffix(".html").write_text(report.render(data))
    s = data["score"]
    print(f"Named in {s['named']}/{s['answers']} AI answers (cited-only {s['cited']}, errors {s['errors']}); "
          f"site checks {s['site_pass']}/{s['site_total']}. Report: {stem.with_suffix('.html')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
