# sortntag.py - Automated Tagging for Markdown Notes

This script helps you automatically tag your markdown notes in the KeepVault folder using Google's Gemini AI.

## Prerequisites

- Python 3.6 or higher
- A Google Gemini API key (get one from [Google AI Studio](https://makersuite.google.com/app/apikey))

## Setup

1. Make sure you have the required Python packages installed:

```bash
pip install -r requirements.txt
```

2. Create a `.env` file in the root directory (if it doesn't already exist) and add your Gemini API key:

```
GEMINI_API_KEY="your_gemini_api_key_here"
```

## Usage

Run the script with Python:

```bash
python sortntag.py
```

This will:
1. Read all the markdown files in the KeepVault folder
2. For each note without tags, call the Gemini API to generate relevant thematic tags
3. Update the note's frontmatter with the new tags

### Command Line Options

The script supports several command line options:

- `--force`: Re-tag notes that already have tags (replaces existing tags)
- `--append-tags`: Process notes that already have tags, but keeps existing tags and adds new ones
- `--dry-run`: Don't actually update any files, just show what would happen
- `--debug`: Enable debug logging for more detailed output
- `--api-key KEY`: Provide the Gemini API key directly (overrides the .env file)
- `--limit N`: Process only the first N files
- `--file PATTERN`: Process only files matching the given pattern
- `--language LANG`: Set the language for tags (default: english)
- `--collect-tags`: Collect all existing tags in your notes and save to tags.json
- `--model MODEL`: Select which Gemini model to use (default: 2.0-flash-lite)
- `--batch-size N`: Number of notes to process in each batch (default: 5)

### Model Options

The script supports multiple Gemini models with different rate limits:

- `2.0-flash-lite`: 30 RPM (requests per minute) - Good for faster processing
- `2.0-flash`: 15 RPM, higher quality responses
- `1.5-flash`: 15 RPM, alternative model

### Examples

```bash
# Tag all notes that don't have tags yet
python sortntag.py

# Re-tag all notes, even those that already have tags
python sortntag.py --force

# Keep existing tags and add new ones
python sortntag.py --append-tags

# Test what would happen without making any changes
python sortntag.py --dry-run

# Process only a specific file
python sortntag.py --file "KeepVault/myfile.md"

# Process all files with "project" in their name
python sortntag.py --file "KeepVault/*project*.md"

# Process at most 5 files
python sortntag.py --limit 5

# Request tags in English for all notes, even if content is in another language
python sortntag.py --language english

# Use the faster model with larger batch size for better performance
python sortntag.py --model 2.0-flash-lite --batch-size 10

# Collect existing tags from all notes to build a tag dictionary
python sortntag.py --collect-tags

# Append new tags while preserving existing ones
python sortntag.py --append-tags --file "KeepVault/myfile.md"
```

## How It Works

The script uses a straightforward approach:

1. It reads each markdown file and extracts its content
2. It sends the content to the Gemini API with a carefully crafted prompt
3. The prompt asks Gemini to analyze the content and provide 3-7 relevant thematic tags
4. Tags are specified to be lowercase with hyphens (e.g., "machine-learning")
5. The resulting tags are added to the YAML frontmatter of the markdown file

## Thematic Tagging System

The script is designed to create a network of interconnected notes through thematic tagging:

1. It focuses on conceptual and subject-matter tags rather than format descriptors
2. Tags prioritize themes, topics, and domains that capture the essence of the content
3. The system avoids generic descriptive tags like "reference" or "notes" in favor of topical tags
4. Tags are created to form natural connections between related notes

This approach enables rich knowledge graph visualization and discovery in tools like Obsidian:
- Easily find related content across your notes
- Discover unexpected connections between topics
- Build a personal knowledge network that grows over time

## Dynamic Tag Learning

The script builds a growing collection of tags as it processes files:

1. It starts by loading any existing tags from `tags.json` (if available)
2. For each file processed, any new tags generated are added to the collection
3. This updated collection is provided as a suggestion (not a constraint) to Gemini when tagging subsequent files
4. The tag collection is saved periodically and at the end of processing
5. This approach balances tag consistency with creative freedom for the AI

This creates a self-improving system where:
- Tag consistency improves over time
- The system learns from its own outputs
- New, creative tags can still be generated when appropriate
- No predefined tag list is needed - the system builds its own vocabulary

## Tag Preservation with --append-tags

The `--append-tags` option provides a way to preserve existing tags while adding new ones:

1. When enabled, files with existing tags will still be processed (instead of skipped)
2. The script keeps all existing tags and adds any new tags that aren't already present
3. The original tag order is preserved, with new tags added at the end
4. This allows for incremental enrichment of your note's metadata without losing manual tags

This is particularly useful for:
- Enriching tags on notes that were tagged manually 
- Running the script with different prompts or models to incrementally improve tagging
- Preserving carefully crafted manual tags while still getting AI assistance

## Rate Limiting & Performance

The script implements sophisticated rate limiting to stay within API quotas:

- Automatically respects each model's requests-per-minute (RPM) limits
- Processes notes in batches for efficiency
- Dynamically waits when necessary to avoid exceeding quotas
- Provides model selection to balance quality vs. speed

## Language Enforcement & Translation

For English tags, the script includes:

- Strong language enforcement in the prompt
- Automatic detection and translation of French tags
- A growing dictionary of common translations
- Logging of translated tags for transparency

This ensures consistent English tagging even when processing notes in other languages.

## Features

- **Thematic tagging**: Creates meaningful connections between notes based on subject matter
- **Tag preservation**: Option to keep existing tags while adding new ones
- **Language specification**: Force tags to be in a specific language (e.g., English) even when the note content is in another language
- **Dynamic tag learning**: Builds and maintains a growing collection of tags as files are processed
- **Improved Unicode support**: Properly handles accented characters and special symbols in tags
- **Tag salvaging**: Attempts to save valid tags even when some tags are invalid
- **Better error handling**: More robust handling of file reading/writing errors and API responses
- **Rate limiting**: Smart throttling to stay within API quotas
- **Batch processing**: Process multiple notes efficiently
- **Model selection**: Choose the most appropriate model for your needs
- **Translation**: Automatic detection and correction of non-English tags

## Technical Details

- Uses the standard `requests` library to directly call the Gemini API
- No need for additional Google packages or complex authentication mechanisms
- Simple JSON payload/response handling for clean, maintainable code
- Unicode support for international characters in tags
- Efficient rate limiting with sliding window algorithm

## Logging

The script logs its activity to both the console and a file called `sortntag.log`. You can check this file for details about what was processed and any errors that occurred.

## Integration with Keep-Obsidian Sync

This script complements the Keep-Obsidian synchronization setup by enhancing notes with tags that make them more discoverable within Obsidian. The tags help organize and connect your notes based on their content. 