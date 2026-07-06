#!/usr/bin/env python3
"""Download a Douyin video from an aweme/detail JSON response."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:80] or fallback).strip("-._")


def first_url(obj: dict, *paths: str) -> str:
    for path in paths:
        current = obj
        for part in path.split("."):
            if isinstance(current, dict):
                current = current.get(part)
            else:
                current = None
                break
        if isinstance(current, dict):
            urls = current.get("url_list") or []
            if urls:
                return urls[0]
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--detail-json", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--index", default=1, type=int)
    parser.add_argument("--cookies", type=Path)
    args = parser.parse_args()

    data = json.loads(args.detail_json.read_text(encoding="utf-8"))
    aweme = data.get("aweme_detail") or {}
    video = aweme.get("video") or {}
    title = aweme.get("desc") or aweme.get("share_info", {}).get("share_title") or aweme.get("aweme_id") or "douyin-video"
    url = first_url(video, "download_addr", "play_addr", "play_addr_h264")
    if not url:
        raise SystemExit("No playable URL found in detail JSON.")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    out = args.output_dir / f"{args.index:02d}-{slugify(title, 'douyin-video')}.mp4"
    cmd = [
        "curl",
        "-L",
        "--fail",
        "--compressed",
        "-A",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
        "-e",
        "https://www.douyin.com/",
        "-o",
        str(out),
    ]
    if args.cookies:
        cmd[1:1] = ["-b", str(args.cookies)]
    cmd.append(url)
    subprocess.run(cmd, check=True)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
