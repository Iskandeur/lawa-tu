#!/usr/bin/env python3
"""
Script to remove tags from Obsidian notes if they are only used in a single note.
This script scans all markdown files in the vault, identifies tags used only once,
and removes them from those notes.
"""

import os
import re
import yaml
import glob
from collections import defaultdict
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    filename='tag_cleanup.log',
    filemode='w'
)
console = logging.StreamHandler()
console.setLevel(logging.INFO)
logging.getLogger('').addHandler(console)

class ObsidianVaultCleaner:
    def __init__(self, vault_path="KeepVault"):
        self.vault_path = vault_path
        self.tag_usage = defaultdict(list)
        self.single_use_tags = set()
        self.total_tags_before = 0
        self.total_tags_after = 0

    def scan_vault(self):
        """Scan all markdown files in the vault to count tag usage."""
        logging.info(f"Scanning vault at {self.vault_path}")
        
        # Find all markdown files in the vault (including subdirectories)
        markdown_files = []
        for root, _, files in os.walk(self.vault_path):
            for file in files:
                if file.endswith('.md'):
                    markdown_files.append(os.path.join(root, file))
        
        logging.info(f"Found {len(markdown_files)} markdown files")
        
        # Process each file to extract tags
        for file_path in markdown_files:
            self._process_file_tags(file_path)
        
        # Identify tags used only once
        for tag, files in self.tag_usage.items():
            if len(files) == 1:
                self.single_use_tags.add(tag)
        
        self.total_tags_before = len(self.tag_usage)
        self.total_tags_after = self.total_tags_before - len(self.single_use_tags)
        
        logging.info(f"Found {self.total_tags_before} total unique tags in the vault")
        logging.info(f"Found {len(self.single_use_tags)} tags used only once")
        logging.info(f"Single-use tags: {', '.join(sorted(self.single_use_tags))}")

    def _process_file_tags(self, file_path):
        """Extract tags from a markdown file (both YAML frontmatter and inline tags)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract tags from YAML frontmatter
            frontmatter_tags = []
            if content.startswith('---'):
                frontmatter_end = content.find('---', 3)
                if frontmatter_end != -1:
                    frontmatter = content[3:frontmatter_end].strip()
                    try:
                        metadata = yaml.safe_load(frontmatter)
                        if metadata and 'tags' in metadata:
                            if isinstance(metadata['tags'], list):
                                frontmatter_tags = metadata['tags']
                            elif isinstance(metadata['tags'], str):
                                # Handle comma-separated tags
                                frontmatter_tags = [tag.strip() for tag in metadata['tags'].split(',')]
                    except yaml.YAMLError:
                        logging.warning(f"Error parsing YAML frontmatter in {file_path}")
            
            # Extract inline tags using regex
            # Match #tag patterns but not within code blocks, URLs, or other special contexts
            inline_tags = re.findall(r'(?<![`#\w])(#[a-zA-Z0-9_-]+)', content)
            inline_tags = [tag[1:] for tag in inline_tags]  # Remove the # prefix
            
            # Combine all tags found in the file
            all_tags = set(frontmatter_tags + inline_tags)
            
            # Record which file each tag appears in
            for tag in all_tags:
                self.tag_usage[tag].append(file_path)
                
        except Exception as e:
            logging.error(f"Error processing {file_path}: {str(e)}")

    def remove_single_use_tags(self):
        """Remove tags that are only used once from their respective files."""
        if not self.single_use_tags:
            logging.info("No single-use tags to remove.")
            return
        
        modified_files = 0
        
        for tag in self.single_use_tags:
            if tag in self.tag_usage and len(self.tag_usage[tag]) == 1:
                file_path = self.tag_usage[tag][0]
                self._remove_tag_from_file(tag, file_path)
                modified_files += 1
        
        logging.info(f"Modified {modified_files} files to remove single-use tags")

    def _remove_tag_from_file(self, tag, file_path):
        """Remove a specific tag from a file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            modified = False
            
            # Handle tags in YAML frontmatter
            if content.startswith('---'):
                frontmatter_end = content.find('---', 3)
                if frontmatter_end != -1:
                    frontmatter = content[3:frontmatter_end].strip()
                    try:
                        metadata = yaml.safe_load(frontmatter)
                        if metadata and 'tags' in metadata:
                            if isinstance(metadata['tags'], list) and tag in metadata['tags']:
                                metadata['tags'].remove(tag)
                                modified = True
                                # If tags list is now empty, remove the tags field
                                if not metadata['tags']:
                                    del metadata['tags']
                            elif isinstance(metadata['tags'], str):
                                tag_list = [t.strip() for t in metadata['tags'].split(',')]
                                if tag in tag_list:
                                    tag_list.remove(tag)
                                    metadata['tags'] = ', '.join(tag_list) if tag_list else None
                                    if metadata['tags'] is None:
                                        del metadata['tags']
                                    modified = True
                        
                        # Rebuild the frontmatter
                        if modified:
                            new_frontmatter = yaml.dump(metadata, default_flow_style=False, sort_keys=False)
                            new_content = f"---\n{new_frontmatter}---\n{content[frontmatter_end+3:]}"
                            content = new_content
                    except yaml.YAMLError:
                        logging.warning(f"Error parsing YAML frontmatter in {file_path}")
            
            # Handle inline tags
            tag_pattern = r'(?<![`#\w])(#' + re.escape(tag) + r')(?!\w)'
            if re.search(tag_pattern, content):
                content = re.sub(tag_pattern, '', content)
                modified = True
            
            # Write back to the file if modified
            if modified:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                logging.info(f"Removed tag '{tag}' from {file_path}")
            else:
                logging.warning(f"Failed to locate tag '{tag}' in {file_path} for removal")
                
        except Exception as e:
            logging.error(f"Error removing tag '{tag}' from {file_path}: {str(e)}")

    def print_summary(self):
        """Print a summary of the tag cleanup operation."""
        removed_tags = len(self.single_use_tags)
        
        logging.info("\n=== Tag Cleanup Summary ===")
        logging.info(f"Total tags before cleanup: {self.total_tags_before}")
        logging.info(f"Tags removed: {removed_tags}")
        logging.info(f"Remaining tags: {self.total_tags_after}")
        logging.info("===========================")
        
        # Also print to console without logging metadata
        print("\n=== Tag Cleanup Summary ===")
        print(f"Total tags before cleanup: {self.total_tags_before}")
        print(f"Tags removed: {removed_tags}")
        print(f"Remaining tags: {self.total_tags_after}")
        print("===========================")

def main():
    cleaner = ObsidianVaultCleaner()
    cleaner.scan_vault()
    cleaner.remove_single_use_tags()
    cleaner.print_summary()
    logging.info("Tag cleanup process completed")

if __name__ == "__main__":
    main() 