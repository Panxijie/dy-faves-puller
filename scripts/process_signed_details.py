#!/usr/bin/env python3
"""Process signed Douyin aweme/detail URLs into local videos, transcripts, and notes."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from note_metadata import (
    add_aweme_id,
    clean_title,
    extract_aweme_id,
    extract_tags,
    leading_metric,
    load_aweme_ids,
    render_frontmatter,
    stats_from_aweme,
    tags_from_aweme,
)


UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
ENTERTAINMENT_RE = re.compile(r"相声|曲艺|影视|美剧|电影|剧集|追剧|综艺|脱口秀|说唱|音乐|歌曲|MV|演出|娱乐", re.I)


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=check)


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:90] or fallback).strip("-._")


def is_entertainment_item(*values: object) -> bool:
    return bool(ENTERTAINMENT_RE.search("\n".join(str(value or "") for value in values)))


def url_from_video(video: dict) -> str:
    for key in ("download_addr", "play_addr", "play_addr_h264"):
        obj = video.get(key)
        if isinstance(obj, dict) and obj.get("url_list"):
            return obj["url_list"][0]
    return ""


def curl_json(url: str, cookies: Path, output: Path, referer: str) -> dict:
    cmd = [
        "curl", "-sS", "-L", "--fail", "--compressed",
        "-A", UA,
        "-e", referer,
        "-b", str(cookies),
        "-o", str(output),
        url,
    ]
    run(cmd)
    text = output.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise RuntimeError("Douyin detail API returned an empty response; refresh the signed detail URL and retry.")
    return json.loads(text)


def load_detail(item: dict, cookies: Path, output: Path, referer: str) -> dict:
    captured = item.get("detail_json")
    if captured:
        source = Path(captured).expanduser()
        if not source.is_absolute():
            source = Path.cwd() / source
        data = json.loads(source.read_text(encoding="utf-8"))
        if not data.get("aweme_detail"):
            raise RuntimeError(f"Captured detail JSON has no aweme_detail: {source}")
        if source.resolve() != output.resolve():
            shutil.copyfile(source, output)
        return data
    signed_url = item.get("signed_detail_url")
    if signed_url:
        return curl_json(signed_url, cookies, output, referer)
    raise RuntimeError("No detail_json or signed_detail_url was provided")


def curl_download(url: str, cookies: Path, output: Path, referer: str) -> None:
    if output.exists() and output.stat().st_size > 1024 * 1024:
        return
    cmd = [
        "curl", "-L", "--fail", "--compressed",
        "-A", UA,
        "-e", referer,
        "-b", str(cookies),
        "-o", str(output),
        url,
    ]
    run(cmd)


def extract_audio(video: Path, audio: Path) -> None:
    if audio.exists() and audio.stat().st_size > 1024:
        return
    run([
        "ffmpeg", "-y", "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(audio),
    ])


def transcribe(audio: Path, transcript_base: Path, model: Path | None, max_ms: int) -> str:
    txt = Path(f"{transcript_base}.txt")
    if txt.exists() and txt.read_text(encoding="utf-8", errors="ignore").strip():
        return txt.read_text(encoding="utf-8", errors="ignore").strip()
    if not model:
        return ""
    cmd = [
        "whisper-cli", "--no-gpu",
        "-m", str(model),
        "-f", str(audio),
        "-l", "zh",
        "-otxt",
        "-of", str(transcript_base),
        "-np",
    ]
    if max_ms > 0:
        cmd[cmd.index("-otxt"):cmd.index("-otxt")] = ["-d", str(max_ms)]
    run(cmd, check=False)
    return txt.read_text(encoding="utf-8", errors="ignore").strip() if txt.exists() else ""


def existing_processed_entry(output: Path, aweme_id: str | None) -> dict | None:
    if not aweme_id:
        return None
    manifests = sorted((output / "拉取记录").glob("*/json/run_manifest.json"), reverse=True)
    for manifest_path in manifests:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in manifest:
            if item.get("aweme_id") != aweme_id or item.get("status") not in {"ok", "note_only", "already_processed"}:
                continue
            required = ["note"]
            if item.get("status") == "ok" and item.get("content_type") != "note":
                required.extend(["video", "transcript"])
            if all(item.get(key) and Path(item[key]).exists() for key in required):
                reused = {key: value for key, value in item.items() if key in {
                    "status", "detail_json", "video", "audio", "transcript", "note", "content_type",
                    "duration", "duration_ms", "note_title", "original_title", "category", "subcategory",
                } and value}
                reused["reused_from_manifest"] = str(manifest_path)
                return reused
    return None


def mark_previously_deleted(result: dict, output: Path, aweme_id: str | None) -> dict:
    reused = existing_processed_entry(output, aweme_id)
    if reused:
        result.update(reused)
        return result
    result.update({
        "status": "already_processed",
        "manual_deleted": True,
        "skip_reason": "aweme_id is marked processed, but local note/assets are missing; treating it as user-deleted and not reprocessing.",
    })
    return result


def simple_summary(title: str, desc: str, transcript: str) -> str:
    clean = re.sub(r"\s+", " ", transcript).strip()
    if clean:
        size = len(clean)
        starts = [0, size // 3, size * 2 // 3]
        excerpts = [clean[start:min(size, start + 700)].strip() for start in starts]
        return (
            "## 摘要\n\n"
            f"这条内容围绕“{desc or title}”。\n\n"
            "## 内容脉络（自动提取）\n\n"
            f"- **开头**：{excerpts[0]}\n"
            f"- **中段**：{excerpts[1]}\n"
            f"- **后段**：{excerpts[2]}\n\n"
            "## 整理状态\n\n"
            "以上覆盖视频开头、中段和结尾；完整转写会作为本地文件保存，并在最终笔记的“本地文件”中链接。由 Codex 执行工作流时，应继续把它改写为信息保真的结构化笔记。\n"
        )
    return (
        "## 摘要\n\n"
        f"这条内容的标题/描述是：{desc or title}\n\n"
        "## 要点\n\n"
        "- 本地未获得可用语音转写，当前摘要基于标题和页面描述。\n"
        "- 视频文件和音频文件已保存，可后续使用更强转写后端补全。\n"
    )


def write_note(path: Path, meta: dict, summary: str, transcript: str) -> None:
    content = render_frontmatter(meta)
    content += "\n\n" + summary.strip()
    path.write_text(content + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--signed-details", required=True, type=Path)
    parser.add_argument("--note-extracts", type=Path)
    parser.add_argument("--cookies", required=True, type=Path)
    parser.add_argument("--output", default=Path("Douyin Favorites"), type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--transcribe-max-ms", type=int, default=180000)
    parser.add_argument("--manifest", type=Path, help="Manifest path. Defaults to <output>/run_manifest.json.")
    parser.add_argument("--merge-manifest", action="store_true", help="Merge results into an existing manifest by index.")
    parser.add_argument("--keep-success", action="store_true", help="Do not replace an existing ok/note_only manifest entry with an error.")
    args = parser.parse_args()

    output = args.output
    processed_aweme_ids = load_aweme_ids(output)
    for name in ("details", "downloads", "audio", "transcripts", "notes"):
        (output / name).mkdir(parents=True, exist_ok=True)

    signed = json.loads(args.signed_details.read_text(encoding="utf-8"))
    note_extracts = {}
    if args.note_extracts and args.note_extracts.exists():
        note_extracts = {item["index"]: item for item in json.loads(args.note_extracts.read_text(encoding="utf-8"))}

    manifest_path = args.manifest or (output / "run_manifest.json")
    manifest = []
    if args.merge_manifest and manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = []
    for item in signed:
        idx = item["index"]
        title = item.get("title") or item.get("source_url") or f"douyin-{idx:02d}"
        item_aweme_id = extract_aweme_id(item)
        prefix = f"{idx:02d}-{slugify(title, f'douyin-{idx:02d}')}"
        result = {"index": idx, "source_url": item.get("source_url"), "title": title}
        if item_aweme_id:
            result["aweme_id"] = item_aweme_id
        print(f"[{idx}] processing", flush=True)
        try:
            if item_aweme_id and item_aweme_id in processed_aweme_ids:
                mark_previously_deleted(result, output, item_aweme_id)
                print(f"[{idx}] already processed", flush=True)
                manifest = [old for old in manifest if old.get("index") != idx]
                manifest.append(result)
                manifest.sort(key=lambda old: old.get("index", 10**9))
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            if not item.get("signed_detail_url") and not item.get("detail_json"):
                note = note_extracts.get(idx, {})
                text = note.get("text", "")
                note_title = clean_title(note.get("title") or title, f"douyin-{idx:02d}")
                if is_entertainment_item(title, note_title, text):
                    result.update({"status": "skipped_entertainment", "category": "影音与娱乐"})
                    add_aweme_id(output, result.get("aweme_id"))
                    processed_aweme_ids = load_aweme_ids(output)
                    manifest = [old for old in manifest if old.get("index") != idx]
                    manifest.append(result)
                    manifest.sort(key=lambda old: old.get("index", 10**9))
                    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                    continue
                note_prefix = f"{idx:02d}-{slugify(note_title, f'douyin-{idx:02d}')}"
                note_path = output / "notes" / f"{note_prefix}.md"
                summary = simple_summary(note_title, note_title, text)
                likes = leading_metric(title)
                write_note(note_path, {
                    "source_url": item.get("source_url"),
                    "title": note_title,
                    "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "content_type": "douyin_note",
                    "likes": likes,
                    "tags": extract_tags(note.get("title") or title),
                }, summary, text)
                result.update({"status": "note_only", "note": str(note_path)})
                add_aweme_id(output, result.get("aweme_id"))
                processed_aweme_ids = load_aweme_ids(output)
                manifest.append(result)
                continue

            detail_path = output / "details" / f"{prefix}.json"
            data = load_detail(item, args.cookies, detail_path, item.get("source_url") or "https://www.douyin.com/")
            aweme = data.get("aweme_detail") or {}
            aweme_id = extract_aweme_id(aweme, item_aweme_id, item.get("source_url"))
            if aweme_id:
                result["aweme_id"] = aweme_id
            if aweme_id and aweme_id in processed_aweme_ids:
                mark_previously_deleted(result, output, aweme_id)
                result.setdefault("detail_json", str(detail_path))
                print(f"[{idx}] already processed", flush=True)
                manifest = [old for old in manifest if old.get("index") != idx]
                manifest.append(result)
                manifest.sort(key=lambda old: old.get("index", 10**9))
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            video = aweme.get("video") or {}
            desc = aweme.get("desc") or title
            note_title = clean_title(desc, f"douyin-{aweme.get('aweme_id') or idx}")
            if is_entertainment_item(title, desc, note_title, tags_from_aweme(aweme)):
                result.update({
                    "status": "skipped_entertainment",
                    "category": "影音与娱乐",
                    "detail_json": str(detail_path),
                    "note_title": note_title,
                })
                add_aweme_id(output, result.get("aweme_id"))
                processed_aweme_ids = load_aweme_ids(output)
                print(f"[{idx}] skipped entertainment", flush=True)
                manifest = [old for old in manifest if old.get("index") != idx]
                manifest.append(result)
                manifest.sort(key=lambda old: old.get("index", 10**9))
                manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            play_url = url_from_video(video)
            if not play_url:
                raise RuntimeError("No video URL in detail JSON")
            video_path = output / "downloads" / f"{prefix}.mp4"
            audio_path = output / "audio" / f"{prefix}.wav"
            transcript_base = output / "transcripts" / prefix
            note_prefix = f"{idx:02d}-{slugify(note_title, f'douyin-{idx:02d}')}"
            note_path = output / "notes" / f"{note_prefix}.md"
            curl_download(play_url, args.cookies, video_path, item.get("source_url") or "https://www.douyin.com/")
            print(f"[{idx}] downloaded", flush=True)
            extract_audio(video_path, audio_path)
            transcript = transcribe(audio_path, transcript_base, args.model, args.transcribe_max_ms)
            print(f"[{idx}] transcribed", flush=True)
            summary = simple_summary(title, desc, transcript)
            write_note(note_path, {
                "source_url": item.get("source_url"),
                "title": note_title,
                "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "content_type": "douyin_video",
                "video_path": video_path,
                "audio_path": audio_path,
                "detail_json": detail_path,
                "transcript_path": Path(f"{transcript_base}.txt"),
                "duration_ms": aweme.get("duration") or video.get("duration"),
                **stats_from_aweme(aweme),
                "tags": tags_from_aweme(aweme),
            }, summary, transcript)
            result.update({
                "status": "ok",
                "aweme_id": result.get("aweme_id"),
                "detail_json": str(detail_path),
                "video": str(video_path),
                "audio": str(audio_path),
                "transcript": str(Path(f"{transcript_base}.txt")),
                "note": str(note_path),
            })
            add_aweme_id(output, result.get("aweme_id"))
            processed_aweme_ids = load_aweme_ids(output)
        except Exception as exc:
            result.update({"status": "error", "error": str(exc)})
            print(f"[{idx}] error: {exc}", flush=True)
        previous = next((old for old in manifest if old.get("index") == idx), None)
        if args.keep_success and previous and previous.get("status") in {"ok", "note_only"} and result.get("status") == "error":
            result = previous
        manifest = [old for old in manifest if old.get("index") != idx]
        manifest.append(result)
        manifest.sort(key=lambda old: old.get("index", 10**9))
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest.sort(key=lambda old: old.get("index", 10**9))
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
