#!/usr/bin/env python3
"""Promote reviewed Douyin notes from raw review/current into Wiki Library."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

from douyin_layout import DEFAULT_OUTPUT, manifest_candidates, review_archive, review_current, review_events_path
from note_metadata import render_frontmatter, split_frontmatter


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:80] or fallback).strip("-._")


def title_from_review(path: Path, meta: dict) -> str:
    title = meta.get("original_title") or path.stem
    title = re.sub(r"^\d{4}-\d{2}-\d{2}-\d+-", "", str(title))
    return title.replace("-", " ").strip() or path.stem


def source_page_name(note: Path, meta: dict) -> str:
    aweme_id = str(meta.get("aweme_id") or "").strip()
    index = str(meta.get("manifest_item_index") or "").strip()
    title = title_from_review(note, meta)
    prefix = f"douyin-{aweme_id}" if aweme_id else f"douyin-{meta.get('pull_id', 'unknown')}-{index or note.stem}"
    return f"{prefix}-{slugify(title, 'review')}.md"


def rel(path: Path, start: Path) -> str:
    return Path(os.path.relpath(path, start=start)).as_posix()


def unique_target(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 2
    while True:
        candidate = path.with_name(f"{stem}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def read_manifest(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return raw if isinstance(raw, list) else []


def write_manifest(path: Path, manifest: list[dict]) -> None:
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def load_event_keys(path: Path) -> set[tuple[str, str, str]]:
    if not path.exists():
        return set()
    keys: set[tuple[str, str, str]] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except Exception:
            continue
        keys.add((str(event.get("event") or ""), str(event.get("aweme_id") or ""), str(event.get("note") or "")))
    return keys


def append_event(path: Path, event: dict, existing: set[tuple[str, str, str]]) -> None:
    key = (str(event.get("event") or ""), str(event.get("aweme_id") or ""), str(event.get("note") or ""))
    if key in existing:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")
    existing.add(key)


def rewrite_relative_links(body: str, *, old_base: Path, new_base: Path) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2).strip()
        if re.match(r"^(?:[a-z][a-z0-9+.-]*:|/|#)", target, re.I):
            return match.group(0)
        resolved = (old_base / target).resolve()
        rewritten = Path(os.path.relpath(resolved, start=new_base)).as_posix()
        return f"[{label}]({rewritten})"

    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", replace, body)


def source_body(
    note_path: Path,
    archive_path: Path,
    source_target: Path,
    meta: dict,
    body: str,
    wiki_root: Path,
    douyin_root: Path,
) -> str:
    today = date.today().isoformat()
    title = title_from_review(note_path, meta)
    source_meta = {
        "type": "source",
        "title": title,
        "description": f"抖音收藏候选总结：{title}",
        "created": today,
        "updated": today,
        "status": "active",
        "raw": rel(archive_path, wiki_root),
        "url": meta.get("source_url"),
        "tags": ["douyin", "reviewed"],
        "entities": [],
        "concepts": [],
        "sources": [],
    }
    raw_pull = douyin_root / "pulls" / str(meta.get("pull_id") or "")
    raw_lines = [f"- Review: `{rel(archive_path, wiki_root)}`"]
    if raw_pull.exists():
        raw_lines.append(f"- Pull: `{rel(raw_pull, wiki_root)}`")
    if meta.get("source_url"):
        raw_lines.append(f"- URL: {meta['source_url']}")
    body = rewrite_relative_links(body, old_base=archive_path.parent, new_base=source_target.parent)
    return (
        render_frontmatter(source_meta)
        + "\n\n"
        + f"# {title}\n\n"
        + "## 摘要\n\n"
        + f"这页由抖音收藏候选总结晋升而来。原始候选总结保存在 raw review archive 中。\n\n"
        + "## 原始资料\n\n"
        + "\n".join(raw_lines)
        + "\n\n"
        + "## 整理后的总结\n\n"
        + body.strip()
        + "\n\n"
        + "## 可能更新的页面\n\n"
        + "- 后续可按主题沉淀到 concepts、entities、questions 或 outputs。\n\n"
        + "## 待验证\n\n"
        + "- 该页保留视频总结中的说法；事实性判断需结合更多来源验证。\n"
    )


def update_index(index_path: Path, source_links: list[str]) -> None:
    text = index_path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    text = re.sub(r"updated:\s*\d{4}-\d{2}-\d{2}", f"updated: {today}", text, count=1)
    lines = text.splitlines()
    try:
        sources_idx = lines.index("## Sources")
    except ValueError:
        lines.extend(["", "## Sources", "", "暂无。"])
        sources_idx = lines.index("## Sources")
    next_heading = next((i for i in range(sources_idx + 1, len(lines)) if lines[i].startswith("## ") and i != sources_idx), len(lines))
    section = lines[sources_idx + 1:next_heading]
    section = [line for line in section if line.strip() != "暂无。"]
    existing = "\n".join(section)
    bullets = [line for line in section if line.startswith("- ")]
    for link in source_links:
        if link not in existing:
            bullets.append(f"- {link}")
    section = ["", *bullets, ""]
    lines = lines[:sources_idx + 1] + section + lines[next_heading:]
    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def append_log(log_path: Path, promoted: list[str], dismissed: int) -> None:
    if not promoted and dismissed == 0:
        return
    today = date.today().isoformat()
    text = log_path.read_text(encoding="utf-8")
    text = re.sub(r"updated:\s*\d{4}-\d{2}-\d{2}", f"updated: {today}", text, count=1)
    log_path.write_text(text, encoding="utf-8")
    entry = [
        "",
        f"## [{today}] ingest | Promote Douyin review",
        "",
        f"- Promoted: {', '.join(promoted) if promoted else 'none'}",
        f"- Dismissed by deletion: {dismissed}",
        "- Notes: 从 `raw/douyin/review/current/` 晋升保留的候选总结，并将其移入 `raw/douyin/review/archive/`。",
        "",
    ]
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(entry))


def promote_note(note_path: Path, *, wiki_root: Path, douyin_root: Path, events: set[tuple[str, str, str]]) -> tuple[str, Path]:
    text = note_path.read_text(encoding="utf-8")
    meta, body = split_frontmatter(text)
    category = str(meta.get("category") or note_path.parent.name or "待分类")
    archive_target = unique_target(review_archive(douyin_root) / category / note_path.name)
    source_target = unique_target(wiki_root / "wiki" / "sources" / source_page_name(note_path, meta))

    archive_target.parent.mkdir(parents=True, exist_ok=True)
    source_target.parent.mkdir(parents=True, exist_ok=True)
    source_text = source_body(note_path, archive_target, source_target, meta, body, wiki_root, douyin_root)
    source_target.write_text(source_text, encoding="utf-8")

    meta["promoted"] = True
    meta["promoted_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta["wiki_source"] = rel(source_target, wiki_root)
    archive_target.write_text(render_frontmatter(meta) + "\n\n" + body.rstrip() + "\n", encoding="utf-8")
    note_path.unlink()

    event = {
        "event": "promoted",
        "at": meta["promoted_at"],
        "aweme_id": meta.get("aweme_id"),
        "pull_id": meta.get("pull_id"),
        "note": str(archive_target),
        "wiki_source": str(source_target),
    }
    append_event(review_events_path(douyin_root), event, events)
    return f"[[sources/{source_target.stem}]]", archive_target


def record_deleted_from_manifests(douyin_root: Path, events: set[tuple[str, str, str]]) -> int:
    current = review_current(douyin_root).resolve()
    count = 0
    for manifest_path in manifest_candidates(douyin_root):
        changed = False
        manifest = read_manifest(manifest_path)
        for item in manifest:
            note_value = item.get("note")
            if not note_value:
                continue
            note_path = Path(note_value)
            try:
                is_current_note = note_path.resolve().is_relative_to(current)
            except AttributeError:
                is_current_note = str(note_path.resolve()).startswith(str(current) + os.sep)
            if not is_current_note or note_path.exists():
                continue
            item["review_status"] = "dismissed_by_deletion"
            item["review_dismissed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            append_event(
                review_events_path(douyin_root),
                {
                    "event": "dismissed_by_deletion",
                    "at": item["review_dismissed_at"],
                    "aweme_id": item.get("aweme_id"),
                    "pull_id": item.get("pull_id") or item.get("pulled_at"),
                    "note": note_value,
                    "manifest": str(manifest_path),
                },
                events,
            )
            count += 1
            changed = True
        if changed:
            write_manifest(manifest_path, manifest)
    return count


def update_promoted_manifest_paths(douyin_root: Path, promoted_paths: dict[str, Path]) -> None:
    for manifest_path in manifest_candidates(douyin_root):
        manifest = read_manifest(manifest_path)
        changed = False
        for item in manifest:
            note_value = item.get("note")
            if note_value in promoted_paths:
                item["note"] = str(promoted_paths[note_value])
                item["review_status"] = "promoted"
                changed = True
        if changed:
            write_manifest(manifest_path, manifest)


def count_deleted_from_manifests(douyin_root: Path) -> int:
    current = review_current(douyin_root).resolve()
    count = 0
    for manifest_path in manifest_candidates(douyin_root):
        for item in read_manifest(manifest_path):
            note_value = item.get("note")
            if not note_value:
                continue
            note_path = Path(note_value)
            try:
                is_current_note = note_path.resolve().is_relative_to(current)
            except AttributeError:
                is_current_note = str(note_path.resolve()).startswith(str(current) + os.sep)
            if is_current_note and not note_path.exists():
                count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wiki-root", type=Path, default=Path("Wiki Library"))
    parser.add_argument("--douyin-root", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    wiki_root = args.wiki_root
    douyin_root = args.douyin_root
    notes = sorted(path for path in review_current(douyin_root).glob("*/*.md") if path.is_file())
    events = load_event_keys(review_events_path(douyin_root))

    if args.dry_run:
        print(f"Current review notes: {len(notes)}")
        for path in notes:
            print(f"- {path}")
        print(f"Dismissed-by-deletion records that would be checked: {count_deleted_from_manifests(douyin_root)}")
        return 0

    promoted_links: list[str] = []
    promoted_paths: dict[str, Path] = {}
    for note in notes:
        old_value = str(note)
        link, archive_path = promote_note(note, wiki_root=wiki_root, douyin_root=douyin_root, events=events)
        promoted_links.append(link)
        promoted_paths[old_value] = archive_path

    update_promoted_manifest_paths(douyin_root, promoted_paths)
    dismissed = record_deleted_from_manifests(douyin_root, events)
    if promoted_links:
        update_index(wiki_root / "wiki" / "index.md", promoted_links)
    append_log(wiki_root / "wiki" / "log.md", promoted_links, dismissed)
    print(f"Promoted {len(promoted_links)} review notes; recorded {dismissed} dismissed-by-deletion notes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
