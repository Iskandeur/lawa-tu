#!/usr/bin/env python3

import os
import glob
import yaml
import re
from pathlib import Path

# Configuration
VAULT_DIR = "KeepVault"
# Regex to find inline tags like #tag, #tag-with-hyphen, #tag/with/slash
TAG_PATTERN_INLINE = re.compile(r'#([\w\/-]+)')

def parse_frontmatter_and_body(full_content):
    """Extracts YAML frontmatter (as dict) and body content from a note."""
    if full_content.startswith("---"):
        parts = re.split(r"^---\s*$", full_content, 2, flags=re.MULTILINE)
        if len(parts) >= 3: # An empty string before the first '---', YAML, body
            frontmatter_text = parts[1]
            body_content = parts[2].lstrip()
            try:
                frontmatter_dict = yaml.safe_load(frontmatter_text)
                if not isinstance(frontmatter_dict, dict):
                    frontmatter_dict = {} # Ensure it's a dict if parsing returns non-dict (e.g. null)
                return frontmatter_dict, body_content
            except yaml.YAMLError:
                return {}, full_content # Malformed YAML, treat as body
    return {}, full_content # No frontmatter

def _add_tags_from_key(frontmatter, key, all_tags_set):
    """Helper to add tags from a specific frontmatter key (e.g., 'labels' or 'tags')."""
    if key in frontmatter:
        tags_data = frontmatter[key]
        if isinstance(tags_data, list):
            for tag_item in tags_data:
                if isinstance(tag_item, str):
                    all_tags_set.add(tag_item.lstrip('#'))
        elif isinstance(tags_data, str):
            all_tags_set.add(tags_data.lstrip('#'))

def scan_for_all_tags(vault_path_str):
    """Scans all notes for inline tags and YAML 'labels'/'tags', returns a sorted list of unique tag names."""
    all_tags = set()
    vault_path = Path(vault_path_str)
    archived_dir = (vault_path / "Archived").as_posix()
    trashed_dir = (vault_path / "Trashed").as_posix()

    for file_path_obj in vault_path.glob("**/*.md"):
        file_path_str = file_path_obj.as_posix()
        if file_path_str.startswith(archived_dir) or \
           file_path_str.startswith(trashed_dir):
            continue
        try:
            with open(file_path_obj, 'r', encoding='utf-8') as file:
                content = file.read()
            
            frontmatter, body_content_for_inline_scan = parse_frontmatter_and_body(content)
            
            inline_tags_found = TAG_PATTERN_INLINE.findall(body_content_for_inline_scan)
            for tag in inline_tags_found:
                all_tags.add(tag) 
            
            if frontmatter:
                _add_tags_from_key(frontmatter, 'labels', all_tags)
                _add_tags_from_key(frontmatter, 'tags', all_tags)
                
        except Exception as e:
            print(f"Warning: Error scanning {file_path_obj.name} for tags: {e}")
    return sorted(list(all_tags))

def get_notes_by_selected_tag(vault_path_str, selected_tag_name):
    """
    Finds notes that contain the selected tag either in their body (e.g., #selected_tag_name)
    or as a label/tag in their frontmatter (e.g., labels: [selected_tag_name] or tags: [selected_tag_name]).
    Returns a list of (Path object, full_content string).
    """
    tagged_notes_data = []
    vault_path = Path(vault_path_str)
    archived_dir = (vault_path / "Archived").as_posix()
    trashed_dir = (vault_path / "Trashed").as_posix()
    
    inline_tag_to_search_pattern = re.compile(r'#(' + re.escape(selected_tag_name) + r')(?![^\s#])')

    for file_path_obj in vault_path.glob("**/*.md"):
        file_path_str = file_path_obj.as_posix()
        if file_path_str.startswith(archived_dir) or \
           file_path_str.startswith(trashed_dir):
            continue
        
        try:
            with open(file_path_obj, 'r', encoding='utf-8') as file:
                full_content = file.read()

            frontmatter, body_for_inline_check = parse_frontmatter_and_body(full_content)
            
            found_by_inline = False
            if inline_tag_to_search_pattern.search(body_for_inline_check):
                 found_by_inline = True

            found_by_frontmatter = False
            if frontmatter:
                if 'labels' in frontmatter:
                    fm_labels = frontmatter['labels']
                    if isinstance(fm_labels, list) and selected_tag_name in fm_labels:
                        found_by_frontmatter = True
                    elif isinstance(fm_labels, str) and selected_tag_name == fm_labels:
                        found_by_frontmatter = True
                
                if not found_by_frontmatter and 'tags' in frontmatter:
                    fm_tags = frontmatter['tags']
                    if isinstance(fm_tags, list) and selected_tag_name in fm_tags:
                        found_by_frontmatter = True
                    elif isinstance(fm_tags, str) and selected_tag_name == fm_tags:
                        found_by_frontmatter = True
            
            if found_by_inline or found_by_frontmatter:
                tagged_notes_data.append((file_path_obj, full_content))
        except Exception as e:
            print(f"Warning: Error reading/processing {file_path_obj.name} for merging: {e}")
    return tagged_notes_data

