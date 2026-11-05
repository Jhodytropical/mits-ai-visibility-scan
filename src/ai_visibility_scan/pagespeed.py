"""Google PageSpeed Insights (mobile, performance only) — free API, no Google client libraries needed.

Credentials, first one found (the key-less quota is shared and usually exhausted):
  PAGESPEED_API_KEY  an API key with the PageSpeed Insights API enabled
  PAGESPEED_SA_KEY   path to a service-account JSON key whose project has the PageSpeed Insights API enabled
Neither set -> configured() is False and the scan skips the speed check (no row, so it never reads as a failure).
"""
from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path

import requests

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
_tok: dict = {}


def configured() -> bool:
    return bool(os.environ.get("PAGESPEED_API_KEY") or os.environ.get("PAGESPEED_SA_KEY"))


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _sa_token(path: str) -> str:
    """OAuth token for a service account (same JWT flow as MITS_Operations/weekly_site_report/gsc.py), cached ~55 min."""
    if _tok.get("path") == path and _tok.get("exp", 0) > time.time():
        return _tok["value"]
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    k = json.loads(Path(path).read_text())
    now = int(time.time())
    head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps({"iss": k["client_email"], "scope": "openid", "aud": k["token_uri"],
                            "iat": now, "exp": now + 3600}).encode())
    pk = serialization.load_pem_private_key(k["private_key"].encode(), password=None)
    sig = _b64(pk.sign(f"{head}.{body}".encode(), padding.PKCS1v15(), hashes.SHA256()))
    r = requests.post(k["token_uri"], data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                            "assertion": f"{head}.{body}.{sig}"}, timeout=60)
    r.raise_for_status()
    _tok.update(path=path, value=r.json()["access_token"], exp=time.time() + 3300)
    return _tok["value"]


def run(url: str) -> dict | None:
    """Raw PageSpeed JSON for one mobile run, or None if it could not be measured (quota, timeout, site error)."""
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    headers = {}
    if os.environ.get("PAGESPEED_API_KEY"):
        params["key"] = os.environ["PAGESPEED_API_KEY"]
    elif os.environ.get("PAGESPEED_SA_KEY"):
        try:
            headers["Authorization"] = "Bearer " + _sa_token(os.environ["PAGESPEED_SA_KEY"])
        except Exception:  # noqa: BLE001 — no token means no measurement, never a failed check
            return None
    try:
        r = requests.get(API, params=params, headers=headers, timeout=120)
    except requests.RequestException:
        return None
    return r.json() if r.status_code == 200 else None
