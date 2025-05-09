#!/usr/bin/env python3

import os
import re
import yaml
import glob
from pathlib import Path

# Configuration
VAULT_DIR = "KeepVault"
LINK_PATTERN = re.compile(r'\[\[(.*?)(?:\|.*?)?\]\]')  # Match Obsidian links [[Note]] or [[Note|Alias]]

def load_notes():
    """Load all notes and extract their links"""
    notes = {}
    connections = {}  # Track which notes have connections (outgoing or incoming)
    
    # Scan all markdown files, including those in subfolders
    markdown_files = glob.glob(f"{VAULT_DIR}/**/*.md", recursive=True)
    
    # Skip archived and trashed notes
    markdown_files = [f for f in markdown_files if "Archived" not in f and "Trashed" not in f]
    
    for file_path in markdown_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                
                # Extract filename without extension
                filename = os.path.basename(file_path)
                note_name = os.path.splitext(filename)[0]
                
                # Store the note
                notes[note_name] = {
                    'path': file_path,
                    'content': content,
                    'outgoing_links': []
                }
                
                # Find all links in the content
                links = LINK_PATTERN.findall(content)
                if links:
                    notes[note_name]['outgoing_links'] = links
                    connections[note_name] = True  # This note has outgoing links
                    
                    # Register incoming links for the targets
                    for link in links:
                        connections[link] = True  # The target note has an incoming link
        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    return notes, connections

def update_frontmatter(file_path, set_archived=True):
    """Update a note's frontmatter to set archived status"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Check if file has YAML frontmatter
        if content.startswith('---\n'):
            # Split the content into frontmatter and note content
            parts = content.split('---\n', 2)
            if len(parts) >= 3:
                frontmatter_text = parts[1]
                note_content = parts[2]
                
                # Parse the frontmatter
                frontmatter = yaml.safe_load(frontmatter_text)
                
                # Update the archived status
                frontmatter['archived'] = set_archived
                
                # Reconstruct the file
                new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False)}---\n{note_content}"
                
                # Write back to the file
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(new_content)
                
                return True
            
        return False
    
    except Exception as e:
        print(f"Error updating frontmatter in {file_path}: {e}")
        return False

def main():
    print(f"Scanning notes in {VAULT_DIR}...")
    notes, connections = load_notes()
    
    print(f"Found {len(notes)} notes in the vault")
    print(f"Found {len(connections)} notes with connections (links or backlinks)")
    
    # Update frontmatter of connected notes
    updated_count = 0
    for note_name in connections:
        # Find the note if it exists
        if note_name in notes:
            file_path = notes[note_name]['path']
            if update_frontmatter(file_path, set_archived=True):
                updated_count += 1
                print(f"Marked as archived: {note_name}")
    
    print(f"\nCompleted! Updated {updated_count} notes.")

if __name__ == "__main__":
    main() 