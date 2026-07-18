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

4. Collect the first requested favorite `video` or `note` links from the authenticated page. Keep `note` links only so their position can be recorded; `note`/image-text items must be skipped before detail capture or media processing. Use `references/browser-extraction.md` and save:

```bash
Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json
```

5. Run the CDP detail-capture path first. Ask for approval to start an isolated debuggable Chrome; do not read existing Chrome cookies unless the user separately and explicitly approves that cookie access:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir="/Users/Admin/Documents/Obsidian Vault/.tmp/douyin-cdp-profile" \
  "https://www.douyin.com/"
```

If the isolated Chrome profile is logged out, show the browser and let the user log in manually. If Douyin shows CAPTCHA, slider verification, QR confirmation, SMS/OTP, or another challenge, stop and wait for the user to complete it manually.

After launching isolated Chrome, wait 3 seconds and inspect its page titles or visible state. If a Douyin verification page (for example, a `verifycenter` CAPTCHA/slider/QR/SMS/OTP prompt) is still active and blocks the authenticated session, show the Chrome window and clearly tell the user that manual verification is required before continuing. Otherwise continue automatically. A stale verification tab may remain after authenticated detail capture succeeds; do not request another manual verification unless a challenge actually blocks capture.

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

6. Process captured details into local media, local transcripts, staging draft notes, and the canonical manifest. `note`/image-text records should remain `skipped_note` and must not produce media, transcripts, or staging notes:

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

7. If the CDP path is unavailable or does not produce usable detail JSON/media for non-entertainment items, fall back to the normal `yt-dlp` path:

```bash
python3 "Codex Skills/dy-faves-puller/scripts/process_favorites.py" \
  --input "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --limit 10
```

If this produces local media and transcripts, keep the manifest as the pull output. Do not run a summary model in this skill.

8. If the `yt-dlp` fallback reports that fresh cookies are needed, ask for explicit permission before reading browser cookies. After approval, retry with a browser profile already logged in to Douyin:

```bash
python3 "Codex Skills/dy-faves-puller/scripts/process_favorites.py" \
  --input "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/favorites_urls.json" \
  --output "Wiki Library/raw/originals/douyin" \
  --manifest "Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json" \
  --limit 10 \
  --cookies-from-browser chrome
```

If this still fails to produce local MP4 files for non-entertainment video items, report the unresolved items instead of creating summaries from page titles or visible text.

9. If CDP login is unavailable and the user explicitly prefers cookie export, ask for approval to export existing Chrome Douyin cookies:

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

10. Verify the local-source pull:

```bash
python3 - <<'PY'
import json, pathlib, subprocess
m = json.load(open("Wiki Library/raw/originals/douyin/pulls/<pull-id>/json/run_manifest.json", encoding="utf-8"))
for item in m:
    if item.get("status") in {"skipped_entertainment", "skipped_note"}:
        if item.get("video") or item.get("audio") or item.get("transcript"):
            raise SystemExit(f"Entertainment item has media assets: {item.get('index')}")
        continue
    if item.get("status") not in {"ok", "note_only", "already_processed", "skipped_note"}:
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

11. Report the manifest path and stop. If the user wants summaries next, invoke `review-summarizer` with that manifest.

## Progress Updates

For long media download, audio extraction, and transcription runs, report progress about every 30 seconds. Base progress on local file counts, directory sizes, and manifest status counts; do not print signed URLs, cookies, or raw download commands. If command output is silenced to avoid leaking signed URLs, say so. When progress appears stalled, infer the bottleneck from local artifacts first: MP4 only means audio extraction may still be pending; MP4+WAV without a transcript usually means transcription is running or stuck; transcript without a manifest update usually means writeback is pending. If one long video blocks later items, continue the later items with `--indices`, `--merge-manifest`, and `--keep-success`.

## Complete Transcripts

Full transcription is the default output; capped transcripts are not final. Use `--transcribe-max-ms 0`, or run `whisper-cli` directly on the full WAV. Only create a capped transcript as a temporary measure when a long video blocks the whole batch; clearly mark it as partial and later rerun full transcription. If a partial transcript already exists, rename it with a suffix such as `.partial-180s.txt` before retrying, because the processing script reuses existing non-empty transcript files. After completion, verify that the final transcript reaches the end of the video, and update any run report that previously described the item as partially transcribed.

## Rules

- Douyin `note`/image-text items are skipped before detail capture or media download. Record them as `skipped_note`; do not create local media, transcripts, or staging notes for them.
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
