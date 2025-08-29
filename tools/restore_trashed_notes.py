#!/usr/bin/env python3
"""
Script to restore trashed notes interactively.
Goes through all notes with trashed: true and prompts user to restore them.
"""

import os
import re
import glob
from pathlib import Path

def find_trashed_notes(vault_path="KeepVault"):
    """Find all markdown files with trashed: true in their YAML front matter."""
    trashed_notes = []
    
    # Search in both main KeepVault directory and Trashed subdirectory
    patterns = [
        os.path.join(vault_path, "*.md"),
        os.path.join(vault_path, "**", "*.md")
    ]
    
    for pattern in patterns:
        for file_path in glob.glob(pattern, recursive=True):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Check if file has YAML front matter with trashed: true
                if content.startswith('---'):
                    yaml_end = content.find('---', 3)
                    if yaml_end != -1:
                        yaml_section = content[:yaml_end + 3]
                        if re.search(r'^trashed:\s*true\s*$', yaml_section, re.MULTILINE):
                            trashed_notes.append(file_path)
                            
            except Exception as e:
                print(f"Error reading {file_path}: {e}")
                
    return trashed_notes

def get_note_title(file_path):
    """Extract the title from a note's YAML front matter."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if content.startswith('---'):
            yaml_end = content.find('---', 3)
            if yaml_end != -1:
                yaml_section = content[:yaml_end]
                title_match = re.search(r'^title:\s*(.+)$', yaml_section, re.MULTILINE)
                if title_match:
                    return title_match.group(1).strip()
                    
        # Fallback to filename
        return Path(file_path).stem
        
    except Exception:
        return Path(file_path).stem

def restore_note(file_path):
    """Change trashed: true to trashed: false in the file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Replace trashed: true with trashed: false
        updated_content = re.sub(r'^trashed:\s*true\s*$', 'trashed: false', content, flags=re.MULTILINE)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
            
        print(f"✅ Restored: {file_path}")
        return True
        
    except Exception as e:
        print(f"❌ Error restoring {file_path}: {e}")
        return False

def main():
    print("🗂️  Finding trashed notes...")
    trashed_notes = find_trashed_notes()
    
    if not trashed_notes:
        print("📭 No trashed notes found!")
        return
        
    print(f"📋 Found {len(trashed_notes)} trashed notes\n")
    
    restored_count = 0
    skipped_count = 0
    
    for i, file_path in enumerate(trashed_notes, 1):
        title = get_note_title(file_path)
        relative_path = os.path.relpath(file_path)
        
        print(f"[{i}/{len(trashed_notes)}] 📝 {title}")
        print(f"    📁 {relative_path}")
        
        # Show a preview of the content
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                
            # Skip YAML front matter and show first few lines of content
            content_start = 0
            for j, line in enumerate(lines):
                if line.strip() == '---' and j > 0:
                    content_start = j + 1
                    break
                    
            preview_lines = []
            for j in range(content_start, min(content_start + 3, len(lines))):
                if j < len(lines) and lines[j].strip():
                    preview_lines.append(lines[j].strip())
                    
            if preview_lines:
                print(f"    💬 Preview: {' '.join(preview_lines)[:100]}...")
                
        except Exception:
            pass
            
        # Prompt user with default 'y'
        while True:
            response = input(f"    🤔 Restore this note? [Y/n]: ").strip().lower()
            
            if response == '' or response == 'y' or response == 'yes':
                if restore_note(file_path):
                    restored_count += 1
                break
            elif response == 'n' or response == 'no':
                print(f"    ⏭️  Skipped: {relative_path}")
                skipped_count += 1
                break
            else:
                print("    ❓ Please enter 'y' for yes or 'n' for no (default is 'y')")
                
        print()  # Empty line for readability
        
    print(f"✨ Done! Restored {restored_count} notes, skipped {skipped_count} notes.")

if __name__ == "__main__":
    main() 