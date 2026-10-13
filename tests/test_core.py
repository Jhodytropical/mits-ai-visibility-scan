"""Offline tests: no API keys and no network."""
import json

import pytest

from ai_visibility_scan import cli, engines, report, site_check

PROFILE = {"name": "MITS SFL", "aliases": ["mitssfl"], "website": "https://www.mitssfl.net", "city": "Hollywood, FL",
           "category": "web design", "services": ["an AI receptionist", "a website"], "prompt_es": "¿Quién?"}


def result(answer="", sources=()):
    return {"answer": answer, "sources": [{"title": t, "url": u} for t, u in sources]}


def test_norm_strips_suffixes_and_punctuation():
    assert cli.norm("MITS SFL, Corp.") == "mits sfl"
    assert cli.norm("The Example Co.") == "example"


def test_build_prompts_uses_profile_and_limit():
    prompts = cli.build_prompts(PROFILE, 5)
    assert prompts[0] == "What are the best web design companies in Hollywood, FL? I want someone reliable."
    assert prompts[-1] == "¿Quién?"
    assert len(cli.build_prompts(PROFILE, 2)) == 2


def test_mention_named_cited_absent():
    assert cli.mention(PROFILE, result("Try MITS SFL for this."), []) == "named"
    assert cli.mention(PROFILE, result("See www.mitssfl.net"), []) == "named"
    assert cli.mention(PROFILE, result("Try Acme.", [("x", "https://www.mitssfl.net/faq")]), []) == "cited"
    assert cli.mention(PROFILE, result("Try Acme."), []) == "absent"
    assert cli.mention(PROFILE, result("Try Acme."), ["MITS SFL Corp"]) == "named"


def test_mention_uses_word_boundaries():
    # "submits" contains "mits" — must not count as a mention of the alias "mitssfl" or the name.
    p = dict(PROFILE, aliases=["MITS"])
    assert cli.mention(p, result("Everyone submits a form."), []) == "absent"


def test_jsonld_nodes_reads_graph_and_lists():
    html = ('<script type="application/ld+json">{"@graph":[{"@type":"LocalBusiness","telephone":"1"}]}</script>'
            '<script type="application/ld+json">[{"@type":"WebPage"}]</script>'
            '<script type="application/ld+json">not json</script>')
    types = sorted(n.get("@type", "") for n in site_check._jsonld_nodes(html))
    assert "LocalBusiness" in types and "WebPage" in types


def _data(cta):
    return {"business": PROFILE, "scanned_at": "2026-10-13T09:00:00-04:00", "prompts": ["q"], "cta": cta,
            "results": [{"engine": "ChatGPT", "model": "m", "prompt": "q <b>", "answer": "a", "sources": [],
                         "businesses": ["Acme <x>"], "status": "absent"}],
            "site": [{"id": "https", "label": "Secure (HTTPS)", "status": "fail", "detail": "d", "fix": "Install SSL."}],
            "competitors": [["Acme <x>", 1]],
            "score": {"answers": 1, "named": 0, "cited": 0, "errors": 0, "site_pass": 0, "site_total": 1}}


def test_report_escapes_html_and_shows_cta():
    html = report.render(_data({"name": "Agency", "phone": "(555) 010-0000", "url": "https://example.com"}))
    assert "Acme &lt;x&gt;" in html and "q &lt;b&gt;" in html
    assert 'href="tel:+15550100000"' in html and "Agency can make these changes" in html
    assert "ChatGPT was not measured" not in html


def test_report_without_cta():
    assert 'class="cta"' not in report.render(_data(None))


def test_keys_env_then_folder_then_missing(monkeypatch, tmp_path):
    for var in engines.KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AIVS_SECRETS_DIR", raising=False)
    assert not engines.available("chatgpt")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        engines._key("openai_key")
    (tmp_path / "openai_key").write_text("from-file\n")
    monkeypatch.setenv("AIVS_SECRETS_DIR", str(tmp_path))
    assert engines._key("openai_key") == "from-file"
    monkeypatch.setenv("OPENAI_API_KEY", "from-env")
    assert engines._key("openai_key") == "from-env"


def test_cli_skips_engines_without_keys(monkeypatch, tmp_path, capsys):
    for var in engines.KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AIVS_SECRETS_DIR", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(engines, "ask_chatgpt", lambda q, c, r: {
        "engine": "ChatGPT", "model": "m", "prompt": q, "answer": "Call MITS SFL.", "sources": [], "error": None,
        "usage": {"input_tokens": 1, "output_tokens": 1, "web_searches": 0}})
    monkeypatch.setattr(site_check, "check", lambda url, phone="": [])
    (tmp_path / "p.json").write_text(json.dumps(PROFILE))
    monkeypatch.setattr("sys.argv", ["ai-visibility-scan", "p.json", "--max-prompts", "2", "--no-cta"])
    assert cli.main() == 0
    err = capsys.readouterr().err
    assert "skipping claude" in err and "skipping gemini" in err and "Named in 2/2" in err
    data = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert data["cta"] is None and data["competitors"] == []
