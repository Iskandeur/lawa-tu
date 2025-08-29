import os
import re

def has_tags(filepath):
    """Checks if a markdown file contains tags."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
            # Check for tags in frontmatter (e.g., tags: [tag1, tag2])
            if re.search(r"^---.*?tags:.*?---", content, re.DOTALL | re.IGNORECASE):
                return True
            # Check for inline tags (e.g., #tag)
            if re.search(r"#\w+", content):
                return True
    except Exception as e:
        print(f"Error reading file {filepath}: {e}")
    return False

def find_untagged_markdown_files(vault_dir, output_file):
    """Finds all .md files in vault_dir without tags and writes their names to output_file."""
    untagged_files = []
    for root, _, files in os.walk(vault_dir):
        for file in files:
            if file.endswith(".md"):
                filepath = os.path.join(root, file)
                if not has_tags(filepath):
                    untagged_files.append(file) # Store only the filename

    with open(output_file, 'w', encoding='utf-8') as f:
        for filename in untagged_files:
            f.write(f"{filename}\n")
    print(f"Found {len(untagged_files)} untagged files. Their names are written to {output_file}")

if __name__ == "__main__":
    keepvault_directory = "KeepVault"
    output_filename = "unprocessed_files.txt"

    if not os.path.isdir(keepvault_directory):
        print(f"Error: Directory '{keepvault_directory}' not found.")
    else:
        find_untagged_markdown_files(keepvault_directory, output_filename) 