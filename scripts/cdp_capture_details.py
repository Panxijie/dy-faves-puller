#!/usr/bin/env python3
"""Capture Douyin aweme/detail JSON bodies from a debuggable Chrome session."""

from __future__ import annotations

import argparse
import base64
import json
import re
import time
from pathlib import Path

import requests
import websocket


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:90] or fallback).strip("-._")


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=5)
        self.next_id = 1

    def send(self, method: str, params: dict | None = None) -> int:
        msg_id = self.next_id
        self.next_id += 1
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        return msg_id

    def call(self, method: str, params: dict | None = None, timeout: float = 10) -> dict:
        msg_id = self.send(method, params)
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result") or {}
        raise TimeoutError(method)

    def recv(self, timeout: float = 1) -> dict | None:
        old_timeout = self.ws.gettimeout()
        self.ws.settimeout(timeout)
        try:
            return json.loads(self.ws.recv())
        except Exception:
            return None
        finally:
            self.ws.settimeout(old_timeout)

    def close(self) -> None:
        self.ws.close()


def new_tab(port: int) -> dict:
    url = f"http://127.0.0.1:{port}/json/new?{requests.utils.quote('about:blank', safe='')}"
    resp = requests.put(url, timeout=5)
    if not resp.ok:
        resp = requests.get(url, timeout=5)
    resp.raise_for_status()
    return resp.json()


def existing_tab(port: int, source_url: str) -> dict | None:
    resp = requests.get(f"http://127.0.0.1:{port}/json/list", timeout=5)
    resp.raise_for_status()
    matches = [tab for tab in resp.json() if tab.get("url") == source_url]
    return matches[-1] if matches else None


def capture_one(port: int, item: dict, index: int, output_dir: Path, timeout: int) -> dict:
    source_url = item["url"]
    aweme_id = re.search(r"/(?:video|note)/(\d+)", source_url)
    aweme_id = aweme_id.group(1) if aweme_id else ""
    title = item.get("title") or source_url
    prefix = f"{index:02d}-{slugify(title, f'douyin-{index:02d}')}"
    tab = existing_tab(port, source_url)
    reuse_loaded_tab = bool(tab)
    tab = tab or new_tab(port)
    cdp = CDP(tab["webSocketDebuggerUrl"])
    try:
        cdp.call("Network.enable")
        cdp.call("Page.enable")
        if not reuse_loaded_tab:
            cdp.call("Page.navigate", {"url": source_url})
        deadline = time.time() + timeout
        request_ids: list[str] = []
        body = ""
        while time.time() < deadline and not body:
            msg = cdp.recv(timeout=1)
            if not msg:
                continue
            if msg.get("method") == "Network.responseReceived":
                params = msg.get("params") or {}
                response = params.get("response") or {}
                url = response.get("url") or ""
                if "/aweme/v1/web/aweme/detail/" in url and (not aweme_id or f"aweme_id={aweme_id}" in url):
                    request_ids.append(params.get("requestId"))
            for request_id in list(request_ids):
                if not request_id:
                    continue
                try:
                    result = cdp.call("Network.getResponseBody", {"requestId": request_id}, timeout=2)
                except Exception:
                    continue
                text = result.get("body") or ""
                if result.get("base64Encoded"):
                    text = base64.b64decode(text).decode("utf-8", errors="replace")
                if text.strip():
                    body = text
                    break
        capture_method = "network_detail"
        if not body:
            refetch = cdp.call("Runtime.evaluate", {
                "expression": f"""(async () => {{
                    const urls = performance.getEntriesByType('resource')
                        .map((entry) => entry.name)
                        .filter((url) => url.includes('/aweme/v1/web/aweme/detail/') && url.includes('aweme_id={aweme_id}'))
                        .reverse();
                    for (const url of urls) {{
                        try {{
                            const text = await (await fetch(url, {{credentials: 'include'}})).text();
                            if (text.includes('aweme_detail')) return text;
                        }} catch {{}}
                    }}
                    return '';
                }})()""",
                "awaitPromise": True,
                "returnByValue": True,
            }, timeout=20)
            body = ((refetch.get("result") or {}).get("value") or "")
            if body:
                capture_method = "performance_refetch"
        if not body:
            result = cdp.call("Runtime.evaluate", {
                "expression": """JSON.stringify({
                    title: document.title,
                    videos: Array.from(document.querySelectorAll('video')).map((video) => ({
                        src: video.currentSrc || video.src || '',
                        duration: Number.isFinite(video.duration) ? video.duration : 0
                    }))
                })""",
                "returnByValue": True,
            })
            value = ((result.get("result") or {}).get("value") or "")
            page = json.loads(value) if value else {}
            media = next(
                (video for video in page.get("videos", []) if str(video.get("src", "")).startswith("http")),
                None,
            )
            if not media:
                return {"index": index, "source_url": source_url, "title": title, "status": "missing_detail_body"}
            body = json.dumps({
                "aweme_detail": {
                    "aweme_id": aweme_id,
                    "desc": title,
                    "duration": int(float(media.get("duration") or 0) * 1000),
                    "video": {"play_addr": {"url_list": [media["src"]]}},
                }
            }, ensure_ascii=False)
            capture_method = "dom_video"
        output_dir.mkdir(parents=True, exist_ok=True)
        detail_path = output_dir / f"{prefix}.json"
        detail_path.write_text(body, encoding="utf-8")
        data = json.loads(body)
        ok = bool(data.get("aweme_detail"))
        return {
            "index": index,
            "source_url": source_url,
            "title": title,
            "status": "ok" if ok else "no_aweme_detail",
            "detail_json": str(detail_path),
            "bytes": len(body.encode("utf-8")),
            "capture_method": capture_method,
        }
    finally:
        cdp.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--favorites", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--indices", nargs="*", type=int)
    parser.add_argument("--port", type=int, default=9222)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()

    items = json.loads(args.favorites.read_text(encoding="utf-8"))
    wanted = set(args.indices or range(1, len(items) + 1))
    results = []
    for index, item in enumerate(items, start=1):
        if index not in wanted:
            continue
        print(f"[{index}] {item['url']}", flush=True)
        results.append(capture_one(args.port, item, index, args.output_dir, args.timeout))
        if args.manifest:
            args.manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.manifest:
        args.manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
