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


def test_build_prompts_professional_wording():
    pro = {**PROFILE, "category": "estate planning attorney", "provider": "estate planning attorney",
           "provider_plural": "estate planning attorneys", "services": ["a will or trust", "probate"]}
    prompts = cli.build_prompts(pro, 4)
    assert prompts[0] == "What are the best estate planning attorneys in Hollywood, FL? I want someone reliable."
    assert prompts[2] == "Can you recommend an estate planning attorney near Hollywood, FL with good reviews?"
    assert prompts[3].endswith("Which local estate planning attorney would you recommend?")
    assert not any("compan" in q for q in prompts)
    dentist = {**pro, "provider": "cosmetic dentist", "provider_plural": "cosmetic dentists"}
    assert cli.build_prompts(dentist, 3)[2].startswith("Can you recommend a cosmetic dentist near")


def test_mention_named_cited_absent():
    assert cli.mention(PROFILE, result("Try MITS SFL for this."), []) == "named"
    assert cli.mention(PROFILE, result("See www.mitssfl.net"), []) == "named"
    assert cli.mention(PROFILE, result("Try Acme.", [("x", "https://www.mitssfl.net/faq")]), []) == "cited"
    assert cli.mention(PROFILE, result("Try Acme."), []) == "absent"
    assert cli.mention(PROFILE, result("Try Acme."), ["MITS SFL Corp"]) == "named"


def test_mention_ignores_longer_place_name():
    p = dict(PROFILE, name="Gables Physical Therapy", aliases=[], website="https://gablespt.example")
    assert cli.mention(p, result("Try Coral Gables Physical Therapy on Ponce."), []) == "absent"
    assert cli.mention(p, result("Try Gables Physical Therapy on Madeira."), []) == "named"


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


def test_schema_reads_every_business_node():
    html = ('<script type="application/ld+json">{"@type": "Organization", "name": "X"}</script>'
            '<script type="application/ld+json">{"@type": "Dentist", "address": "1 Main", "telephone": "1", '
            '"openingHours": "Mo", "areaServed": "Miami", "sameAs": ["https://g.co/x"]}</script>')
    status, detail, _ = site_check.schema_result(html)
    assert status == "pass" and "Missing" not in detail


def test_schema_microdata_counts():
    html = ('<div itemscope itemtype="http://schema.org/LocalBusiness"><span itemprop="streetAddress">1 Polk</span>'
            '<span itemprop="telephone">954</span></div>')
    status, detail, _ = site_check.schema_result(html)
    assert status == "warn" and "microdata" in detail and "address" not in detail.split("Missing:")[-1]


def test_schema_added_by_script_is_named():
    html = "<script>var s=document.createElement('script');s.type='application/ld+json';s.text='{}';</script>"
    status, detail, _ = site_check.schema_result(html)
    assert status == "warn" and "script" in detail


def test_schema_template_placeholders():
    html = '<script type="application/ld+json">{"@type": "LegalService", "name": "Your Law Firm Name Here"}</script>'
    status, detail, _ = site_check.schema_result(html)
    assert status == "warn" and "placeholder" in detail


def test_meta_checks_city_and_attribute_order():
    html = '<title>Dentistry in Dora, FL</title><meta content="Family dentist." name="description">'
    status, detail, _ = site_check.meta_result(html, "Doral, FL")
    assert status == "warn" and "Doral" in detail and "Description: present" in detail
    ok = '<title>Dentist in Doral, FL</title><meta name="description" content="Family dentist.">'
    assert site_check.meta_result(ok, "Doral, FL")[0] == "pass"


def test_sitemap_candidates_follow_robots():
    urls = site_check.sitemap_candidates("https://a.com", "User-agent: *\nSitemap: https://a.com/sitemap_index.xml\n")
    assert urls[0] == "https://a.com/sitemap.xml" and "https://a.com/sitemap_index.xml" in urls


def test_report_escapes_html_and_shows_cta():
    html = report.render(_data({"name": "Agency", "phone": "(555) 010-0000", "url": "https://example.com"}))
    assert "Acme &lt;x&gt;" in html and "q &lt;b&gt;" in html
    assert 'href="tel:+15550100000"' in html and "Agency can make these changes" in html
    assert "ChatGPT was not measured" not in html


def test_report_says_when_an_assistant_got_fewer_questions():
    d = _data(None)
    d["results"] += [{"engine": "Claude", "model": "m2", "prompt": p, "answer": "a", "sources": [], "businesses": [],
                      "status": "absent"} for p in ("q <b>", "second q")]
    html = report.render(d)
    assert "ChatGPT was asked 1 of the 2 questions" in html and "Claude was asked" not in html
    assert "was asked" not in report.render(_data(None))  # one engine, all questions: no note


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


