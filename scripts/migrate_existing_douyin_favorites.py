#!/usr/bin/env python3
"""Migrate the old Douyin Favorites library into Wiki Library raw/douyin."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from douyin_layout import (
    DEFAULT_OUTPUT,
    asset_dir,
    assert_current_review_empty,
    ensure_review_dirs,
    pulls_root,
    registry_root,
    review_current,
)
from note_metadata import extract_aweme_id, render_frontmatter, split_frontmatter


PULL_ID = "legacy-douyin-favorites"


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


def move_file(source: Path, target: Path, *, apply: bool) -> Path:
    target = unique_target(target)
    print(f"{source} -> {target}")
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
    return target


def asset_kind(path: Path) -> str | None:
    lower = path.name.lower()
    if lower.endswith((".mp4", ".webm", ".mov", ".mkv")) or "-video" in lower:
        return "video"
    if lower.endswith((".wav", ".mp3", ".m4a", ".aac")) or "-audio" in lower:
        return "audio"
    if lower.endswith(".txt") or "-transcript" in lower:
        return "transcript"
    if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")) or "-image" in lower:
        return "image"
    return None


def rel_link(note_target: Path, target: Path) -> str:
    return Path(os.path.relpath(target, start=note_target.parent)).as_posix()


def rewrite_asset_links(body: str, note_target: Path, moved_assets: dict[str, Path]) -> str:
    def replace(match: re.Match[str]) -> str:
        label = match.group(1)
        target = match.group(2)
        name = Path(target).name
        if name in moved_assets:
            return f"[{label}]({rel_link(note_target, moved_assets[name])})"
        return match.group(0)

    return re.sub(r"\[([^\]]+)\]\((?:\.\./\.\./素材库/|素材库/)([^)]+)\)", replace, body)


def move_assets(source_root: Path, douyin_root: Path, *, apply: bool) -> dict[str, Path]:
    moved: dict[str, Path] = {}
    asset_source = source_root / "素材库"
    if not asset_source.exists():
        return moved
    for source in sorted(asset_source.iterdir()):
        if not source.is_file():
            continue
        kind = asset_kind(source)
        if not kind:
            continue
        target = move_file(source, asset_dir(douyin_root, kind) / source.name, apply=apply)
        moved[source.name] = target
    return moved


def migrate_pull_records(source_root: Path, douyin_root: Path, *, apply: bool) -> None:
    record_root = source_root / "拉取记录"
    if not record_root.exists():
        return
    for source in sorted(record_root.iterdir()):
        if source.name == "aweme_ids.txt":
            target = registry_root(douyin_root) / "aweme_ids.txt"
            move_file(source, target, apply=apply)
        elif source.is_dir():
            move_file(source, pulls_root(douyin_root) / source.name, apply=apply)


def migrate_misc(source_root: Path, douyin_root: Path, *, apply: bool) -> None:
    index = source_root / "笔记索引.md"
    if index.exists():
        move_file(index, douyin_root / "legacy" / "笔记索引.md", apply=apply)
    details = source_root / "details"
    if details.exists():
        for source in sorted(details.glob("*.json")):
            move_file(source, pulls_root(douyin_root) / PULL_ID / "json" / "details" / source.name, apply=apply)
    models = source_root / "models"
    if models.exists():
        for source in sorted(models.iterdir()):
            if source.is_file():
                move_file(source, douyin_root / "models" / source.name, apply=apply)


def migrate_notes(source_root: Path, douyin_root: Path, moved_assets: dict[str, Path], *, apply: bool) -> list[dict]:
    note_root = source_root / "笔记库"
    manifest: list[dict] = []
    if not note_root.exists():
        return manifest
    for index, source in enumerate(sorted(note_root.glob("*/*.md")), start=1):
        category = source.parent.name
        note_target = review_current(douyin_root) / category / source.name
        text = source.read_text(encoding="utf-8")
        meta, body = split_frontmatter(text)
        aweme_id = extract_aweme_id(meta.get("source_url"), meta.get("aweme_id"))
        meta["aweme_id"] = aweme_id
        meta["pull_id"] = PULL_ID
        meta.setdefault("pulled_at", meta.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M"))
        meta["manifest_item_index"] = index
        meta["promoted"] = False
        body = rewrite_asset_links(body, note_target, moved_assets)
        new_text = render_frontmatter(meta) + "\n\n" + body.rstrip() + "\n"
        print(f"{source} -> {note_target}")
        if apply:
            note_target.parent.mkdir(parents=True, exist_ok=True)
            note_target.write_text(new_text, encoding="utf-8")
            source.unlink()
        item = {
            "index": index,
            "status": "ok",
            "aweme_id": aweme_id,
            "source_url": meta.get("source_url"),
            "title": meta.get("original_title") or source.stem,
            "note": str(note_target),
            "category": meta.get("category") or category,
            "subcategory": meta.get("subcategory"),
            "pulled_at": meta.get("pulled_at"),
            "pull_id": PULL_ID,
        }
        for key, suffix in (("video", "-video"), ("audio", "-audio"), ("transcript", "-transcript")):
            target = next((path for name, path in moved_assets.items() if source.stem in name and suffix in name), None)
            if target:
                item[key] = str(target)
        manifest.append(item)
    return manifest


def write_manifest(douyin_root: Path, manifest: list[dict], *, apply: bool) -> None:
    target = pulls_root(douyin_root) / PULL_ID / "json" / "run_manifest.json"
    print(f"manifest -> {target}")
    if apply:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("Douyin Favorites"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.apply:
        assert_current_review_empty(args.output)
        ensure_review_dirs(args.output)
    moved_assets = move_assets(args.source, args.output, apply=args.apply)
    manifest = migrate_notes(args.source, args.output, moved_assets, apply=args.apply)
    migrate_pull_records(args.source, args.output, apply=args.apply)
    migrate_misc(args.source, args.output, apply=args.apply)
    write_manifest(args.output, manifest, apply=args.apply)
    print(f"Migrated {len(manifest)} reviewed notes.")
    if not args.apply:
        print("Preview only; rerun with --apply to move files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
