#!/usr/bin/env python3
"""
Export KeepVault (excluding Trashed) into a single, consistently-named JSON file
at tools/vault_export.json with a structure designed for efficient RAG/agentic AI.

Usage:
  - From repo root or tools/:
      python tools/export_vault_to_markdown.py
  - Optional custom vault path:
      python tools/export_vault_to_markdown.py --vault-path /absolute/path/to/KeepVault

Notes:
  - Output path is fixed to tools/vault_export.json (intentionally stable for .gitignore)
  - Only markdown files (*.md) are included
  - Any file under a directory named "Trashed" is excluded
  - Tags/labels are intentionally omitted from note metadata for now
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Tuple, List, Set, Optional
import json
import re


class DateTimeEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles datetime objects by converting them to ISO format strings."""
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def parse_frontmatter(full_text: str) -> Tuple[str, Dict, str]:
    """Return (frontmatter_raw, frontmatter_dict, body)

    - frontmatter_raw: the raw YAML text between the first two '---' lines (no markers)
    - frontmatter_dict: parsed YAML as dict (empty dict on error/missing)
    - body: the remaining markdown content after frontmatter
    """
    try:
        import yaml  # local dependency, already used in this repo
    except Exception:
        yaml = None  # still return raw strings if PyYAML missing

    if full_text.startswith("---\n"):
        parts = full_text.split("---\n", 2)
        if len(parts) >= 3:
            fm_raw = parts[1]
            body = parts[2]
            fm_dict = {}
            if yaml is not None:
                try:
                    parsed = yaml.safe_load(fm_raw)
                    if isinstance(parsed, dict):
                        fm_dict = parsed
                except Exception:
                    fm_dict = {}
            return fm_raw.rstrip("\n"), fm_dict, body
    # no frontmatter
    return "", {}, full_text


def is_trashed(path: Path, vault_root: Path) -> bool:
    """Return True if the path is inside a directory named 'Trashed' under vault_root."""
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        # not under vault
        return False
    parts = rel.parts
    return "Trashed" in parts


def coerce_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return [value]
    return []


def extract_meta(fm: Dict) -> Dict:
    # Normalize common metadata fields used across this repo (omit tags/labels intentionally)
    return {
        "id": fm.get("id"),
        "title": fm.get("title"),
        "color": (fm.get("color") or "").upper() if isinstance(fm.get("color"), str) else fm.get("color"),
        "pinned": bool(fm.get("pinned", False)),
        "archived": bool(fm.get("archived", False)),
        "trashed": bool(fm.get("trashed", False)),
        "created": fm.get("created"),
        "updated": fm.get("updated"),
        "edited": fm.get("edited"),
    }


def discover_markdown_files(vault_root: Path) -> list:
    files = []
    for p in vault_root.rglob("*.md"):
        if p.is_file() and not is_trashed(p, vault_root):
            files.append(p)
    # sort for deterministic ordering
    files.sort(key=lambda x: x.as_posix().lower())
    return files


def build_note_index(files: List[Path], vault_root: Path) -> Dict[str, List[str]]:
    """Build an index mapping keys to relative posix paths for resolution.

    Keys include:
      - relative path without extension, lowercased
      - filename stem, lowercased
    Values are lists of relative posix paths (sorted deterministically).
    """
    index: Dict[str, List[str]] = {}
    rel_paths = [f.relative_to(vault_root).as_posix() for f in files]
    for rel in sorted(rel_paths, key=lambda p: p.lower()):
        # path without extension
        if rel.lower().endswith(".md"):
            without_ext = rel[:-3]
        else:
            without_ext = rel
        stem_key = Path(rel).stem.lower()
        keys = {without_ext.lower(), stem_key}
        for key in keys:
            index.setdefault(key, []).append(rel)
    return index


MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _strip_anchor_and_query(target: str) -> str:
    base = target.split("#", 1)[0]
    base = base.split("?", 1)[0]
    return base


def _normalize_internal_path(candidate: Path, vault_root: Path) -> Optional[str]:
    try:
        candidate = candidate.resolve()
        if not candidate.is_file():
            return None
        rel = candidate.relative_to(vault_root).as_posix()
        return rel
    except Exception:
        return None


