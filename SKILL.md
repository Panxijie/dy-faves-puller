---
name: dy-faves2notes
description: Fetch a logged-in Douyin user's favorite/collection videos, save the first N video URLs, download each video, extract subtitles or audio transcript, summarize the content, and write Markdown notes. Use when Codex needs to automate Douyin favorites, collections, liked videos, or private logged-in Douyin video lists into local Markdown/Obsidian notes.
---

# DY Faves2Notes

## Overview

Automate a logged-in Douyin favorites workflow into local Markdown notes. The skill uses the in-app browser to collect the user's current favorite URLs, downloads real local video resources, extracts audio, transcribes locally when possible, and creates one `.md` summary per item.

When the user asks to "总结前 10 条收藏视频", "处理我的收藏", or similar, treat it as a request to fetch the current Douyin favorites page again. Do not summarize an old `拉取记录` unless the user explicitly asks to use an existing pull record.

Do not fall back to page-title-only or visible-page-text-only summaries when the user asked for favorite videos. A correct run must produce local video files for the target videos, then summarize from transcript/audio/video-derived content. Page text is only auxiliary metadata.

Entertainment items are different: if metadata/title/tags indicate `影音与娱乐`, skip them before media download and record `skipped_entertainment`. Examples include `相声`, `曲艺`, `影视`, `美剧`, `电影`, `剧集`, `追剧`, `综艺`, `脱口秀`, `说唱`, `音乐`, `歌曲`, `MV`, and `演出`.

The workflow is not complete when transcription finishes. A complete run must also rewrite draft notes into structured Chinese summaries, organize notes and assets into `笔记库/` and `素材库/`, and rebuild `Douyin Favorites/笔记索引.md`.

## Workflow

1. Open `https://www.douyin.com/user/self?showTab=favorite_collection` in the in-app browser.
2. If the page is logged out, show the browser and ask the user to scan/login. If Douyin opens a verification/challenge page after login or cookie injection, for example CAPTCHA, slider verification, QR confirmation, SMS/OTP prompt, or other risk-control check, stop and tell the user that manual verification is needed. Resume only after the user says verification is complete. Do not enter passwords, OTPs, or solve CAPTCHAs without explicit action-time confirmation.
3. Record the pull start time to the minute as `YYYY-MM-DD_HH-mm`. Create `Douyin Favorites/拉取记录/<pull-id>/json/`.
4. Collect the first 10 currently visible favorite `video` or `note` links from the authenticated page. Use `references/browser-extraction.md` and save the array as `Douyin Favorites/拉取记录/<pull-id>/json/favorites_urls.json`.
5. Run the normal `yt-dlp` path first. It handles public/simple cases and creates the first manifest:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/process_favorites.py" \
  --input "Douyin Favorites/拉取记录/<pull-id>/json/favorites_urls.json" \
  --output "Douyin Favorites" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --limit 10
```

6. If `yt-dlp` reports that fresh cookies are needed, ask for explicit permission before reading browser cookies. After approval, retry with a normal browser profile that is already logged in to Douyin:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/process_favorites.py" \
  --input "Douyin Favorites/拉取记录/<pull-id>/json/favorites_urls.json" \
  --output "Douyin Favorites" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --limit 10 \
  --cookies-from-browser chrome
```

If this still returns `Fresh cookies are needed` or fails to produce local MP4 files, continue to the CDP fallback. Do not answer from the fallback notes produced by `process_favorites.py` when their status is `download_failed`; those notes are placeholders.

7. Use the detail-JSON/CDP fallback. This is the reliable path for Douyin favorites that render in the browser but block `yt-dlp`.

Ask for explicit approval to start a temporary debuggable Chrome with an isolated profile. To avoid asking the user to scan/login again, first ask for approval to read existing Chrome Douyin cookies. If approved, export them to the pull record:

```bash
yt-dlp \
  --cookies-from-browser chrome \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/douyin-cookies.txt" \
  --skip-download \
  "https://www.douyin.com/"
```

`yt-dlp` may still end with `Unsupported URL` for the Douyin homepage after exporting cookies. Treat the export as usable only if the cookie file exists and is non-empty; do not treat a non-zero exit alone as proof that export failed.

Do not print the cookie file. Keep it inside the pull record and delete it after the workflow only if the user approves cleanup.

