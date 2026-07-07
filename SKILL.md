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

Downloads and transcription should run as a pipeline when the implementation supports it: start multiple media downloads concurrently, and as soon as one item finishes downloading, extract audio and enqueue transcription for that item instead of waiting for every download to finish. Keep final note ordering stable by manifest `index`.

## Non-Negotiable Output Contract

For each non-entertainment item with captured detail JSON, the final note must be derived from the downloaded local media/transcript and must preserve the metadata captured from that detail JSON. Do not create final notes by hand from page text, and do not recreate frontmatter from memory.

The captured per-item detail JSON is the canonical source for:

- `likes`, `comments`, `favorites`, `shares` from `aweme.statistics`.
- `tags` from structured `text_extra` hashtags and hashtag text in `desc`.
- `duration` from aweme/video metadata or `ffprobe`.
- `source_url`, `aweme_id`, source title, and media URLs.

After `process_signed_details.py` creates draft notes, treat the draft note frontmatter as data that must be preserved. When rewriting summaries, edit only the Markdown body below the closing `---` unless there is a specific metadata correction from detail JSON. Never replace populated `likes`, `comments`, `favorites`, `shares`, or `tags` with `null` or `[]`.

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

After starting the temporary Chrome, always check its current Douyin page state before asking the user to log in. If the temporary profile is already authenticated, continue directly. If cookie export or injection is unavailable, or if the temporary profile is still logged out after this check, show the Chrome window and ask the user to log in manually. If the temporary profile reaches a Douyin verification/challenge page instead of the favorites page, stop and tell the user to complete verification in that visible Chrome window, then continue only after the user confirms it is done. Once the temporary browser is authenticated, capture detail JSON for all 10 current favorites:

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

8. Process the captured detail bodies into local videos, audio, transcripts, draft notes, and a corrected manifest. `process_signed_details.py` must classify each detail JSON before downloading media; entertainment items should become `skipped_entertainment` with no video/audio/transcript asset.

After all detail JSON has been captured, prefer Codex sub-agents for the expensive per-video work when the environment exposes multi-agent tools. Set a conservative sub-agent cap first, usually `2` or `3`, because local transcription and model summarization are CPU/API-heavy. The parent agent should split disjoint index ranges, give each worker a shard manifest path, and keep final organization/indexing local to the parent. Workers must not share a manifest path and should use `--defer-registry`; the parent merges shard manifests into `run_manifest.json`, updates `aweme_ids.txt`, verifies resources/metadata, then runs the final organization/index pass.

Example worker commands for a sub-agent shard:

```bash
PYTHONPYCACHEPREFIX=".tmp/pycache" python3 \
  "Codex Skills/dy-faves2notes/scripts/process_signed_details.py" \
  --signed-details "Douyin Favorites/拉取记录/<pull-id>/json/cdp-capture-manifest.json" \
  --indices 2 3 4 \
  --cookies "Douyin Favorites/拉取记录/<pull-id>/json/empty-cookies.txt" \
  --output "Douyin Favorites" \
  --model "Douyin Favorites/models/ggml-base.bin" \
  --transcribe-max-ms 0 \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest-agent-1.json" \
  --defer-registry \
  --merge-manifest \
  --keep-success

python3 "Codex Skills/dy-faves2notes/scripts/summarize_notes_with_model.py" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest-agent-1.json"
```

Each worker should report its shard manifest path and any failed indices. The parent agent then merges all `run_manifest-agent-*.json` records into the canonical `run_manifest.json`, preserving stable order by `index`; records from shard manifests should replace matching placeholder/error records from the canonical manifest unless `--keep-success` preserved a prior successful item. Only after merge should the parent append eligible aweme IDs to `拉取记录/aweme_ids.txt`.

If sub-agents are not available, process locally with the normal command. `--max-workers` is available as a fallback local worker cap, but it is not a substitute for Codex sub-agents.

The script requires a Netscape cookies file argument even when the captured signed media URLs do not need cookies; create a non-sensitive empty file inside the pull record:

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

