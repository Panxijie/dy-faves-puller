#!/usr/bin/env python3
"""Rebuild the Douyin note index from the current note library."""

from __future__ import annotations

import argparse
import os
import re
from datetime import date
from pathlib import Path

from note_metadata import split_frontmatter


CATEGORY_ORDER = ["技术与工具", "科研与学习", "情感与关系", "生活与职场", "待分类"]
NOTE_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d+-")


def title_from_filename(path: Path) -> str:
    title = NOTE_NAME_RE.sub("", path.stem)
    return re.sub(r"\s+", " ", title.replace("-", " ")).strip() or path.stem


def strip_markdown(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"[*_~>#-]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def summary_from_body(body: str, limit: int, path: Path | None = None) -> str:
    match = re.search(r"^##\s+摘要\s*$([\s\S]*?)(?=^##\s+|\Z)", body, re.M)
    section = match.group(1) if match else body
    paragraphs = [strip_markdown(part) for part in re.split(r"\n\s*\n", section) if strip_markdown(part)]
    summary = paragraphs[0] if paragraphs else ""
    if len(summary) <= limit:
        return summary
    label = str(path) if path else "note"
    raise ValueError(f"{label}: ## 摘要 is {len(summary)} characters; rewrite it to {limit} characters or fewer.")


def escape_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def unescape_cell(value: str) -> str:
    return value.replace("\\|", "|").strip()


def category_sort_key(category: str) -> tuple[int, str]:
    try:
        return (CATEGORY_ORDER.index(category), category)
    except ValueError:
        return (len(CATEGORY_ORDER), category)


def collect_notes(output: Path, summary_limit: int) -> dict[str, list[dict[str, str]]]:
    note_root = output / "笔记库"
    grouped: dict[str, list[dict[str, str]]] = {}
    if not note_root.exists():
        return grouped
    for path in sorted(note_root.glob("*/*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = split_frontmatter(text)
        category = str(meta.get("category") or path.parent.name or "待分类")
        grouped.setdefault(category, []).append(
            {
                "title": title_from_filename(path),
                "subcategory": str(meta.get("subcategory") or "待分类"),
                "summary": summary_from_body(body, summary_limit, path),
                "link": Path(os.path.relpath(path, start=output)).as_posix(),
            }
        )
    for notes in grouped.values():
        notes.sort(key=lambda item: item["link"])
    return grouped


def expected_titles(output: Path, summary_limit: int) -> list[str]:
    grouped = collect_notes(output, summary_limit)
    titles: list[str] = []
    for category in sorted(grouped, key=category_sort_key):
        titles.extend(note["title"] for note in grouped[category])
    return titles


def index_titles(index_path: Path) -> list[str]:
    if not index_path.exists():
        return []
    titles: list[str] = []
    for line in index_path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| ---"):
            continue
        cells = [unescape_cell(cell) for cell in line.strip("|").split("|")]
        if cells and cells[0] != "标题":
            titles.append(cells[0])
    return titles


def check_titles(output: Path, summary_limit: int) -> bool:
    expected = expected_titles(output, summary_limit)
    actual = index_titles(output / "笔记索引.md")
    if actual == expected:
        print(f"Index titles match note library ({len(expected)} notes).")
        return True
    missing = [title for title in expected if title not in actual]
    extra = [title for title in actual if title not in expected]
    if missing:
        print("Missing from index:")
        for title in missing:
            print(f"- {title}")
    if extra:
        print("Extra in index:")
        for title in extra:
            print(f"- {title}")
    return False


def build_index_text(output: Path, summary_limit: int = 50) -> str:
    grouped = collect_notes(output, summary_limit)
    lines = [
        "# 抖音收藏笔记索引",
        "",
        f"更新时间：{date.today().isoformat()}",
        "",
    ]
    for category in sorted(grouped, key=category_sort_key):
        lines.extend(
            [
                f"## {category}",
                "",
                "| 标题 | 子类别 | 内容摘要 | 笔记 |",
                "| --- | --- | --- | --- |",
            ]
        )
        for note in grouped[category]:
            lines.append(
                f"| {escape_cell(note['title'])} | {escape_cell(note['subcategory'])} | "
                f"{escape_cell(note['summary'])} | [打开]({note['link']}) |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def write_index(output: Path, summary_limit: int = 50) -> Path:
    target = output / "笔记索引.md"
    target.write_text(build_index_text(output, summary_limit), encoding="utf-8")
    return target


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("Douyin Favorites"))
    parser.add_argument("--summary-limit", type=int, default=50)
    parser.add_argument("--check-titles", action="store_true", help="Only compare index titles with current note-library titles.")
    args = parser.parse_args()
    if args.check_titles:
        return 0 if check_titles(args.output, args.summary_limit) else 1
    target = write_index(args.output, args.summary_limit)
    print(f"Updated {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