Then start the isolated debuggable Chrome:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --remote-allow-origins=http://127.0.0.1:9222 \
  --user-data-dir="/Users/Admin/Documents/Obsidian Vault/.tmp/douyin-cdp-profile" \
  "https://www.douyin.com/"
```

If an exported cookie file exists, inject those cookies into the isolated Chrome session before capture:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves2notes/scripts/inject_cookies_cdp.py" \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/douyin-cookies.txt" \
  --port 9222 \
  --url "https://www.douyin.com/"
```

If cookie export or injection is unavailable, or if the temporary profile is still logged out after injection, show the Chrome window and ask the user to log in manually. If the temporary profile reaches a Douyin verification/challenge page instead of the favorites page, stop and tell the user to complete verification in that visible Chrome window, then continue only after the user confirms it is done. Once the temporary browser is authenticated, capture detail JSON for all 10 current favorites:

```bash
PYTHONPATH=".tmp/pydeps" PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves2notes/scripts/cdp_capture_details.py" \
  --favorites "Douyin Favorites/拉取记录/<pull-id>/json/favorites_urls.json" \
  --output-dir "Douyin Favorites/拉取记录/<pull-id>/json/cdp-details" \
  --port 9222 \
  --timeout 45 \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/cdp-capture-manifest.json"
```

If sandboxing blocks `127.0.0.1:9222` with `Operation not permitted`, rerun the same command with escalated permission. Do not print cookies or signed URLs.

8. Process the captured detail bodies into local videos, audio, transcripts, draft notes, and a corrected manifest. `process_signed_details.py` must classify each detail JSON before downloading media; entertainment items should become `skipped_entertainment` with no video/audio/transcript asset. The script requires a Netscape cookies file argument even when the captured signed media URLs do not need cookies; create a non-sensitive empty file inside the pull record:

```bash
printf '# Netscape HTTP Cookie File\n' \
  > "Douyin Favorites/拉取记录/<pull-id>/json/empty-cookies.txt"
PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves2notes/scripts/process_signed_details.py" \
  --signed-details "Douyin Favorites/拉取记录/<pull-id>/json/cdp-capture-manifest.json" \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/empty-cookies.txt" \
  --output "Douyin Favorites" \
  --model "Douyin Favorites/models/ggml-base.bin" \
  --transcribe-max-ms 0 \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --merge-manifest \
  --keep-success
```

If media download fails with the empty cookie file, ask before exporting/using a real Netscape cookie file and rerun with `--cookies "Douyin Favorites/douyin-cookies.txt"`.

9. Verify resources before summarizing:

```bash
python3 - <<'PY'
import json, pathlib, subprocess
m = json.load(open("Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json", encoding="utf-8"))
for item in m:
    video = pathlib.Path(item["video"])
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=nw=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    print(item["index"], video.name)
    print(result.stdout.strip())
PY
```

All non-entertainment target video items must have valid local MP4 paths in `run_manifest.json`. Entertainment items should have `status: "skipped_entertainment"` and no local media. If any non-entertainment item lacks a video, fix the download/capture first instead of summarizing page text.

10. Read the complete transcript paths listed in `run_manifest.json`, not stale similarly named files from earlier failed attempts. Rewrite the draft notes from transcript content and save the rewritten Markdown back to each manifest item's `note` path before organizing:

- `## 摘要`: one concise orientation paragraph of 50 Chinese characters or fewer.
- `## 详细内容`: follow the video's order and retain reasoning, intermediate steps, demonstrations, examples, names, numbers, settings, and comparisons.
- Topic-specific sections such as tools, procedures, arguments, or cases when they improve scanning.
- `## 注意事项`: separate the video's claims from verified facts and note uncertainty or transcription ambiguity.

Entertainment/music items should not be downloaded or summarized unless the user explicitly asks to keep entertainment assets. Non-entertainment visual/lifestyle items may be downloaded and summarized when they contain informational guidance; if the transcript is weak, note the uncertainty.

Do not optimize for the shortest possible note. For ordinary informational videos, make the detailed section substantial enough to reconstruct the main content without replaying the video. For long tutorials, preserve every major chapter and actionable step.

After rewriting, verify that each kept note has real Chinese sections, not the script's extractive fallback headings such as `## Summary`, `## Notes`, or `## 内容脉络（自动提取）`.

11. Preview organization, fix any bad auto-classification or overlong filenames if needed, then apply:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/organize_content_library.py" \
  --output "Douyin Favorites" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM"