def main():
    # 1. Scan for all tags
    print(f"Scanning all notes in '{VAULT_DIR}' for available tags...")
    available_tags = scan_for_all_tags(VAULT_DIR)

    if not available_tags:
        print("No tags found in the vault. Exiting.")
        return

    print("\nAvailable tags found:")
    for i, tag_name in enumerate(available_tags):
        print(f"  {i+1}. {tag_name}")
    
    # 2. Get user choice for the tag
    chosen_index = -1
    while True:
        try:
            choice_str = input(f"\nEnter the number of the tag to merge (1-{len(available_tags)}): ")
            chosen_index = int(choice_str) - 1
            if 0 <= chosen_index < len(available_tags):
                break
            else:
                print("Invalid choice. Please enter a number from the list.")
        except ValueError:
            print("Invalid input. Please enter a number.")

    selected_tag_name = available_tags[chosen_index] # This is the tag name without a leading '#'
    print(f"\nYou selected tag: '{selected_tag_name}'")

    # 3. Set dynamic filenames and titles
    sanitized_tag_name_for_filename = "".join(c if c.isalnum() or c in (' ', '-') else '_' for c in selected_tag_name)
    # Replace spaces with underscores for a cleaner filename if spaces were allowed in tag name (they are not by regex)
    sanitized_tag_name_for_filename = sanitized_tag_name_for_filename.replace(' ', '_')

    merged_note_title = f"Consolidated {selected_tag_name}"
    merged_note_filename = f"Consolidated_{sanitized_tag_name_for_filename}.md"


    # 4. Find notes with the selected tag
    print(f"\nScanning notes for items related to tag '{selected_tag_name}'...")
    notes_to_merge_data = get_notes_by_selected_tag(VAULT_DIR, selected_tag_name)

    if not notes_to_merge_data:
        print(f"No notes found for tag '{selected_tag_name}'. Nothing to merge. Exiting.")
        return

    print(f"Found {len(notes_to_merge_data)} notes to merge for tag '{selected_tag_name}'.")

    # 5. Merge logic
    merged_content_parts = []
    original_file_paths_to_delete = []
    
    # Pattern to remove the selected tag if it appears inline in the content body.
    # This should match #tagname, ensuring it's the whole tag.
    tag_to_remove_from_body_pattern = re.compile(r'#' + re.escape(selected_tag_name) + r'(?![^\s#])', re.IGNORECASE)


    for file_path_obj, full_content in notes_to_merge_data:
        original_file_paths_to_delete.append(file_path_obj)
        
        _, body_for_merging = parse_frontmatter_and_body(full_content)
        
        cleaned_body = tag_to_remove_from_body_pattern.sub("", body_for_merging).strip()
        
        merged_content_parts.append(f"## Content from: {file_path_obj.name}\n\n{cleaned_body}\n\n---")

    final_merged_body = "\n".join(merged_content_parts).strip()
    # Ensure the last entry also has a separator if content exists and it wasn't just an empty note
    if final_merged_body and not final_merged_body.endswith("\n---"):
         final_merged_body += "\n---" 

    new_frontmatter_dict = {
        'title': merged_note_title,
        'labels': [selected_tag_name], # Add the merged tag to labels (or 'tags' key if preferred)
        'tags': [selected_tag_name],   # Also add to 'tags' for broader compatibility
        'archived': False,
        'trashed': False,
        'pinned': False
    }
    
    yaml_frontmatter_str = ""
    try:
        # Ensure consistent key order for better diffs if the file is modified later
        yaml_frontmatter_str = f"---\n{yaml.dump(new_frontmatter_dict, sort_keys=True, allow_unicode=True, Dumper=yaml.SafeDumper)}---\n"
    except TypeError: # Fallback if Dumper arg isn't supported in older PyYAML or specific setup
        yaml_frontmatter_str = f"---\n{yaml.dump(new_frontmatter_dict, sort_keys=True, allow_unicode=True)}---\n"
    except Exception as e:
        print(f"Warning: Error generating YAML frontmatter: {e}. Using basic dump.")
        # Basic fallback
        yaml_frontmatter_str = f"---\ntitle: {merged_note_title}\nlabels:\n  - {selected_tag_name}\ntags:\n  - {selected_tag_name}\narchived: false\ntrashed: false\npinned: false\n---\n"


    new_note_full_content = yaml_frontmatter_str + final_merged_body
    new_note_path = Path(VAULT_DIR) / merged_note_filename
    
    if new_note_path in original_file_paths_to_delete:
        print(f"Warning: The target merged file '{new_note_path.name}' is also one of the source files.")
        print("It will be overwritten. If this is a re-run, previous merged content might be lost from it.")

    try:
        with open(new_note_path, 'w', encoding='utf-8') as file:
            file.write(new_note_full_content)
        print(f"\nSuccessfully created/updated merged note: {new_note_path}")
    except Exception as e:
        print(f"Error writing new note {new_note_path}: {e}")
        print("Aborting before deleting original files.")
        return

    print("\nDeleting original tagged notes...")
    deleted_count = 0
    for file_path_obj in original_file_paths_to_delete:
        if file_path_obj.resolve() == new_note_path.resolve():
            print(f"Skipping deletion of '{file_path_obj.name}' as it is the merged target file.")
            continue
        try:
            os.remove(file_path_obj)
            print(f"Deleted: {file_path_obj.name}")
            deleted_count += 1
        except Exception as e:
            print(f"Error deleting file {file_path_obj.name}: {e}")
            
    print(f"\nCompleted. Merged {len(notes_to_merge_data)} notes into '{merged_note_filename}'.")
    print(f"Deleted {deleted_count} original notes.")

if __name__ == "__main__":
    try:
        import yaml
    except ImportError:
        print("PyYAML library is not installed. Please install it by running: pip install PyYAML")
        exit(1)
    main() 