9. Verify local resources and metadata before summarizing. This is a required gate; do not start final note rewriting until it passes.

```bash
python3 - <<'PY'
import json, pathlib, re, subprocess, sys
m = json.load(open("Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json", encoding="utf-8"))
for item in m:
    if item.get("status") == "skipped_entertainment":
        if item.get("video") or item.get("audio") or item.get("transcript"):
            raise SystemExit(f"Entertainment item has media assets: {item.get('index')}")
        continue
    if item.get("status") not in {"ok", "note_only", "already_processed"}:
        raise SystemExit(f"Unresolved item status: {item.get('index')} {item.get('status')}")
    video_value = item.get("video")
    if item.get("content_type") != "note" and not video_value:
        raise SystemExit(f"Missing local video path: {item.get('index')}")
    if not video_value:
        continue
    video = pathlib.Path(video_value)
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration,size", "-of", "default=nw=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    print(item["index"], video.name)
    print(result.stdout.strip())
PY
```

All non-entertainment target video items must have valid local MP4 paths in `run_manifest.json`, except items explicitly marked `manual_deleted` because the user previously removed their note/assets after reading them. Entertainment items should have `status: "skipped_entertainment"` and no local media. If any non-entertainment item lacks a video and is not `manual_deleted`, fix the download/capture first instead of summarizing page text.

Then verify each draft note has the metadata captured in detail JSON:

```bash
PYTHONPATH="Codex Skills/dy-faves2notes/scripts" python3 - <<'PY'
import json, pathlib, re
from note_metadata import stats_from_aweme, tags_from_aweme

manifest = json.load(open("Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json", encoding="utf-8"))

def find_aweme(value, predicate):
    if isinstance(value, dict):
        if predicate(value):
            return value
        for child in value.values():
            found = find_aweme(child, predicate)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_aweme(child, predicate)
            if found:
                return found
    return None

def frontmatter(path):
    text = pathlib.Path(path).read_text(encoding="utf-8")
    if not text.startswith("---\n") or "\n---\n" not in text[4:]:
        raise SystemExit(f"Missing YAML frontmatter: {path}")
    raw = text.split("\n---\n", 1)[0]
    return {m.group(1): m.group(2).strip() for m in re.finditer(r"^([^:\n]+):\s*(.*)$", raw, re.M)}

for item in manifest:
    if item.get("status") != "ok":
        continue
    note = item.get("note")
    detail = item.get("detail_json")
    if not note or not detail:
        raise SystemExit(f"Missing note/detail path: {item.get('index')}")
    data = json.load(open(detail, encoding="utf-8"))
    stats_aweme = find_aweme(data, lambda obj: isinstance(obj.get("statistics"), dict)) or {}
    tags_aweme = find_aweme(data, lambda obj: "text_extra" in obj or "desc" in obj) or {}
    meta = frontmatter(note)
    for key, value in stats_from_aweme(stats_aweme).items():
        if key in {"likes", "comments", "favorites", "shares"} and meta.get(key) in {None, "", "null"}:
            raise SystemExit(f"Missing {key} in note frontmatter: {note}")
    if tags_from_aweme(tags_aweme) and meta.get("tags") in {None, "", "[]"}:
        raise SystemExit(f"Missing tags in note frontmatter: {note}")
print("Draft metadata verified.")
PY
```

10. Read the complete transcript paths listed in `run_manifest.json`, not stale similarly named files from earlier failed attempts. Rewrite only the note body from transcript content and save the rewritten Markdown back to each manifest item's `note` path before organizing. Preserve existing YAML frontmatter from the draft note, including statistics and tags.

By default, use the configurable summary model script rather than Codex hand-written summaries. Unless the user explicitly asks to use Codex/manual summaries or to stay offline, treat this configured model as the default summarizer for final note rewriting.