def test_claude_uses_its_own_key_never_the_shared_one(monkeypatch, tmp_path):
    for var in list(engines.KEYS.values()) + ["ANTHROPIC_API_KEY"]:
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "anthropic_key").write_text("shared\n")      # the Jarvis/Nexux key file
    monkeypatch.setenv("AIVS_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "shared-env")
    assert not engines.available("claude")
    (tmp_path / "aivs_anthropic_key").write_text("own\n")
    assert engines.available("claude") and engines._key("aivs_anthropic_key") == "own"


def test_cli_skips_engines_without_keys(monkeypatch, tmp_path, capsys):
    for var in engines.KEYS.values():
        monkeypatch.delenv(var, raising=False)
    monkeypatch.delenv("AIVS_SECRETS_DIR", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(engines, "ask_chatgpt", lambda q, c, r: {
        "engine": "ChatGPT", "model": "m", "prompt": q, "answer": "Call MITS SFL.", "sources": [], "error": None,
        "usage": {"input_tokens": 1, "output_tokens": 1, "web_searches": 0}})
    monkeypatch.setattr(site_check, "check", lambda url, phone="", city="", business_type="local": [])
    (tmp_path / "p.json").write_text(json.dumps(PROFILE))
    monkeypatch.setattr("sys.argv", ["ai-visibility-scan", "p.json", "--max-prompts", "2", "--no-cta"])
    assert cli.main() == 0
    err = capsys.readouterr().err
    assert "skipping claude" in err and "skipping gemini" in err and "Named in 2/2" in err
    data = json.loads(next((tmp_path / "out").glob("*.json")).read_text())
    assert data["cta"] is None and data["competitors"] == []


def _psi(score, lcp="3.1 s", field=None):
    d = {"lighthouseResult": {"categories": {"performance": {"score": score}},
                              "audits": {"largest-contentful-paint": {"displayValue": lcp}}}}
    if field:
        d["loadingExperience"] = {"overall_category": field}
    return d


def test_speed_uses_google_bands():
    assert site_check.speed_result(_psi(0.95))[0] == "pass"
    assert site_check.speed_result(_psi(0.95))[2] == ""
    assert site_check.speed_result(_psi(0.90))[0] == "pass"
    assert site_check.speed_result(_psi(0.89))[0] == "warn"
    assert site_check.speed_result(_psi(0.50))[0] == "warn"
    assert site_check.speed_result(_psi(0.49))[0] == "fail"
    status, detail, fix = site_check.speed_result(_psi(0.42, "6.1 s", "SLOW"))
    assert "42/100" in detail and "6.1 s" in detail and "rate it slow" in detail and "images" in fix


def test_speed_unmeasured_gives_no_row(monkeypatch):
    assert site_check.speed_result(None) is None
    assert site_check.speed_result({"lighthouseResult": {"categories": {}}}) is None

    class R:
        status_code, text, url = 200, "<html><title>x</title></html>", "https://a.com/"
        headers = {}
    monkeypatch.setattr(site_check, "_get", lambda url, **kw: R())
    monkeypatch.delenv("PAGESPEED_API_KEY", raising=False)
    monkeypatch.delenv("PAGESPEED_SA_KEY", raising=False)
    assert "speed" not in [c["id"] for c in site_check.check("https://a.com/")]
    monkeypatch.setenv("PAGESPEED_API_KEY", "test")
    monkeypatch.setattr(site_check.pagespeed, "run", lambda url: None)  # quota/timeout
    assert "speed" not in [c["id"] for c in site_check.check("https://a.com/")]
    monkeypatch.setattr(site_check.pagespeed, "run", lambda url: _psi(0.3))
    row = [c for c in site_check.check("https://a.com/") if c["id"] == "speed"][0]
    assert row["status"] == "fail" and row["label"].startswith("Mobile page speed")


def test_noindex_only_reported_when_present():
    assert site_check.noindex_result('<meta name="robots" content="index,follow">') is None
    assert site_check.noindex_result('<meta name="robots" content="noindex, nofollow">')[0] == "fail"
    assert site_check.noindex_result('<meta content="noindex" name="googlebot">')[0] == "fail"
    assert site_check.noindex_result("", {"X-Robots-Tag": "noindex"})[0] == "fail"


def test_alt_counts_only_missing_attribute():
    deco = '<img src=a alt=""><img src=b alt=""><img src=c alt="">'  # decorative images done right
    assert site_check.alt_result(deco)[0] == "pass"
    assert site_check.alt_result('<img src=a><img src=b>') is None  # fewer than 3 images: no row
    st, det, fix = site_check.alt_result('<img src=a><img src=b alt="x"><img src=c alt="y"><img src=d alt="z">')
    assert st == "warn" and det.startswith("1 of 4") and "description" in fix
    assert site_check.alt_result('<img src=a><img src=b alt="x"><img src=c alt="y"><img src=d alt="z"><img src=e alt="w">')[0] == "pass"


def test_broken_links_ignore_bot_blocks_and_other_sites(monkeypatch):
    class R:
        def __init__(self, c): self.status_code = c
    monkeypatch.setattr(site_check, "_get", lambda u, **kw: R(codes[u]))  # GET confirms HEAD's 404
    html = ('<a href="/ok">a</a><a href="/gone">b</a><a href="/blocked">c</a><a href="https://other.com/x">d</a>'
            '<a href="tel:123">e</a><a href="/ok#top">f</a><a href="/">home</a><a href="callHref">g</a><a href="&">h</a>'
            '<a href="/cdn-cgi/l/email-protection">i</a><a href="homepage.welcome.ctaLink">j</a>')
    codes = {"https://a.com/ok": 200, "https://a.com/gone": 404, "https://a.com/blocked": 403}
    seen = []
    st, det, _ = site_check.broken_links_result(html, "https://a.com/", head=lambda u: seen.append(u) or R(codes[u]))
    assert st == "fail" and "1 of 3" in det and "/gone (404)" in det
    assert sorted(seen) == sorted(codes)  # other sites, tel:, #fragments and the homepage itself are not fetched
    assert site_check.broken_links_result('<a href="/ok">a</a>', "https://a.com/", head=lambda u: R(200))[0] == "pass"
    assert site_check.broken_links_result("<p>no links</p>", "https://a.com/") is None


def test_head_404_but_get_200_is_not_broken(monkeypatch):
    class R:
        def __init__(self, c): self.status_code = c
    monkeypatch.setattr(site_check, "_get", lambda u, **kw: R(200))
    assert site_check.broken_links_result('<a href="/home">a</a>', "https://a.com/", head=lambda u: R(404))[0] == "pass"


def test_broken_links_follow_base_href(monkeypatch):
    class R:
        def __init__(self, c): self.status_code = c
    seen = []
    site_check.broken_links_result('<base href="https://a.com/site/"><a href="page.html">x</a>', "https://a.com/",
                                   head=lambda u: seen.append(u) or R(200))
    assert seen == ["https://a.com/site/page.html"]


def test_meta_charset_used_when_header_has_none():
    class R:
        headers = {"Content-Type": "text/html"}
        content = '<html><head><meta charset="UTF-8"><title>A \u2014 B</title>'.encode("utf-8")
        encoding = "ISO-8859-1"
    r = R(); site_check._fix_encoding(r)
    assert r.encoding == "UTF-8"
    r = R(); r.headers = {"Content-Type": "text/html; charset=windows-1252"}; site_check._fix_encoding(r)
    assert r.encoding == "ISO-8859-1"   # an explicit header charset wins, as in browsers


def test_schema_online_business_type_skips_local_fields():
    """2026-11-01: software/product sites are asked for name, url, logo, sameAs - not address, hours, service area."""
    org = ('<script type="application/ld+json">{"@context":"https://schema.org","@type":"Organization","name":"Perimeter OS",'
           '"url":"https://perimeter-os.com","logo":"https://perimeter-os.com/logo.png"}</script>')
    status, detail, fix = site_check.schema_result(org)  # default stays local: same result as before
    assert status == "warn" and "openingHoursSpecification" in detail
    status, detail, fix = site_check.schema_result(org, "online")
    assert status == "warn" and "Missing: sameAs." in detail and "openingHours" not in detail
    app = ('<script type="application/ld+json">{"@type":"SoftwareApplication","name":"PianoBoss","url":"https://x.app",'
           '"image":"https://x.app/i.png","sameAs":["https://youtube.com/@x"]}</script>')
    assert site_check.schema_result(app, "software")[0] == "pass"  # "software" is an alias; image counts as logo
    assert site_check.schema_result(app)[0] == "fail"  # a local scan still wants LocalBusiness data
    status, detail, fix = site_check.schema_result('<script type="application/ld+json">{"@type":"WebSite","name":"x"}</script>', "online")
    assert status == "fail" and "Organization JSON-LD" in fix


def test_business_type_rejects_unknown_values():
    import pytest
    with pytest.raises(ValueError):
        site_check.schema_result("<html></html>", "franchise")