python3 "Codex Skills/dy-faves2notes/scripts/organize_content_library.py" \
  --output "Douyin Favorites" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json" \
  --pulled-at "YYYY-MM-DD HH:MM" \
  --apply
```

Close the temporary Chrome session after capture and processing. Delete `.tmp/douyin-cdp-profile` only after the user approves cleanup.

12. Verify completion:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/update_note_index.py" \
  --output "Douyin Favorites" \
  --check-titles
python3 - <<'PY'
import pathlib, re
for path in sorted(pathlib.Path("Douyin Favorites/笔记库").glob("*/*.md")):
    text = path.read_text(encoding="utf-8")
    if "## Summary" in text or "## 内容脉络（自动提取）" in text:
        raise SystemExit(f"Draft fallback remains: {path}")
    match = re.search(r"^## 摘要\s*$([\s\S]*?)(?=^##\s+|\Z)", text, re.M)
    if not match:
        raise SystemExit(f"Missing summary section: {path}")
    summary = " ".join(match.group(1).split())
    if len(summary) > 50:
        raise SystemExit(f"Summary too long ({len(summary)}): {path}")
print("Note library summaries verified.")
PY
```

Only report completion after the index check passes and the new/updated notes are present in `Douyin Favorites/笔记库/`.

After summaries are finalized, write notes and local source assets separately:

- Put Markdown notes under `Douyin Favorites/笔记库/<category>/<pull-date>-<category-sequence>-<summary-title>.md`.
- Put videos, images, audio, and transcript files flat under `Douyin Favorites/素材库/`, without category subfolders.
- Add a `## 本地文件` section to every note with relative Markdown links to the local video or image, transcript, and audio when those files exist.

Reset the sequence to 1 for each broad category on each new date, and continue from the largest existing sequence in that same category when multiple pulls occur on the same date. Use one broad `category` and one narrower `subcategory`: `技术与工具`, `科研与学习`, `情感与关系`, `影音与娱乐`, `生活与职场`, or `待分类`.

Use the same YAML property schema for every note, in this order:

`source_url`, `created_at`, `content_type`, `original_title`, `category`, `subcategory`, `pulled_at`, `category_sequence`, `duration`, `likes`, `comments`, `favorites`, `shares`, `tags`.

Keep missing values as explicit `null` and missing tag lists as `[]` so every note has the same property keys. Do not store `title` because the note title already appears in the filename. Do not store `pull_date` because `pulled_at` includes the date. Do not store `video_path`, `image_path`, `audio_path`, `transcript_path`, or `detail_json` in YAML; local media links belong only in `## 本地文件`, and detail JSON remains discoverable from the pull record manifest.

Move the run report and JSON records into `Douyin Favorites/拉取记录/<YYYY-MM-DD_HH-mm>/`. Keep `run_report.md` at the record root; put `run_manifest.json`, `favorites_urls.json`, `note-extracts.json`, and per-item detail JSON files under its `json/` directory.

Maintain `Douyin Favorites/拉取记录/aweme_ids.txt` as the global processed-ID registry, with one `aweme_id` per line. Add IDs after an item is successfully summarized, saved as note-only, or intentionally skipped as entertainment. Use this file for duplicate detection before any media download in future pulls.

The apply pass rebuilds `Douyin Favorites/笔记索引.md` from the current `Douyin Favorites/笔记库/**/*.md` tree after organization finishes. The index is always derived from the current note library, not just the latest manifest, so added, deleted, moved, or renamed notes are reflected on the next organization/index pass. Titles in the index come from current note filenames; summaries come directly from each note's `## 摘要` section. Do not truncate summaries while building the index; if a note summary exceeds 50 Chinese characters, rewrite that note's `## 摘要` first. When checking whether the index matches the current note library, compare only the title list derived from note filenames against the index title column; do not compare summaries, subcategories, or links as freshness signals.

To update only the index after manual note-library changes, run:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/update_note_index.py" --output "Douyin Favorites"
```

To check whether the existing index titles match the current note library without rewriting the index, run:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/update_note_index.py" --output "Douyin Favorites" --check-titles
```