The model API URL, model name, API key source, and generation parameters come from `Codex Skills/dy-faves2notes/summary_model_config.json`. The fixed summarization requirements live in `Codex Skills/dy-faves2notes/summary_prompt.md`. Future summary style or content-requirement changes should normally be made in `summary_prompt.md`, not improvised by Codex at runtime.

```json
{
  "provider": "openai_compatible",
  "base_url": "https://api.deepseek.com",
  "endpoint": "/chat/completions",
  "api_key_env": "DEEPSEEK_API_KEY",
  "api_key": "",
  "model": "deepseek-v4-pro",
  "prompt_path": "summary_prompt.md",
  "temperature": 0.2,
  "max_tokens": 4096,
  "timeout_seconds": 120
}
```

After transcription and metadata verification pass, run the configured model summarizer:

```bash
python3 "Codex Skills/dy-faves2notes/scripts/summarize_notes_with_model.py" \
  --manifest "Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json"
```

This sends local transcript text and note metadata to the API configured in `summary_model_config.json`; do not print API keys or request/response bodies containing private content. The model-generated note body must still satisfy:

- `## 摘要`: one concise orientation paragraph of 50 Chinese characters or fewer.
- `## 详细内容`: follow the video's order and retain reasoning, intermediate steps, demonstrations, examples, names, numbers, settings, and comparisons.
- Topic-specific sections such as tools, procedures, arguments, or cases when they improve scanning.
- `## 注意事项`: separate the video's claims from verified facts and note uncertainty or transcription ambiguity.
- The model prompt is the fixed text in `summary_prompt.md`; the user prompt should only add per-video metadata and transcript content.

Entertainment/music items should not be downloaded or summarized unless the user explicitly asks to keep entertainment assets. Non-entertainment visual/lifestyle items may be downloaded and summarized when they contain informational guidance; if the transcript is weak, note the uncertainty.

Do not optimize for the shortest possible note. For ordinary informational videos, make the detailed section substantial enough to reconstruct the main content without replaying the video. For long tutorials, preserve every major chapter and actionable step.

After rewriting, verify that each kept note has real Chinese sections, not the script's extractive fallback headings such as `## Summary`, `## Notes`, or `## 内容脉络（自动提取）`. Also rerun the draft metadata verification above; if a body rewrite dropped stats or tags, restore them from detail JSON before organizing.

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
PYTHONPATH="Codex Skills/dy-faves2notes/scripts" python3 - <<'PY'
import json, pathlib, re
from note_metadata import stats_from_aweme, tags_from_aweme

manifest = json.load(open("Douyin Favorites/拉取记录/<pull-id>/json/run_manifest.json", encoding="utf-8"))

def find_aweme(value, predicate):
    if isinstance(value, dict):
        if predicate(value):
            return value
        for child in value.values():
            found = find_aweme(child, predicate)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_aweme(child, predicate)
            if found:
                return found
    return None

def yaml_value(front, key):
    match = re.search(rf"^{re.escape(key)}:\s*(.*)$", front, re.M)
    return match.group(1).strip() if match else None

for item in manifest:
    if item.get("status") != "ok" or not item.get("note"):
        continue
    path = pathlib.Path(item["note"])
    text = path.read_text(encoding="utf-8")
    if "## Summary" in text or "## 内容脉络（自动提取）" in text:
        raise SystemExit(f"Draft fallback remains: {path}")
    match = re.search(r"^## 摘要\s*$([\s\S]*?)(?=^##\s+|\Z)", text, re.M)
    if not match:
        raise SystemExit(f"Missing summary section: {path}")
    summary = " ".join(match.group(1).split())
    if len(summary) > 50:
        raise SystemExit(f"Summary too long ({len(summary)}): {path}")
    front = text.split("\n---\n", 1)[0]
    detail = item.get("detail_json")
    if detail:
        data = json.load(open(detail, encoding="utf-8"))
        stats_aweme = find_aweme(data, lambda obj: isinstance(obj.get("statistics"), dict)) or {}
        tags_aweme = find_aweme(data, lambda obj: "text_extra" in obj or "desc" in obj) or {}
        for key, value in stats_from_aweme(stats_aweme).items():
            if key in {"likes", "comments", "favorites", "shares"} and yaml_value(front, key) in {None, "", "null"}:
                raise SystemExit(f"Missing engagement metadata: {path} {key}")
        if tags_from_aweme(tags_aweme) and yaml_value(front, "tags") in {None, "", "[]"}:
            raise SystemExit(f"Missing tags: {path}")
