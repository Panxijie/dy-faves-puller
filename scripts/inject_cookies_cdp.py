#!/usr/bin/env python3
"""Inject exported Douyin cookies into a temporary debuggable Chrome session."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests
import websocket


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=5)
        self.next_id = 1

    def call(self, method: str, params: dict | None = None, timeout: float = 10) -> dict:
        msg_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}
        raise TimeoutError(method)

    def close(self) -> None:
        self.ws.close()


def new_tab(port: int, url: str) -> dict:
    endpoint = f"http://127.0.0.1:{port}/json/new?{requests.utils.quote(url, safe='')}"
    resp = requests.put(endpoint, timeout=5)
    if not resp.ok:
        resp = requests.get(endpoint, timeout=5)
    resp.raise_for_status()
    return resp.json()


def parse_netscape_cookies(path: Path, domains: list[str]) -> list[dict]:
    cookies: list[dict] = []
    wanted = tuple(domain.lower() for domain in domains)
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line or line.startswith("# Netscape") or line.startswith("# This file"):
            continue
        http_only = False
        if line.startswith("#HttpOnly_"):
            http_only = True
            line = line.removeprefix("#HttpOnly_")
        if line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 7:
            continue
        domain, _include_subdomains, cookie_path, secure, expires, name, value = parts
        clean_domain = domain.lstrip(".").lower()
        if wanted and not any(clean_domain == item or clean_domain.endswith(f".{item}") for item in wanted):
            continue
        cookie: dict = {
            "name": name,
            "value": value,
            "domain": domain,
            "path": cookie_path or "/",
            "secure": secure.upper() == "TRUE",
            "httpOnly": http_only,
        }
        try:
            expiry = int(expires)
            if expiry > 0:
                cookie["expires"] = expiry
        except ValueError:
            pass
        cookies.append(cookie)
    return cookies


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cookies", required=True, type=Path)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--url", default="https://www.douyin.com/")
    parser.add_argument("--domain", action="append", default=["douyin.com"], help="Cookie domain to inject. Repeatable.")
    args = parser.parse_args()

    cookies = parse_netscape_cookies(args.cookies, args.domain)
    if not cookies:
        raise SystemExit("No matching cookies found to inject.")

    tab = new_tab(args.port, "about:blank")
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.call("Network.enable")
        cdp.call("Network.setCookies", {"cookies": cookies}, timeout=15)
        cdp.call("Page.enable")
        cdp.call("Page.navigate", {"url": args.url})
    finally:
        cdp.close()

    domains = sorted({cookie["domain"] for cookie in cookies})
    print(json.dumps({"status": "ok", "cookie_count": len(cookies), "domains": domains, "url": args.url}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