Name notes as `<YYYY-MM-DD>-<two-digit category sequence>-<summary title>.md`. Do not use the raw Douyin title directly as the filename. After summarizing the content, choose a concise, descriptive note title and store the source title as `original_title`. Remove leading engagement counts and hashtags from filenames. Use `video` or `note` for `content_type`, without the `douyin_` prefix. Store engagement metadata in YAML properties as compact readable values: keep counts below 1w as integers, and format counts of 1w or more with `w` as the ten-thousand unit, such as `1.2w` or `28.5w`. Use explicit `null` for unavailable scalar properties instead of omitting the key. Store `duration` as human-readable Chinese text such as `2 分钟 31 秒` or `1 小时 4 分钟 8 秒`, not milliseconds.

To migrate notes created by an older version, preview and then apply:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/migrate_note_names.py" --output "Douyin Favorites"
python3 "Codex Skills/dy-faves2notes/scripts/migrate_note_names.py" --output "Douyin Favorites" --apply
```

## Required Tools

- `yt-dlp` for video metadata, subtitles, and media download.
- `ffmpeg` for audio extraction.
- `ffprobe` for deriving human-readable video duration when metadata is missing.
- In-app browser access for the authenticated Douyin favorites page.
- Python `requests` and `websocket-client` packages for the CDP detail-capture fallback.

Optional:

- `OPENAI_API_KEY` plus the explicit script flag `--use-openai` for OpenAI audio transcription and Markdown summarization. Never use `--use-openai` unless the user has approved uploading downloaded audio/transcript text to OpenAI. The script uses `gpt-4o-mini-transcribe` for audio and `gpt-4.1` for summaries by default; override with `OPENAI_TRANSCRIBE_MODEL` and `OPENAI_SUMMARY_MODEL`.
- Local `whisper-cli` from `whisper-cpp` plus a GGML model for offline transcription.

## Output Layout

`Douyin Favorites/` contains:

- `笔记索引.md`: category-grouped index of kept notes. For each note, list title, subcategory, a content summary of 50 Chinese characters or fewer without ellipses, and a relative Markdown link to the note.
- `笔记库/`: user-facing topic categories. Each category contains only Markdown notes.
- `素材库/`: flat local source assets, including videos, images, audio, and transcript text. Notes link to these files with relative Markdown links.
- `拉取记录/aweme_ids.txt`: global processed-ID registry, one aweme ID per line.
- `拉取记录/<YYYY-MM-DD_HH-mm>/`: one pull's `run_report.md` and `json/` records, including per-item detail JSON.
- `downloads/`, `audio/`, `transcripts/`, and `details/`: temporary staging folders before organization. After a clean organization pass, these should normally be empty or absent.

## Failure Handling

- If Douyin shows a login prompt, stop collection and ask the user to log in in the visible browser.
- If Douyin shows a verification/challenge page, stop collection and ask the user to complete that verification in the visible browser before retrying the same capture step.
- If extraction returns fewer than 10 links, scroll the favorites grid and rerun the extraction snippet.
- If an item's `aweme_id` is already in `拉取记录/aweme_ids.txt`, skip it entirely with `status: "already_processed"`.
- If the user asked to download/summarize the current first N favorite videos, download video resources for all non-entertainment target video items before writing the final answer.
- Always classify `影音与娱乐` before media download and keep only a manifest record with `status: "skipped_entertainment"` unless the user explicitly asks to preserve entertainment assets too.
- If `yt-dlp` cannot download a private/favorite video, keep the URL and metadata in the manifest. If the log says fresh cookies are needed, request explicit user approval before reading/exporting cookies and prefer `--cookies-from-browser chrome` or another browser profile that is logged in to Douyin.
- If no subtitle/transcript exists and no transcription backend is configured, still keep the downloaded video/audio asset, create a Markdown note with metadata and local media links, and clearly state that transcription is unavailable.
- Signed Douyin detail URLs are fragile. Use only exact `aweme_id` matches and process them immediately after the browser observes them. A `200` response with zero bytes means the URL/signature is unusable outside that browser context and must be refreshed or collected from a debuggable browser session.
- If CDP starts after the detail response has already completed, reuse the loaded tab and refetch the signed detail resource from `performance` entries inside that authenticated page context. Keep the signed URL out of logs.
- Start the debuggable Chrome session only after explicit user approval. Use an isolated temporary profile, avoid printing cookies or signed URLs, close Chrome when capture finishes, and delete the temporary profile after the workflow completes if the user approved cleanup.
- Treat `--use-openai` as a data-transfer action. It can send audio and transcript content from the user's Douyin favorites to OpenAI, so require explicit user approval before running it.
- Respect platform terms and the user's account boundaries. Only process videos from the user's authenticated session and local files requested by the user.
