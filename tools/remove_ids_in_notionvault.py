import os
import sys
import argparse


def split_frontmatter_and_body(text: str):
    if text.startswith('---\n'):
        end_idx = text.find('\n---\n', 4)
        if end_idx != -1:
            yaml_str = text[4:end_idx]
            body = text[end_idx + 5 :]
            return yaml_str, body
    return None, text


def remove_id_from_yaml(yaml_str: str) -> str:
    lines = yaml_str.splitlines()
    kept = []
    for line in lines:
        # match keys exactly starting with 'id:' with optional spaces after key
        stripped = line.lstrip()
        if stripped.startswith('id:'):
            continue
        kept.append(line)
    return '\n'.join(kept)


def process_markdown_file(path: str) -> bool:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            original = f.read()
    except Exception:
        return False

    yaml_str, body = split_frontmatter_and_body(original)
    if yaml_str is None:
        return False

    new_yaml = remove_id_from_yaml(yaml_str)
    if new_yaml == yaml_str:
        return False

    new_content = f"---\n{new_yaml}\n---\n{body}"
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    return True


def iter_markdown_files(root: str):
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.lower().endswith('.md'):
                yield os.path.join(dirpath, name)


def main():
    parser = argparse.ArgumentParser(description='Remove YAML id field from Markdown files under KeepVault/NotionVault')
    parser.add_argument('--root', default=os.path.join(os.getcwd(), 'KeepVault', 'NotionVault'), help='Path to NotionVault root')
    parser.add_argument('--dry-run', action='store_true', help='Only report files that would change')
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        print(f"Root not found: {root}")
        return 2

    total = 0
    changed = 0
    for md in iter_markdown_files(root):
        total += 1
        try:
            with open(md, 'r', encoding='utf-8') as f:
                content = f.read()
            yaml_str, _body = split_frontmatter_and_body(content)
            if yaml_str is None:
                continue
            new_yaml = remove_id_from_yaml(yaml_str)
            if new_yaml != yaml_str:
                changed += 1
                if not args.dry_run:
                    new_content = f"---\n{new_yaml}\n---\n{content[ content.find('\n---\n', 4) + 5: ]}"
                    with open(md, 'w', encoding='utf-8') as fw:
                        fw.write(new_content)
        except Exception:
            # skip unreadable files
            continue

    print(f"Scanned {total} Markdown files under {root}. Updated {changed}.")
    return 0


if __name__ == '__main__':
    sys.exit(main())


