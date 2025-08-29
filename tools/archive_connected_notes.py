#!/usr/bin/env python3

import os
import re
import yaml
import glob
from pathlib import Path

# Configuration
VAULT_DIR = "KeepVault"
LINK_PATTERN = re.compile(r'\[\[(.*?)(?:\|.*?)?\]\]')  # Match Obsidian links [[Note]] or [[Note|Alias]]

def parse_frontmatter(content):
    """Parse YAML frontmatter from markdown content"""
    if not content.startswith('---\n'):
        return {}, content
    
    parts = content.split('---\n', 2)
    if len(parts) < 3:
        return {}, content
    
    try:
        frontmatter = yaml.safe_load(parts[1])
        note_content = parts[2]
        return frontmatter or {}, note_content
    except yaml.YAMLError:
        return {}, content

def load_notes():
    """Load all notes and extract their links"""
    notes = {}
    title_to_filename = {}  # Map titles to filenames for link resolution
    filename_to_note = {}   # Map filenames to note data
    
    # Scan all markdown files, including those in subfolders
    markdown_files = glob.glob(f"{VAULT_DIR}/**/*.md", recursive=True)
    
    # NO LONGER SKIP archived and trashed notes - we want to process ALL files to find connections
    print(f"Found {len(markdown_files)} total markdown files to scan...")
    
    # First pass: Load all notes and build lookup tables
    for file_path in markdown_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
                
            # Extract filename without extension
            filename = os.path.basename(file_path)
            note_name = os.path.splitext(filename)[0]
            
            # Parse frontmatter
            frontmatter, note_content = parse_frontmatter(content)
            title = frontmatter.get('title', '').strip()
            
            # Store the note
            note_data = {
                'path': file_path,
                'content': content,
                'frontmatter': frontmatter,
                'note_content': note_content,
                'outgoing_links': [],
                'has_connections': False,
                'is_archived': 'Archived' in file_path,
                'is_trashed': 'Trashed' in file_path
            }
            
            notes[note_name] = note_data
            filename_to_note[note_name] = note_data
            
            # Build title mapping (if title exists and is different from filename)
            if title and title != note_name:
                title_to_filename[title] = note_name
                # Also try title with spaces replaced by underscores (common in Keep)
                title_normalized = title.replace(' ', '_')
                if title_normalized != note_name:
                    title_to_filename[title_normalized] = note_name
        
        except Exception as e:
            print(f"Error processing {file_path}: {e}")
    
    print(f"Loaded {len(notes)} notes")
    print(f"Built {len(title_to_filename)} title mappings")
    
    # Debug: Check for links in any files
    total_links = 0
    files_with_links = 0
    
    # Second pass: Find all links and establish connections
    for note_name, note_data in notes.items():
        # Find all links in the content
        links = LINK_PATTERN.findall(note_data['note_content'])
        if links:
            files_with_links += 1
            total_links += len(links)
            print(f"Found {len(links)} outgoing links in '{note_name}': {links}")
            note_data['outgoing_links'] = links
            note_data['has_connections'] = True  # This note has outgoing links
            
            # Register incoming links for the targets
            for link in links:
                # Try to resolve the link to an actual note
                target_note = None
                
                # Direct filename match (most common)
                if link in filename_to_note:
                    target_note = filename_to_note[link]
                    print(f"  Direct match: '{link}' -> '{link}'")
                
                # Title match
                elif link in title_to_filename:
                    target_filename = title_to_filename[link]
                    target_note = filename_to_note[target_filename]
                    print(f"  Title match: '{link}' -> '{target_filename}'")
                
                # Try partial matches (case insensitive)
                else:
                    # Check if any filename starts with the link text (case insensitive)
                    link_lower = link.lower()
                    for filename, note_data_target in filename_to_note.items():
                        if filename.lower() == link_lower:
                            target_note = note_data_target
                            print(f"  Case-insensitive match: '{link}' -> '{filename}'")
                            break
                    
                    # Check titles case insensitive
                    if not target_note:
                        for title, filename in title_to_filename.items():
                            if title.lower() == link_lower:
                                target_note = filename_to_note[filename]
                                print(f"  Title case-insensitive match: '{link}' -> '{filename}'")
                                break
                
                if target_note:
                    target_note['has_connections'] = True  # The target note has an incoming link
                    print(f"  ✓ Marked '{link}' as having incoming connection")
                else:
                    print(f"  ✗ Could not resolve link '{link}' - no matching note found")
    
    print(f"\nSummary: {files_with_links} files contain {total_links} total links")
    return notes

def update_frontmatter(file_path, set_archived=True):
    """Update a note's frontmatter to set archived status"""
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            content = file.read()
        
        # Parse frontmatter
        frontmatter, note_content = parse_frontmatter(content)
        
        if not frontmatter:
            print(f"  Warning: No frontmatter found in {file_path}")
            return False
        
        # Check if already archived
        if frontmatter.get('archived', False) == set_archived:
            print(f"  Already in correct state: {os.path.basename(file_path)}")
            return False
        
        # Update the archived status
        frontmatter['archived'] = set_archived
        
        # Reconstruct the file
        new_content = f"---\n{yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True)}---\n{note_content}"
        
        # Write back to the file
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(new_content)
        
        return True
    
    except Exception as e:
        print(f"Error updating frontmatter in {file_path}: {e}")
        return False

def main():
    print(f"Scanning notes in {VAULT_DIR}...")
    notes = load_notes()
    
    # Count notes with connections
    connected_notes = {name: note for name, note in notes.items() if note['has_connections']}
    
    # Separate active notes that need to be archived (exclude pinned notes)
    active_connected_notes = {
        name: note for name, note in connected_notes.items() 
        if not note['is_archived'] and not note['is_trashed'] and not note['frontmatter'].get('pinned', False)
    }
    
    print(f"\nFound {len(notes)} total notes in the vault")
    print(f"Found {len(connected_notes)} notes with connections (outgoing or incoming links)")
    print(f"Found {len(active_connected_notes)} ACTIVE notes that need to be archived (excluding pinned notes)")
    
    if not connected_notes:
        print("No connected notes found. This might indicate an issue with link detection.")
        print("\nDebugging: Checking for any [[]] patterns in first few files...")
        for i, (name, note) in enumerate(list(notes.items())[:5]):
            matches = LINK_PATTERN.findall(note['note_content'])
            if matches:
                print(f"  {name}: found links {matches}")
        return
    
    if not active_connected_notes:
        print("No active notes need archiving - all connected notes are already archived/trashed/pinned.")
        return
    
    # Show what will be updated
    print(f"\nActive notes that will be marked as archived:")
    for name, note in active_connected_notes.items():
        current_archived = note['frontmatter'].get('archived', False)
        status = "✓ already archived" if current_archived else "→ will be archived"
        print(f"  {name} {status}")
    
    # Ask for confirmation
    response = input(f"\nProceed to mark {len(active_connected_notes)} notes as archived? (y/N): ")
    if response.lower() != 'y':
        print("Operation cancelled.")
        return
    
    # Update frontmatter of connected notes
    updated_count = 0
    for note_name, note_data in active_connected_notes.items():
        file_path = note_data['path']
        if update_frontmatter(file_path, set_archived=True):
            updated_count += 1
            print(f"✓ Marked as archived: {note_name}")
    
    print(f"\nCompleted! Updated {updated_count} notes.")

if __name__ == "__main__":
    main() 