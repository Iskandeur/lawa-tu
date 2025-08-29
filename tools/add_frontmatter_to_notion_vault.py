import os
import sys
import uuid
import argparse
from datetime import datetime

import yaml


def read_file_text(path: str) -> str:
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write_file_text(path: str, content: str) -> None:
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def split_frontmatter_and_body(text: str):
    if text.startswith('---\n'):
        # Find the closing '---' line
        end_idx = text.find('\n---\n', 4)
        if end_idx != -1:
            yaml_str = text[4:end_idx]
            body = text[end_idx + 5 :]
            return yaml_str, body
    return None, text


def ensure_keep_style_frontmatter(meta: dict, file_path: str) -> dict:
    # Normalize types and ensure fields exist similar to KeepVault
    # Fields observed: id, title, color, pinned, created, updated, edited, archived, trashed
    # We'll keep existing values if present.
    meta = dict(meta) if meta else {}

    # id: generate if missing
    if 'id' not in meta or meta['id'] in (None, ''):
        # mimic Keep-like id appearance: random-ish hex with dots
        meta['id'] = f"{uuid.uuid4().hex[:10]}.{uuid.uuid4().hex[:16]}"

    # title: default from filename without extension
    if 'title' not in meta:
        meta['title'] = os.path.splitext(os.path.basename(file_path))[0]

    # color: default WHITE (Keep sometimes uses 'White' or 'WHITE'); prefer 'White' per examples
    if 'color' not in meta or not meta['color']:
        meta['color'] = 'White'

    # pinned/archived/trashed: booleans default false
    for key in ('pinned', 'archived', 'trashed'):
        if key not in meta or meta[key] is None:
            meta[key] = False

    # timestamps: ISO strings; default to file mtime for created/updated/edited if missing
    def iso_from_ts(ts: float) -> str:
        # local time with offset is complex; use naive ISO if offset unknown
        # KeepVault examples include timezone offset; we stick to ISO without offset for simplicity
        return datetime.fromtimestamp(ts).isoformat()

    try:
        stat = os.stat(file_path)
        fallback_created = iso_from_ts(stat.st_ctime)
        fallback_updated = iso_from_ts(stat.st_mtime)
    except Exception:
        now = datetime.now().isoformat()
        fallback_created = now
        fallback_updated = now

    if 'created' not in meta or not meta['created']:
        meta['created'] = fallback_created
    if 'updated' not in meta or not meta['updated']:
        meta['updated'] = fallback_updated
    if 'edited' not in meta or not meta['edited']:
        meta['edited'] = meta.get('updated', fallback_updated)

    # tags: prefer tags over labels; migrate labels -> tags and ensure NotionImport present
    existing_tags = meta.get('tags')
    existing_labels = meta.get('labels')

    tags_list = []
    if isinstance(existing_tags, list):
        tags_list.extend([str(x) for x in existing_tags])
    elif isinstance(existing_tags, str) and existing_tags.strip():
        tags_list.append(existing_tags.strip())

    if isinstance(existing_labels, list):
        tags_list.extend([str(x) for x in existing_labels])
    elif isinstance(existing_labels, str) and existing_labels.strip():
        tags_list.append(existing_labels.strip())

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for t in tags_list:
        if t not in seen:
            seen.add(t)
            deduped.append(t)

    if 'NotionImport' not in seen:
        deduped.append('NotionImport')

    meta['tags'] = deduped
    if 'labels' in meta:
        del meta['labels']

    return meta


def dump_yaml(meta: dict) -> str:
    # Preserve key order similar to KeepVault appearance
    ordered_keys = [
        'id', 'title', 'color', 'pinned', 'created', 'updated', 'edited', 'archived', 'trashed', 'tags'
    ]
    ordered = {}
    for key in ordered_keys:
        if key in meta:
            ordered[key] = meta[key]
    # Include any extra keys at the end
    for key in meta:
        if key not in ordered:
            ordered[key] = meta[key]
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True).strip()


def process_file(path: str) -> bool:
    original = read_file_text(path)
    yaml_str, body = split_frontmatter_and_body(original)
    meta = {}
    if yaml_str is not None:
        try:
            loaded = yaml.safe_load(yaml_str)
            if isinstance(loaded, dict):
                meta = loaded
        except Exception:
            # Treat as no frontmatter on parse error
            meta = {}
    meta = ensure_keep_style_frontmatter(meta, path)
    new_yaml = dump_yaml(meta)
    new_content = f"---\n{new_yaml}\n---\n{body}"
    if new_content != original:
        write_file_text(path, new_content)
        return True
    return False


def iter_markdown_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith('.md'):
                yield os.path.join(dirpath, name)


def main():
    parser = argparse.ArgumentParser(description='Add/ensure frontmatter for NotionVault notes with NotionImport label')
    parser.add_argument('--vault', default=os.path.join(os.getcwd(), 'NotionVault'), help='Path to NotionVault root')
    parser.add_argument('--dry-run', action='store_true', help='Do not write changes, only report')
    args = parser.parse_args()

    vault_path = os.path.abspath(args.vault)
    if not os.path.isdir(vault_path):
        print(f"Vault path not found: {vault_path}")
        return 2

    changed = 0
    total = 0
    for md_path in iter_markdown_files(vault_path):
        total += 1
        if args.dry_run:
            try:
                original = read_file_text(md_path)
            except Exception:
                continue
            yaml_str, _body = split_frontmatter_and_body(original)
            meta = {}
            if yaml_str is not None:
                try:
                    loaded = yaml.safe_load(yaml_str)
                    if isinstance(loaded, dict):
                        meta = loaded
                except Exception:
                    meta = {}
            meta = ensure_keep_style_frontmatter(meta, md_path)
            # simulate content
            new_yaml = dump_yaml(meta)
            new_content = f"---\n{new_yaml}\n---\n"
            if not original.startswith(new_content):
                changed += 1
        else:
            try:
                if process_file(md_path):
                    changed += 1
            except Exception as e:
                print(f"Error processing {md_path}: {e}")

    print(f"Processed {total} markdown files in {vault_path}. Updated {changed}.")
    return 0


if __name__ == '__main__':
    sys.exit(main())


