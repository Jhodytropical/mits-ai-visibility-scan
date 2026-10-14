# AI Visibility Scan

**When a customer asks ChatGPT, Claude or Gemini for a business like yours, are you named?**

45% of US consumers now use AI tools for local recommendations, up from 6% a year earlier (BrightLocal Local Consumer
Review Survey, Feb 2026, 1,002 adults). Most small businesses are never mentioned. This tool measures it for one business and writes a one-page report the owner can read.

It:

1. Asks each AI assistant 4–5 real buyer questions ("Who should I call for a leaking water heater in Hollywood, FL?"),
   with live web search on and the customer's city set, the way a customer would.
2. Records whether the business was **recommended by name**, **used only as a source**, or **not mentioned**.
3. Lists **who the AI recommends instead**.
4. Checks the website for the signals AI tools read: HTTPS, AI search crawlers allowed in `robots.txt`, `LocalBusiness`
   structured data (hours, area, phone), phone in plain text, title/description, `llms.txt`, sitemap.
5. Writes `report.html` (printable, phone-friendly) and the raw `report.json`.

| Assistant | API used | Notes |
|---|---|---|
| ChatGPT | OpenAI Responses API + `web_search` | `gpt-5.3-chat-latest`, falling back to `gpt-5.5` |
| Claude | Anthropic Messages API + web search | `claude-opus-5-5` |
| Gemini | Gemini API + Google Search grounding | `gemini-flash-latest` |

## Install

```bash
git clone https://github.com/Jhodytropical/mits-ai-visibility-scan.git
cd mits-ai-visibility-scan
python3 -m venv .venv && .venv/bin/pip install -e .
```

## API keys (bring your own; none are included)

Set any of these. An assistant without a key is skipped.

```bash
cp .env.example .env    # then fill in your keys; .env is gitignored
```

or export `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` in your shell. You can also point `AIVS_SECRETS_DIR` at a
folder holding files named `openai_key`, `anthropic_key` and `gemini_api_key`. The "who AI recommends instead" table uses
Claude; without an Anthropic key it stays empty.

## Run

```bash
cp examples/profile.example.json my-business.json   # edit name, website, phone, city, category, services
.venv/bin/ai-visibility-scan my-business.json
.venv/bin/ai-visibility-scan my-business.json --engines chatgpt --max-prompts 3   # cheaper
.venv/bin/ai-visibility-scan my-business.json --no-cta                            # no call-to-action box
.venv/bin/ai-visibility-scan my-business.json --cta-name "Your Agency" --cta-phone "(555) 010-0000" --cta-url https://example.com
```

The profile's `category` is a noun phrase that reads naturally in "best {category} companies"; `services` holds two buyer
phrasings; `prompt_es` adds a Spanish question; `extra_prompts` adds your own.

## Cost

Each scan makes real paid API calls. Measured in October 2026: about **$0.16 per Claude question** (roughly 30k input tokens
of search results plus 1–3 searches). ChatGPT and Gemini usage is written to the JSON; check your provider's billing page.
A full 5-question, 3-assistant scan is typically a few dollars or less.

## Honest limits

- API answers can differ from what the ChatGPT, Claude and Gemini apps show, and they change from run to run. Re-scan
  over time; treat one scan as a sample, not a ranking.
- Nobody can guarantee placement in AI answers. The fixes in the report improve the signals AI tools read; results are
  measured, not promised.
- Check each provider's terms for your use. Running scans for your own business or your clients is developer/business use.

## Tests

```bash
.venv/bin/pip install -e '.[test]' && .venv/bin/pytest -q     # offline; no API keys or network needed
```

## Contributing safely

`scripts/install_hooks.sh` installs a pre-commit/pre-push check that refuses to commit anything that looks like an API key.

## About

Built by [MITS SFL](https://www.mitssfl.net), Hollywood, Florida. We also do the fixes: structured data, listings
consistency, and monthly re-scans. MIT licensed.