print("Latest pull notes verified.")
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

If the per-item detail JSON contains `aweme.statistics`, the final note YAML must include non-null `likes`, `comments`, `favorites`, and `shares` values from that structure. Leave these fields as `null` only when the captured detail JSON truly lacks the corresponding statistic. If the detail JSON contains `text_extra` hashtags or hashtags in `desc`, the final note YAML must include those values in `tags`; leave `tags: []` only when no captured hashtag data exists.

Move the run report and JSON records into `Douyin Favorites/拉取记录/<YYYY-MM-DD_HH-mm>/`. Keep `run_report.md` at the record root; put `run_manifest.json`, `favorites_urls.json`, `note-extracts.json`, and per-item detail JSON files under its `json/` directory.

Maintain `Douyin Favorites/拉取记录/aweme_ids.txt` as the global processed-ID registry, with one `aweme_id` per line. Add IDs after an item is successfully summarized, saved as note-only, intentionally skipped as entertainment, or intentionally skipped because it was already processed and later manually deleted by the user. Use this file for duplicate detection before any media download in future pulls.

`aweme_ids.txt` alone is not proof that the note/assets still exist. When an ID is already processed, first look up prior manifests and verify the referenced local note/media files still exist. If they exist, reuse their paths in the current manifest. If they are missing, assume the user deliberately deleted them after reading; mark the item `status: "already_processed"`, `manual_deleted: true`, and do not redownload or regenerate it unless the user explicitly asks to restore deleted items.

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
- A configured OpenAI-compatible summary API in `Codex Skills/dy-faves2notes/summary_model_config.json` for final note rewriting after local transcription. This configured model is the default final summarizer unless the user explicitly asks to use Codex/manual summaries or an offline-only workflow.
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
- If an item's `aweme_id` is already in `拉取记录/aweme_ids.txt`, reuse existing note/assets only if the referenced files still exist. If they are missing, mark it `manual_deleted` and skip it without redownloading.
- If the user asked to download/summarize the current first N favorite videos, download video resources for all non-entertainment target video items before writing the final answer.
- Always classify `影音与娱乐` before media download and keep only a manifest record with `status: "skipped_entertainment"` unless the user explicitly asks to preserve entertainment assets too.
- If `yt-dlp` cannot download a private/favorite video, keep the URL and metadata in the manifest. If the log says fresh cookies are needed, request explicit user approval before reading/exporting cookies and prefer `--cookies-from-browser chrome` or another browser profile that is logged in to Douyin.
- If no subtitle/transcript exists and no transcription backend is configured, still keep the downloaded video/audio asset, create a Markdown note with metadata and local media links, and clearly state that transcription is unavailable.
- Signed Douyin detail URLs are fragile. Use only exact `aweme_id` matches and process them immediately after the browser observes them. A `200` response with zero bytes means the URL/signature is unusable outside that browser context and must be refreshed or collected from a debuggable browser session.
- If CDP starts after the detail response has already completed, reuse the loaded tab and refetch the signed detail resource from `performance` entries inside that authenticated page context. Keep the signed URL out of logs.
- Start the debuggable Chrome session only after explicit user approval. Use an isolated temporary profile, avoid printing cookies or signed URLs, close Chrome when capture finishes, and delete the temporary profile after the workflow completes if the user approved cleanup.
- Treat `--use-openai` as a data-transfer action. It can send audio and transcript content from the user's Douyin favorites to OpenAI, so require explicit user approval before running it.
- Respect platform terms and the user's account boundaries. Only process videos from the user's authenticated session and local files requested by the user.
