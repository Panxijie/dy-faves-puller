---
name: dy-faves-puller
description: Fetch a logged-in Douyin user's favorite or collection items into local Wiki Library source materials. Use when Codex needs to open the authenticated Douyin favorites page, collect current favorite URLs, capture detail JSON, download local videos/images/audio, transcribe locally when possible, and write pull manifests under `Wiki Library/raw/originals/douyin/`. This skill does not call a summary model or write final review notes; use `review-summarizer` afterward for model-generated candidate summaries.
---

# DY Faves Puller

## Overview

Pull Douyin favorites into local source files. This skill stops at local evidence: URLs, detail JSON, downloaded media, audio, transcripts, staging draft notes when scripts need them, registry records, and `run_manifest.json`.

Do not use this skill to generate model-written summaries, organize notes into `raw/review/current/`, or promote anything into `Wiki Library/wiki/`. After a pull is complete, hand the manifest to `review-summarizer` if the user wants candidate review summaries.

## Output Boundary

This skill writes only under:

- `Wiki Library/raw/originals/douyin/pulls/<pull-id>/`: pull record, `run_report.md`, `favorites_urls.json`, `run_manifest.json`, capture manifests, cookies files when explicitly approved, and per-item detail JSON.
- `Wiki Library/raw/originals/douyin/assets/`: stable local source assets when already organized by a previous pass.
- `Wiki Library/raw/originals/douyin/downloads/`, `audio/`, `transcripts/`, `details/`, `notes/`: staging folders used during capture and transcription.
- `Wiki Library/raw/originals/douyin/registry/`: processed ID registry and review event records.

It must not write candidate summaries to `Wiki Library/raw/review/current/`. Staging files under `raw/originals/douyin/notes/` are extraction artifacts for later summarization, not human review notes.

## Workflow

1. Open `https://www.douyin.com/user/self?showTab=favorite_collection` in the in-app browser.
2. If the page is logged out, show the browser and ask the user to scan/login. If Douyin shows CAPTCHA, slider verification, QR confirmation, SMS/OTP, or another challenge, stop and wait for the user to complete it manually.
3. Record the pull start time to the minute as `YYYY-MM-DD_HH-mm`. Create:

```bash
Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/
```

4. Collect the first requested favorite `video` or `note` links from the authenticated page. Use `references/browser-extraction.md` and save:

```bash
Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json
```

5. Run the normal `yt-dlp` path first:

```bash
python3 "Codex Skills/dy-faves-puller/scripts/process_favorites.py" \
  --input "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --limit 10
```

If this produces local media and transcripts, keep the manifest as the pull output. Do not run a summary model in this skill.

6. If `yt-dlp` reports that fresh cookies are needed, ask for explicit permission before reading browser cookies. After approval, retry with a browser profile already logged in to Douyin:

```bash
python3 "Codex Skills/dy-faves-puller/scripts/process_favorites.py" \
  --input "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --limit 10 \
  --cookies-from-browser chrome
```

If this still fails to produce local MP4 files for non-entertainment video items, continue to the CDP fallback.

7. For the CDP fallback, first ask for approval to export existing Chrome Douyin cookies:

```bash
yt-dlp \
  --cookies-from-browser chrome \
  --cookies "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/douyin-cookies.txt" \
  --skip-download \
  "https://www.douyin.com/"
```

Treat the export as usable only if the cookie file exists and is non-empty. Do not print cookies.

Then ask for approval to start an isolated debuggable Chrome:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir="/Users/Admin/Documents/Obsidian Vault/.tmp/douyin-cdp-profile" \
  "https://www.douyin.com/"
```

If an exported cookie file exists, inject it:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/inject_cookies_cdp.py" \
  --cookies "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/douyin-cookies.txt" \
  --port 9222 \
  --url "https://www.douyin.com/"
```

Capture detail JSON:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/cdp_capture_details.py" \
  --favorites "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json" \
  --output-dir "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/cdp-details" \
  --port 9222 \
  --timeout 45 \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/cdp-capture-manifest.json"
```

If sandboxing blocks `127.0.0.1:9222`, rerun the same command with escalated permission. Do not print signed URLs.

8. Process captured details into local media, local transcripts, staging draft notes, and the canonical manifest:

```bash
printf '# Netscape HTTP Cookie File\n' \
  > "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/empty-cookies.txt"
PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves-puller/scripts/process_signed_details.py" \
  --signed-details "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/cdp-capture-manifest.json" \
  --cookies "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/empty-cookies.txt" \
  --output "Wiki Library/raw/originals/douyin" \
  --model "Wiki Library/raw/originals/douyin/models/ggml-base.bin" \
  --transcribe-max-ms 0 \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --merge-manifest \
  --keep-success
```

Use `--max-workers` or sub-agent sharding only for the local download/transcription stage. Workers should write shard manifests, and the parent should merge them into the canonical `run_manifest.json`.

9. Verify the local-source pull:

```bash
python3 - <<'PY'
import json, pathlib, subprocess
m = json.load(open("Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json", encoding="utf-8"))
for item in m:
    if item.get("status") == "skipped_entertainment":
        if item.get("video") or item.get("audio") or item.get("transcript"):
            raise SystemExit(f"Entertainment item has media assets: {item.get('index')}")
        continue
    if item.get("status") not in {"ok", "note_only", "already_processed"}:
        raise SystemExit(f"Unresolved item status: {item.get('index')} {item.get('status')}")
    video_value = item.get("video")
    if item.get("content_type") != "note" and video_value:
        video = pathlib.Path(video_value)
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=nw=1", str(video)],
            capture_output=True, text=True, check=True,
        )
        print(item["index"], video.name)
        print(result.stdout.strip())
print("Douyin local pull verified.")
PY
```

10. Report the manifest path and stop. If the user wants summaries next, invoke `review-summarizer` with that manifest.

## Rules

- Entertainment items are skipped before media download unless the user explicitly asks to keep them. Examples: `相声`, `曲艺`, `影视`, `美剧`, `电影`, `剧集`, `追剧`, `综艺`, `脱口秀`, `说唱`, `音乐`, `歌曲`, `MV`, `演出`.
- The captured detail JSON is the canonical source for statistics, tags, duration, source URL, aweme ID, source title, and media URLs.
- Do not create final notes from page titles or visible page text alone.
- Do not call `summarize_notes_with_model.py`, `organize_content_library.py`, or any chat-completion summary API from this skill.
- Do not promote review notes into `Wiki Library/wiki/` from this skill.
- Keep cookies and signed URLs private. Never print them.
- Start debuggable Chrome only after explicit user approval, use an isolated temporary profile, close it after capture, and delete the temporary profile only after the user approves cleanup.
- Respect platform terms and the user's account boundaries. Only process videos from the user's authenticated session and local files requested by the user.

## Required Tools

- In-app browser access for the authenticated Douyin favorites page.
- `yt-dlp` for video metadata, subtitles, and media download.
- `ffmpeg` and `ffprobe` for audio extraction and media validation.
- Python `requests` and `websocket-client` packages for CDP detail capture.
- Optional local `whisper-cli` plus a GGML model for offline transcription.

## Next Step

After this skill produces a verified `run_manifest.json`, use:

```bash
python3 "Codex Skills/review-summarizer/scripts/summarize_notes_with_model.py" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json"
```

or simply ask Codex to use `review-summarizer` for the manifest.
