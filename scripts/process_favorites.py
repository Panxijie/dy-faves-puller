#!/usr/bin/env python3
"""Download Douyin favorite URLs and produce Markdown summaries."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from douyin_layout import DEFAULT_OUTPUT, assert_current_review_empty
from note_metadata import add_aweme_id, clean_title, extract_aweme_id, load_aweme_ids, render_frontmatter


ALLOW_OPENAI = False
ENTERTAINMENT_RE = re.compile(r"相声|曲艺|影视|美剧|电影|剧集|追剧|综艺|脱口秀|说唱|音乐|歌曲|MV|演出|娱乐", re.I)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise SystemExit(f"Missing required command: {name}")
    return path


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"https?://", "", value)
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE)
    value = value.strip("-._")
    return (value[:80] or fallback).strip("-._")


def load_items(path: Path, limit: int) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("favorites") or raw.get("urls") or []
    items: list[dict] = []
    for entry in raw:
        if isinstance(entry, str):
            items.append({"url": entry})
        elif isinstance(entry, dict) and entry.get("url"):
            items.append(entry)
    return items[:limit]


def is_entertainment_item(*values: object) -> bool:
    return bool(ENTERTAINMENT_RE.search("\n".join(str(value or "") for value in values)))


def newest_matching(directory: Path, prefix: str, patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    for pattern in patterns:
        matches.extend(directory.glob(f"{prefix}*{pattern}"))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def subtitle_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="ignore")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.isdigit():
            continue
        if "-->" in stripped:
            continue
        if stripped.upper() == "WEBVTT":
            continue
        lines.append(stripped)
    return "\n".join(lines)


def extract_audio(video: Path, audio: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-b:a",
        "64k",
        str(audio),
    ]
    run(cmd)


def multipart_body(fields: dict[str, str], file_field: str, file_path: Path) -> tuple[bytes, str]:
    boundary = f"----codex-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode())
        chunks.append(b"\r\n")
    mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    chunks.append(f"--{boundary}\r\n".encode())
    chunks.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_path.name}"\r\n'.encode()
    )
    chunks.append(f"Content-Type: {mime}\r\n\r\n".encode())
    chunks.append(file_path.read_bytes())
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def openai_request(path: str, payload: bytes, content_type: str, api_key: str) -> dict:
    req = urllib.request.Request(
        f"https://api.openai.com{path}",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API error {exc.code}: {body}") from exc


def transcribe_audio(audio: Path) -> str:
    whisper = shutil.which("whisper")
    if whisper:
        output_dir = audio.parent
        run([whisper, str(audio), "--language", "Chinese", "--model", "base", "--output_format", "txt", "--output_dir", str(output_dir)])
        txt = audio.with_suffix(".txt")
        if txt.exists():
            return txt.read_text(encoding="utf-8", errors="ignore").strip()

    api_key = os.environ.get("OPENAI_API_KEY") if ALLOW_OPENAI else ""
    if not api_key:
        return ""
    model = os.environ.get("OPENAI_TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe")
    body, boundary = multipart_body({"model": model, "response_format": "json"}, "file", audio)
    data = openai_request("/v1/audio/transcriptions", body, f"multipart/form-data; boundary={boundary}", api_key)
    return str(data.get("text") or "").strip()


def call_openai_summary(prompt: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY") if ALLOW_OPENAI else ""
    if not api_key:
        return ""
    model = os.environ.get("OPENAI_SUMMARY_MODEL", "gpt-4.1")
    payload = json.dumps(
        {
            "model": model,
            "input": prompt,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    data = openai_request("/v1/responses", payload, "application/json", api_key)
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts).strip() or str(data.get("output_text") or "").strip()


def extractive_summary(transcript: str, title: str) -> str:
    if not transcript:
        return "## 摘要\n\n未获得可用转写。当前笔记需要字幕、本地 Whisper 或经用户批准的 OpenAI 转写后端补全。"
    clean = re.sub(r"\s+", " ", transcript).strip()
    excerpt = clean[:900]
    return textwrap.dedent(
        f"""\
        ## Summary

        {excerpt}

        ## Notes

        - This is an extractive fallback summary because no OpenAI summary backend was configured.
        - Re-run with `OPENAI_API_KEY` to generate a structured summary.
        """
    ).strip()


def markdown_note(item: dict, summary: str, paths: dict[str, str], info: dict) -> str:
    title = clean_title(info.get("description") or info.get("title") or item.get("title") or "", "Douyin video")
    meta = {
        "source_url": item.get("url", ""),
        "title": title,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        **{k: v for k, v in paths.items() if v},
        "likes": info.get("like_count"),
        "comments": info.get("comment_count"),
        "favorites": info.get("collect_count") or info.get("favorite_count"),
        "shares": info.get("repost_count"),
        "tags": info.get("tags") or [],
    }
    return render_frontmatter(meta) + "\n\n" + summary.strip() + "\n"


def process_item(item: dict, index: int, output: Path, cookies: Path | None, cookies_from_browser: str | None) -> dict:
    downloads = output / "downloads"
    transcripts_dir = output / "transcripts"
    notes_dir = output / "notes"
    for directory in (downloads, transcripts_dir, notes_dir):
        directory.mkdir(parents=True, exist_ok=True)

    title = item.get("title") or item.get("desc") or f"douyin-{index:02d}"
    prefix = f"{index:02d}-{slugify(title, f'douyin-{index:02d}')}"
    template = str(downloads / f"{prefix}.%(ext)s")

    aweme_id = extract_aweme_id(item)
    result = {"index": index, "url": item.get("url"), "title": title, "status": "started"}
    if aweme_id:
        result["aweme_id"] = aweme_id
    if aweme_id and aweme_id in load_aweme_ids(output):
        result.update({"status": "already_processed"})
        return result
    if is_entertainment_item(item.get("title"), item.get("desc"), item.get("text")):
        result.update({"status": "skipped_entertainment", "category": "影音与娱乐"})
        add_aweme_id(output, aweme_id)
        return result
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--write-info-json",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs",
        "zh-Hans,zh-CN,zh,en",
        "--convert-subs",
        "srt",
        "--merge-output-format",
        "mp4",
        "-o",
        template,
        item["url"],
    ]
    if cookies:
        cmd[1:1] = ["--cookies", str(cookies)]
    if cookies_from_browser:
        cmd[1:1] = ["--cookies-from-browser", cookies_from_browser]
    try:
        result["download_log"] = run(cmd, check=False).stdout[-4000:]
        video = newest_matching(downloads, prefix, [".mp4", ".webm", ".mkv", ".mov"])
        info_json = newest_matching(downloads, prefix, [".info.json"])
        info = json.loads(info_json.read_text(encoding="utf-8")) if info_json else {}
        aweme_id = extract_aweme_id(info, aweme_id, item.get("url"))
        if aweme_id:
            result["aweme_id"] = aweme_id
        if aweme_id and aweme_id in load_aweme_ids(output):
            result.update({"status": "already_processed"})
            return result
        subtitle = newest_matching(downloads, prefix, [".srt", ".vtt"])
        transcript = subtitle_text(subtitle) if subtitle else ""
        audio = None
        if video:
            audio = downloads / f"{prefix}.mp3"
            extract_audio(video, audio)
            if not transcript:
                transcript = transcribe_audio(audio)
        transcript_path = transcripts_dir / f"{prefix}.txt"
        transcript_path.write_text(transcript, encoding="utf-8")

        prompt = textwrap.dedent(
            f"""\
            Summarize this Douyin video for an Obsidian note in Chinese.
            Write an information-preserving note, not a short abstract. Include: one-sentence gist,
            a chronological detailed account, concrete examples, named tools and parameters,
            important numbers or claims, useful takeaways, caveats, and possible follow-up actions.
            Distinguish claims made by the video from your own inference. Do not omit intermediate
            steps merely to keep the answer short.

            Title: {title}
            URL: {item.get("url")}
            转写文本:
            {transcript[:18000]}
            """
        )
        summary = call_openai_summary(prompt) or extractive_summary(transcript, title)
        note_title = clean_title(info.get("description") or info.get("title") or title, f"douyin-{index:02d}")
        note_prefix = f"{index:02d}-{slugify(note_title, f'douyin-{index:02d}')}"
        note_path = notes_dir / f"{note_prefix}.md"
        note_path.write_text(
            markdown_note(
                item,
                summary,
                {
                    "video_path": str(video) if video else "",
                    "audio_path": str(audio) if audio else "",
                    "info_json": str(info_json) if info_json else "",
                    "transcript_path": str(transcript_path),
                },
                info,
            ),
            encoding="utf-8",
        )
        status = "ok" if video else "download_failed"
        if not video:
            result["error"] = "yt-dlp did not produce a video file; fresh Douyin cookies may be required."
        result.update(
            {
                "status": status,
                "video": str(video) if video else None,
                "audio": str(audio) if audio else None,
                "subtitle": str(subtitle) if subtitle else None,
                "transcript": str(transcript_path),
                "note": str(note_path),
            }
        )
        if status == "ok":
            add_aweme_id(output, aweme_id)
    except Exception as exc:
        result.update({"status": "error", "error": str(exc)})
    return result


def main() -> int:
    global ALLOW_OPENAI
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", default=DEFAULT_OUTPUT, type=Path)
    parser.add_argument("--manifest", type=Path, help="Run manifest path. Defaults to <output>/run_manifest.json.")
    parser.add_argument("--limit", default=10, type=int)
    parser.add_argument("--cookies", type=Path, help="Netscape-format cookies file for yt-dlp.")
    parser.add_argument("--cookies-from-browser", help="Browser profile for yt-dlp, e.g. chrome, safari, edge.")
    parser.add_argument("--use-openai", action="store_true", help="Allow uploading audio/transcript text to OpenAI for transcription/summarization.")
    args = parser.parse_args()
    ALLOW_OPENAI = args.use_openai

    require_tool("yt-dlp")
    require_tool("ffmpeg")
    args.output.mkdir(parents=True, exist_ok=True)
    assert_current_review_empty(args.output)
    items = load_items(args.input, args.limit)
    if not items:
        raise SystemExit("No URLs found in input JSON.")

    manifest = []
    manifest_path = args.manifest or (args.output / "run_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    for index, item in enumerate(items, start=1):
        print(f"[{index}/{len(items)}] {item.get('url')}", flush=True)
        manifest.append(process_item(item, index, args.output, args.cookies, args.cookies_from_browser))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
