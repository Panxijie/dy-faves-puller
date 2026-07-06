#!/usr/bin/env python3
"""Rename existing notes to sequence + clean title and enrich YAML properties."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from note_metadata import clean_title, extract_tags, leading_metric, render_frontmatter, split_frontmatter, stats_from_aweme, tags_from_aweme


def slugify(value: str, fallback: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", value, flags=re.UNICODE).strip("-._")
    return (value[:90] or fallback).strip("-._")


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def find_manifest(output: Path, explicit: Path | None) -> Path:
    if explicit:
        return explicit
    root = output / "run_manifest.json"
    if root.exists():
        return root
    candidates = sorted((output / "拉取记录").glob("*/json/run_manifest.json"))
    if candidates:
        return candidates[-1]
    raise FileNotFoundError("No run_manifest.json found")


def note_page_stats(text: str) -> dict[str, int]:
    match = re.search(r"投稿\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", text or "")
    if not match:
        return {}
    return dict(zip(("likes", "comments", "favorites", "shares"), map(int, match.groups())))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("Douyin Favorites"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--apply", action="store_true", help="Apply renames and metadata changes. Default is a preview.")
    args = parser.parse_args()

    manifest_path = find_manifest(args.output, args.manifest)
    manifest = load_json(manifest_path)
    note_extracts_path = manifest_path.parent / "note-extracts.json"
    if not note_extracts_path.exists():
        note_extracts_path = args.output / "note-extracts.json"
    note_extracts = {
        item["index"]: item
        for item in (load_json(note_extracts_path) if note_extracts_path.exists() else [])
    }

    changes: list[tuple[Path, Path, str, dict]] = []
    for item in manifest:
        index = int(item["index"])
        source = Path(item["note"])
        meta, body = split_frontmatter(source.read_text(encoding="utf-8"))
        title = clean_title(str(meta.get("title") or item.get("title") or ""), f"douyin-{index:02d}")
        stats: dict[str, int] = {}
        tags: list[str] = []

        detail_path = item.get("detail_json")
        if detail_path and Path(detail_path).exists() and Path(detail_path).stat().st_size:
            aweme = (load_json(Path(detail_path)) or {}).get("aweme_detail") or {}
            stats = stats_from_aweme(aweme)
            tags = tags_from_aweme(aweme)
        else:
            raw_title = str(item.get("title") or "")
            likes = leading_metric(raw_title)
            if likes is not None:
                stats["likes"] = likes
            tags = extract_tags(raw_title)

        if index in note_extracts:
            stats.update(note_page_stats(note_extracts[index].get("text") or ""))
            tags = list(dict.fromkeys([*tags, *extract_tags(note_extracts[index].get("original_title") or "")]))

        meta["title"] = title
        for key in ("likes", "comments", "favorites", "shares", "plays"):
            meta.pop(key, None)
            if key in stats:
                meta[key] = stats[key]
        meta["tags"] = tags
        target = source.parent / f"{index:02d}-{slugify(title, f'douyin-{index:02d}')}.md"
        text = render_frontmatter(meta) + "\n\n" + body.rstrip() + "\n"
        changes.append((source, target, text, item))
        print(f"{source.name} -> {target.name}")

    if not args.apply:
        print("Preview only; rerun with --apply to write changes.")
        return 0

    targets = [target for _, target, _, _ in changes]
    if len(targets) != len(set(targets)):
        raise RuntimeError("Two notes resolve to the same target filename")
    for source, target, text, item in changes:
        target.write_text(text, encoding="utf-8")
        if source != target:
            source.unlink()
        item["note"] = str(target)
        item["note_title"] = split_frontmatter(text)[0]["title"]
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
