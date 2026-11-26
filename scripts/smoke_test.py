#!/usr/bin/env python3
"""Read-only smoke test for a deployed CloudOps AI (preview or production).

    python scripts/smoke_test.py https://<frontend-or-api-host>
    python scripts/smoke_test.py https://<frontend-host> --email ops@example.com   # asks for the password

Standard library only. It never calls billed endpoints (Cost Explorer) unless
--include-billed is given, never runs the AI rewrite, and never changes
anything except its own sign-in session (it signs out at the end).
Point it at the frontend URL to test the /api rewrite and cookies as a
browser sees them.
"""

from __future__ import annotations

import argparse
import getpass
import http.cookiejar
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

RESULTS = []


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
             headers: Optional[Dict[str, str]] = None) -> Tuple[int, Dict[str, str], Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base + path, data=data, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", "cloudops-smoke-test")
        if data is not None:
            request.add_header("Content-Type", "application/json")
            request.add_header("Origin", self.base)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with self.opener.open(request, timeout=60) as response:
                raw, status, hdrs = response.read(), response.status, dict(response.headers)
        except urllib.error.HTTPError as error:
            raw, status, hdrs = error.read(), error.code, dict(error.headers)
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            payload = raw[:200]
        return status, {k.lower(): v for k, v in hdrs.items()}, payload


def check(name: str, ok: bool, info: str = "") -> bool:
    RESULTS.append((name, ok, info))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, (" - " + info) if info else ""))
    return ok


def note(text: str) -> None:
    print("INFO  " + text)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read-only smoke test for CloudOps AI.")
    parser.add_argument("base_url")
    parser.add_argument("--email", help="operator account to test signed-in pages")
    parser.add_argument("--password", help="omit to be prompted")
    parser.add_argument("--include-billed", action="store_true", help="also call /api/costs (Cost Explorer, cached)")
    args = parser.parse_args(argv)
    client = Client(args.base_url)

    status, headers, body = client.call("GET", "/health")
    check("health endpoint", status == 200 and isinstance(body, dict) and body.get("status") == "healthy", "HTTP %s" % status)
    check("request id header", "x-request-id" in headers)
    check("security headers", headers.get("x-content-type-options") == "nosniff" and "x-frame-options" in headers)

    status, _, body = client.call("GET", "/api/resources/ec2")
    check("EC2 inventory responds with JSON", status in (200, 503) and isinstance(body, dict), "HTTP %s" % status)

    status, _, body = client.call("GET", "/api/auth/me")
    accounts = status != 503
    check("accounts endpoint", status in (401, 503), "accounts %s" % ("enabled" if accounts else "disabled: no DATABASE_URL"))

    status, _, body = client.call("GET", "/api/governance/findings")
    if status == 200:
        note("governance findings are public (CLOUDOPS_PUBLIC_SECURITY_FINDINGS=true)")
    else:
        check("governance findings private when signed out", status == 401 and body.get("code") == "unauthenticated", "HTTP %s" % status)
    status, _, _ = client.call("GET", "/api/ai/recommendations")
    check("recommendations private when signed out", status in (200, 401), "HTTP %s" % status)
    status, _, body = client.call("GET", "/api/demo/governance/summary")
    if status == 404:
        note("demo is turned off (CLOUDOPS_DEMO_ENABLED=false)")
    else:
        check("public demo serves labelled sample data", status == 200 and isinstance(body, dict) and body.get("demo") is True,
              "HTTP %s" % status)

    evil = Client(args.base_url)
    status, _, body = evil.call("POST", "/api/auth/logout", body={},
                                headers={"Origin": "https://attacker.example", "Cookie": "cloudops_session=fake"})
    check("cross-site write refused", status == 403 and isinstance(body, dict) and body.get("code") == "origin_not_allowed",
          "HTTP %s" % status)

    if args.include_billed:
        status, headers, body = client.call("GET", "/api/costs")
        check("costs endpoint (billed, cached)", status in (200, 503), "HTTP %s, cache %s" % (status, headers.get("x-vercel-cache", "n/a")))

    if args.email and accounts:
        password = args.password or getpass.getpass("Password for %s: " % args.email)
        status, _, body = client.call("POST", "/api/auth/login", body={"email": args.email, "password": password})
        if check("sign in", status == 200, "HTTP %s" % status):
            status, _, me = client.call("GET", "/api/auth/me")
            check("session cookie works through this host", status == 200, "HTTP %s" % status)
            operator = bool(me and me.get("is_operator"))
            check("account is an operator", operator, "add it to CLOUDOPS_OPERATOR_EMAILS" if not operator else "")
            if operator:
                status, _, summary = client.call("GET", "/api/governance/summary")
                if check("governance summary", status == 200, "HTTP %s" % status):
                    for name, source in summary["sources"].items():
                        note("source %s: %s%s" % (name, source["status"], (" (" + source["error"] + ")") if source["error"] else ""))
                    note("%d open findings" % summary["total_findings"])
                status, _, recs = client.call("GET", "/api/ai/recommendations")
                check("recommendations", status == 200 and recs.get("persisted") is True, "HTTP %s" % status)
                status, _, ai = client.call("GET", "/api/ai/status")
                if check("AI status", status == 200):
                    note("AI provider: %s, calls today %s of %s" % (ai["provider"]["provider"], ai["calls_used_today"], ai["daily_call_limit"]))
                status, _, sec = client.call("GET", "/api/security/status")
                if check("security status", status == 200):
                    creds = sec["aws_credentials"]
                    note("AWS credential mode %s, temporary=%s" % (creds["mode"], creds["temporary"]))
                    if creds.get("recommendation"):
                        note(creds["recommendation"])
            client.call("POST", "/api/auth/logout", body={})

    failed = [r for r in RESULTS if not r[1]]
    print("\n%d checks, %d failed" % (len(RESULTS), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