def extract_links(text: str, current_file: Path, vault_root: Path, index: Dict[str, List[str]]) -> Tuple[Set[str], Set[str]]:
    """Return (internal_links_rel_paths, external_links_urls).

    - Internal links include markdown relative links and wikilinks, resolved to
      relative posix paths within the vault when possible.
    - External links capture http/https URLs from markdown links.
    """
    internal: Set[str] = set()
    external: Set[str] = set()

    # Markdown links
    for _text, target in MD_LINK_RE.findall(text):
        target = target.strip()
        if target.startswith("http://") or target.startswith("https://"):
            external.add(target)
            continue
        if target.startswith("mailto:"):
            continue
        cleaned = _strip_anchor_and_query(target)
        # Resolve relative to current file directory
        base_candidate = (current_file.parent / cleaned)
        candidates: List[Path] = []
        candidates.append(base_candidate)
        if base_candidate.suffix.lower() != ".md":
            candidates.append(base_candidate.with_suffix(".md"))
        for cand in candidates:
            rel = _normalize_internal_path(cand, vault_root)
            if rel:
                internal.add(rel)
                break

    # Wikilinks
    for raw in WIKILINK_RE.findall(text):
        # handle alias and anchors
        target = raw.split("|", 1)[0].strip()
        target = _strip_anchor_and_query(target)
        if not target:
            continue
        key = target.lower()
        # Path-like wikilink (folder/note)
        if "/" in target or "\\" in target:
            # normalize separators and try index lookups without extension
            normalized = target.replace("\\", "/")
            if normalized.lower().endswith(".md"):
                normalized_no_ext = normalized[:-3].lower()
            else:
                normalized_no_ext = normalized.lower()
            candidates = index.get(normalized_no_ext, [])
            if candidates:
                internal.add(candidates[0])
                continue
        # Stem-based resolution
        candidates = index.get(key, [])
        if candidates:
            internal.add(candidates[0])

    return internal, external


def export_vault(vault_root: Path, output_path: Path) -> Tuple[int, Path]:
    files = discover_markdown_files(vault_root)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build index for link resolution
    index = build_note_index(files, vault_root)

    # First pass: parse notes and collect outbound links
    notes_temp: List[Dict] = []
    for md_file in files:
        rel_path = md_file.relative_to(vault_root).as_posix()
        text = md_file.read_text(encoding="utf-8")
        fm_raw, fm_dict, body = parse_frontmatter(text)
        meta = extract_meta(fm_dict)
        size_bytes = md_file.stat().st_size
        outbound_internal, external_links = extract_links(text, md_file, vault_root, index)
        notes_temp.append({
            "rel_path": rel_path,
            "filename": md_file.name,
            "size_bytes": size_bytes,
            "meta": meta,
            "content": body.rstrip("\n"),
            "outbound_internal": sorted(outbound_internal),
            "external_links": sorted(external_links),
        })

    # Compute backlinks
    backlinks_map: Dict[str, Set[str]] = {}
    for note in notes_temp:
        source = note["rel_path"]
        for target in note["outbound_internal"]:
            backlinks_map.setdefault(target, set()).add(source)

    # Build final JSON structure
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = {
        "export": {
            "generated_utc": generated,
            "vault_path": str(vault_root.resolve()),
            "excluded_dirs": ["Trashed"],
            "notes_count": len(files),
            "version": "2.0",
        },
        "notes": [],
    }

    for note in notes_temp:
        rel_path = note["rel_path"]
        data["notes"].append({
            "path": rel_path,
            "filename": note["filename"],
            "size_bytes": note["size_bytes"],
            # include normalized metadata (excluding tags/labels)
            **note["meta"],
            # links
            "links": {
                "internal": note["outbound_internal"],
                "external": note["external_links"],
            },
            "backlinks": sorted(backlinks_map.get(rel_path, set())),
            # content last for readability
            "content": note["content"],
        })

    with output_path.open("w", encoding="utf-8") as out:
        json.dump(data, out, ensure_ascii=False, indent=2, cls=DateTimeEncoder)

    return len(files), output_path


    


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    default_vault = (script_dir.parent / "KeepVault").resolve()
    fixed_output = (script_dir / "vault_export.json").resolve()

    parser = argparse.ArgumentParser(description="Export KeepVault to a single JSON file for RAG/agentic AI")
    parser.add_argument("--vault-path", "-v", type=str, default=str(default_vault),
                        help="Path to KeepVault (default: ../KeepVault relative to tools/)")
    args = parser.parse_args()

    vault_root = Path(args.vault_path).expanduser().resolve()
    if not vault_root.exists() or not vault_root.is_dir():
        print(f"Error: Vault path '{vault_root}' does not exist or is not a directory.")
        return 1

    count, out_path = export_vault(vault_root, fixed_output)
    print(f"Exported {count} notes (excluding Trashed) to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


