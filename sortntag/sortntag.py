import os
import glob
import yaml
import re
import logging
import time
import json
import requests
import sys
import io
from dotenv import load_dotenv
from pathlib import Path
from datetime import datetime
from collections import deque

# Create a safe unicode-aware console handler for Windows systems
class SafeStreamHandler(logging.StreamHandler):
    def __init__(self, stream=None):
        # Use stdout by default
        super().__init__(stream or sys.stdout)
    
    def emit(self, record):
        try:
            msg = self.format(record)
            try:
                # Try to write normally first
                self.stream.write(msg + self.terminator)
            except UnicodeEncodeError:
                # Handle Unicode encode errors by replacing problematic characters
                safe_msg = msg.encode(self.stream.encoding, errors='replace').decode(self.stream.encoding)
                self.stream.write(safe_msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# File handler - ensure utf-8 encoding
file_handler = logging.FileHandler("sortntag.log", encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(file_handler)

# Console handler - handle unicode safely
console_handler = SafeStreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(console_handler)

# Constants
VAULT_DIR = "KeepVault"
ARCHIVED_DIR = os.path.join(VAULT_DIR, "Archived")
TRASHED_DIR = os.path.join(VAULT_DIR, "Trashed")
TAGS_FILE = "tags.json"

# API configuration
GEMINI_MODELS = {
    "2.0-flash": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
        "rpm": 15,  # Requests per minute
        "tpm": 1000000,  # Tokens per minute
        "rpd": 1500  # Requests per day
    },
    "2.0-flash-lite": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-lite:generateContent",
        "rpm": 30,
        "tpm": 1000000,
        "rpd": 1500
    },
    "1.5-flash": {
        "url": "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent",
        "rpm": 15,
        "tpm": 250000,
        "rpd": 500
    }
}

# Default model
DEFAULT_MODEL = "2.0-flash-lite"  # Higher RPM (30 vs 15)

class RateLimiter:
    """Rate limiter for API calls"""
    def __init__(self, rpm, window_size=60):
        self.rpm = rpm
        self.window_size = window_size
        self.request_times = deque()
        
    def wait_if_needed(self):
        """Wait if we're exceeding our rate limit"""
        current_time = time.time()
        
        # Remove requests older than our window
        while self.request_times and self.request_times[0] < current_time - self.window_size:
            self.request_times.popleft()
        
        # Check if we're at the limit
        if len(self.request_times) >= self.rpm:
            # Calculate wait time based on the oldest request
            wait_time = self.window_size - (current_time - self.request_times[0])
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.2f} seconds")
                time.sleep(wait_time)
        
        # Record this request
        self.request_times.append(time.time())

def parse_args():
    """Parse command line arguments"""
    import argparse
    parser = argparse.ArgumentParser(description="Tag markdown notes using Gemini AI")
    parser.add_argument("--force", action="store_true", help="Force retagging notes that already have tags")
    parser.add_argument("--append-tags", action="store_true", help="Keep existing tags and add new ones instead of replacing them")
    parser.add_argument("--dry-run", action="store_true", help="Don't write tags to files, just show what would happen")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--api-key", help="Gemini API key (overrides .env file)")
    parser.add_argument("--limit", type=int, help="Limit the number of files to process")
    parser.add_argument("--file", help="Process a specific file or glob pattern")
    parser.add_argument("--collect-tags", action="store_true", help="Collect all existing tags and save to tags.json")
    parser.add_argument("--language", default="english", help="Language for tags (default: english)")
    parser.add_argument("--model", default=DEFAULT_MODEL, choices=GEMINI_MODELS.keys(), help=f"Gemini model to use (default: {DEFAULT_MODEL})")
    parser.add_argument("--batch-size", type=int, default=5, help="Number of notes to process in parallel (default: 5)")
    parser.add_argument("--input-file-list", help="Path to a text file containing a list of markdown files to process (one file per line).")
    return parser.parse_args()

def load_api_key(cmd_api_key=None):
    """Load Gemini API key from command line args or .env file"""
    # First check command line argument
    if cmd_api_key:
        return cmd_api_key
    
    # Then check .env file
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not found in .env file")
    return api_key

def get_prompt(language="english", existing_tags=None):
    """Return a carefully crafted prompt for the Gemini model"""
    # Add existing tags as suggestions, but emphasize creativity
    tag_suggestion = ""
    if existing_tags and len(existing_tags) > 0:
        # Take a sample of existing tags to avoid overwhelming the model
        sample_size = min(20, len(existing_tags))
        sample_tags = existing_tags[:sample_size]
        tag_suggestion = f"""
Some tags already used in the system include: {', '.join(sample_tags)}.
Feel free to use these if they fit well, but don't hesitate to create new tags if they better capture the content.
Prefer using existing tags when appropriate to build connections between related notes.
"""
    
    # English-specific emphasis
    english_emphasis = ""
    if language.lower() == "english":
        english_emphasis = """
CRITICAL REQUIREMENT: ALL TAGS MUST BE IN ENGLISH ONLY. 
- Do NOT provide tags in French, Spanish, or any other language
- Translate any non-English concepts into their English equivalents
- If you're unsure of a translation, use a more general English term instead
"""
    
    prompt = f"""
You are an expert tagger and categorizer of personal notes. Your task is to analyze the given note content and assign the most relevant THEMATIC tags that capture its essence and create connections to related topics.

CONTEXT:
This is part of a note-taking system that bridges Google Keep and Obsidian. The notes are personal and cover a wide range of topics including:
- Personal projects and tasks
- Learning materials and research
- Ideas and concepts
- Notes from readings or conversations
- Reference materials and links

INSTRUCTIONS:
1. Analyze the content of the note provided below.
2. Return ONLY a comma-separated list of 3-7 relevant thematic tags for the note.
3. Focus on CONCEPTUAL and THEMATIC tags that relate to the subject matter, NOT format or type descriptors.
4. Prioritize tags that could link this note to other related notes on similar topics or themes.
5. Be specific but not too granular - prefer broader thematic concepts when possible.
6. Use lowercase tags with hyphens instead of spaces (example: "machine-learning", "project-ideas").
7. IMPORTANT: All tags MUST be in {language}, even if the content is in another language.
8. DO NOT include introductory text or explanations in your response - ONLY the comma-separated list of tags.
9. Avoid purely descriptive tags like "reference-material" or "notes" - focus on the SUBJECT MATTER instead.

EXAMPLES:
- For a note about programming in Python: "python, data-analysis, coding, algorithms" (NOT "tutorial" or "reference")
- For a book note: "philosophy, ethics, ancient-greece" (NOT "book-notes" or "summary")
- For a work idea: "project-management, agile, team-organization" (NOT "work-notes" or "idea")

{english_emphasis}
{tag_suggestion}
NOTE CONTENT:
"""
    return prompt

def load_existing_tags():
    """Load existing tags from JSON file if it exists"""
    if os.path.exists(TAGS_FILE):
        try:
            with open(TAGS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading tags from {TAGS_FILE}: {e}")
    return []

def save_tags(tags):
    """Save tags to JSON file"""
    try:
        with open(TAGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted(list(tags)), f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error(f"Error saving tags to {TAGS_FILE}: {e}")
        return False

def collect_existing_tags(md_files):
    """Collect all existing tags from the md files"""
    all_tags = set()
    tagged_files = 0
    
    for file_path in md_files:
        frontmatter, _ = extract_frontmatter_and_content(file_path)
        if 'tags' in frontmatter and isinstance(frontmatter['tags'], list):
            tagged_files += 1
            all_tags.update(frontmatter['tags'])
    
    logger.info(f"Found {len(all_tags)} unique tags in {tagged_files} files")
    
    # Save to a file
    save_tags(all_tags)
    
    return sorted(list(all_tags))

def find_md_files(specific_file=None, input_file_list=None):
    logger.info(f"Finding markdown files. Specific_file: {specific_file}, Input_file_list: {input_file_list}")
    md_files = []
    if input_file_list:
        logger.info(f"Processing files from input list: {input_file_list}")
        try:
            with open(input_file_list, 'r', encoding='utf-8') as f:
                for line in f:
                    filename = line.strip()
                    if filename:
                        # Assume filenames in the list are relative to VAULT_DIR
                        # or could be absolute.
                        # The unprocessed_files.txt contains names like "My Note.md"
                        # which are expected to be in VAULT_DIR.
                        potential_path = os.path.join(VAULT_DIR, filename)
                        if os.path.exists(potential_path) and potential_path.endswith((".md", ".MD")): # Check for .MD as well
                            md_files.append(potential_path)
                        elif os.path.exists(filename) and filename.endswith((".md", ".MD")): # Check if it's an absolute path
                            md_files.append(filename)
                        else:
                            logger.warning(f"File {filename} from list not found or not a markdown file. Searched: {potential_path} and as absolute.")
        except FileNotFoundError:
            logger.error(f"Input file list {input_file_list} not found.")
            return [] # Return empty list if file not found
        logger.info(f"Found {len(md_files)} files from input list.")

    elif specific_file:
        # Handle glob patterns for specific files
        # Try relative to VAULT_DIR first
        logger.info(f"Processing specific file/glob pattern: {specific_file} relative to {VAULT_DIR}")
        md_files = [f for f in glob.glob(os.path.join(VAULT_DIR, specific_file), recursive=True) if f.endswith((".md", ".MD"))]
        if not md_files:
            # Try absolute path if no files found in vault_dir
            logger.info(f"No files found with pattern relative to vault. Trying absolute path for: {specific_file}")
            md_files = [f for f in glob.glob(specific_file, recursive=True) if f.endswith((".md", ".MD"))]
        logger.info(f"Found {len(md_files)} files from specific_file/glob.")
    else:
        logger.info(f"Processing all files in {VAULT_DIR}")
        md_files = [os.path.join(root, name)
                    for root, dirs, files in os.walk(VAULT_DIR)
                    for name in files
                    if name.endswith((".md", ".MD"))]
        logger.info(f"Found {len(md_files)} files from walking VAULT_DIR.")
    
    # Exclude files in Archived and Trashed directories
    # This part needs to be careful if md_files contains absolute paths already outside VAULT_DIR.
    # However, for this use case, unprocessed_files.txt lists files intended to be in VAULT_DIR.

    original_count = len(md_files)
    md_files = [f for f in md_files if ARCHIVED_DIR not in os.path.abspath(f) and TRASHED_DIR not in os.path.abspath(f)]
    excluded_count = original_count - len(md_files)
    if excluded_count > 0:
        logger.info(f"Excluded {excluded_count} files from Archived or Trashed directories.")

    # Further filter: remove files that already have tags if --force is not used
    # This logic might need adjustment depending on when it's called relative to reading args.
    # For now, assuming args are available or this is handled later.

    if not md_files:
        logger.info("No markdown files found to process.")
    else:
        logger.info(f"Found {len(md_files)} markdown files to process (after exclusions).")
    return md_files

def extract_frontmatter_and_content(file_path):
    """Extract YAML frontmatter and content from a markdown file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check if the file has frontmatter
        frontmatter_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
        if frontmatter_match:
            frontmatter_str = frontmatter_match.group(1)
            try:
                frontmatter = yaml.safe_load(frontmatter_str)
                # Get the content after the frontmatter
                remaining_content = content[frontmatter_match.end():]
            except yaml.YAMLError as e:
                logger.error(f"Error parsing frontmatter in {file_path}: {e}")
                frontmatter = {}
                remaining_content = content
        else:
            frontmatter = {}
            remaining_content = content
        
        return frontmatter, remaining_content
    except Exception as e:
        logger.error(f"Error reading file {file_path}: {e}")
        return {}, ""

def validate_and_fix_english_tags(tags, filename):
    """Validate tags are in English and fix common French words"""
    # Common French words that need to be translated
    french_to_english = {
        "philosophie": "philosophy",
        "conscience": "consciousness",
        "voyage": "travel",
        "rêves-lucides": "lucid-dreams",
        "symbolisme": "symbolism",
        "non-dualité": "non-duality",
        "cybersécurité": "cybersecurity",
        "informatique": "computing",
        "recherches": "research",
        "certifications": "certifications",
        "france": "france",  # Keep country names as is
        "ia": "ai",
        "alliance-confiance-numerique": "digital-trust-alliance",
        "cybersecurity": "cybersecurity"  # Already English, keep as is
    }
    
    fixed_tags = []
    
    for tag in tags:
        # Check if this tag needs translation
        if tag.lower() in french_to_english:
            fixed_tag = french_to_english[tag.lower()]
            logger.info(f"Translated tag '{tag}' to '{fixed_tag}' for {filename}")
            fixed_tags.append(fixed_tag)
        else:
            fixed_tags.append(tag)
    
    return fixed_tags

def get_tags_from_gemini(api_key, content, filename, language="english", existing_tags=None, model_config=None, rate_limiter=None):
    """Get tags from Gemini AI with retry logic"""
    if not model_config:
        model_config = GEMINI_MODELS[DEFAULT_MODEL]

    api_url = model_config["url"]
    
    # Prepare prompt and payload
    prompt = get_prompt(language, existing_tags)
    full_content = prompt + content + "\n"

    payload = {
        "contents": [{
            "parts": [{"text": full_content}]
        }],
        "generationConfig": {
            "temperature": 0.4, # Adjust for creativity vs. consistency
            "topK": 10,         # Consider adjusting
            "topP": 0.95,       # Consider adjusting
            "maxOutputTokens": 100,
            "stopSequences": []
        },
        "safetySettings": [ # More permissive safety settings
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]
    }

    headers = {
        'Content-Type': 'application/json',
        'x-goog-api-key': api_key
    }

    max_retries = 3
    base_backoff_seconds = 10 # Initial wait time for retries

    for attempt in range(max_retries):
        if rate_limiter:
            rate_limiter.wait_if_needed()

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=60) # Added timeout
            
            if response.status_code == 200:
                try:
                    response_json = response.json()
                    if "candidates" in response_json and response_json["candidates"]:
                        tags_text = response_json["candidates"][0]["content"]["parts"][0]["text"]
                        # Sanitize tags: lowercase, strip whitespace, remove empty tags
                        tags = [tag.strip().lower() for tag in tags_text.split(',') if tag.strip()]
                        
                        # Validate and fix English tags if necessary
                        if language.lower() == "english":
                            tags = validate_and_fix_english_tags(tags, filename)

                        if not tags:
                            logger.warning(f"Gemini returned empty or invalid tags for {filename}: {tags_text}")
                            return None 
                        return tags
                    else:
                        logger.warning(f"No candidates in response for {filename}: {response_json}")
                        # This could be a retryable condition depending on the exact response,
                        # but for now, treat as failure for this attempt.
                        # If it was a 503/429, it would be caught by the status_code check below.
                        # This handles cases where 200 OK but payload is not as expected.
                        error_detail = response_json.get("error", {}).get("message", "Unexpected response structure")
                        logger.error(f"Error with Gemini API response structure for {filename}: {error_detail}")
                        # No explicit retry here, let the loop handle it if it's the last attempt or a general error occurs

                except (json.JSONDecodeError, KeyError, IndexError) as e:
                    logger.error(f"Error parsing Gemini response for {filename}: {e}. Response text: {response.text[:500]}")
                    # This is likely not a retryable server error, so break or handle as last attempt.
                    if attempt == max_retries -1:
                        return None # Failed after all retries
                    # Continue to next attempt, maybe it was a transient parsing issue with the response body? Unlikely.
                    # For safety, let's treat parsing errors as non-retryable for now, unless they are clearly transient.

            # Specific retryable error codes
            elif response.status_code in [429, 500, 503, 504]: # Added 500, 504
                logger.warning(f"Gemini API returned {response.status_code} for {filename}. Attempt {attempt + 1}/{max_retries}. Retrying in {base_backoff_seconds * (2**attempt)}s...")
                time.sleep(base_backoff_seconds * (2**attempt)) # Exponential backoff
                # Continue to next iteration of the loop for retry
            
            # Non-retryable client errors (4xx, excluding 429) or other unexpected server errors
            else:
                error_message = f"Error calling Gemini API for {filename}: {response.status_code} - {response.text[:500]}"
                logger.error(error_message)
                return None # Do not retry for other client errors or unhandled server errors

        except requests.exceptions.RequestException as e: # Catch network/connection errors
            logger.error(f"Error getting tags for {filename}: {e}")
            if attempt < max_retries - 1:
                logger.warning(f"Network/Request error for {filename}. Attempt {attempt + 1}/{max_retries}. Retrying in {base_backoff_seconds * (2**attempt)}s...")
                time.sleep(base_backoff_seconds * (2**attempt)) # Exponential backoff
            else:
                logger.error(f"Failed to get tags for {filename} after {max_retries} attempts due to network/request errors.")
                return None # Failed all retries for network errors
        
        # If loop continues, it means a retry is happening.

    logger.error(f"Failed to get tags for {filename} after {max_retries} attempts.")
    return None # Return None if all retries fail

def update_note_with_tags(file_path, frontmatter, content, tags, dry_run=False, append_tags=False):
    """Update the note file with the new tags"""
    # If append_tags is True, merge existing tags with new ones
    if append_tags and 'tags' in frontmatter and isinstance(frontmatter['tags'], list):
        existing_tags = frontmatter['tags']
        # Combine tags and remove duplicates while preserving order
        combined_tags = []
        # Add existing tags first
        for tag in existing_tags:
            if tag not in combined_tags:
                combined_tags.append(tag)
        # Then add new tags
        for tag in tags:
            if tag not in combined_tags:
                combined_tags.append(tag)
        tags = combined_tags
        logger.info(f"Appended tags, now has {len(tags)} tags: {', '.join(tags)}")
    else:
        # Otherwise, just replace the tags
        frontmatter['tags'] = tags
    
    # Add or update the tags in the frontmatter
    frontmatter['tags'] = tags
    
    # Create the updated content
    updated_content = "---\n" + yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True) + "---\n" + content
    
    if dry_run:
        if append_tags:
            logger.info(f"DRY RUN: Would update with appended tags to {file_path}: {', '.join(tags)}")
        else:
            logger.info(f"DRY RUN: Would write tags to {file_path}: {', '.join(tags)}")
        return True
        
    # Write back to the file
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        return True
    except Exception as e:
        logger.error(f"Error writing file {file_path}: {e}")
        return False

def process_files_batch(files_to_process, api_key, language, existing_tags, model_config, rate_limiter, dry_run=False, append_tags=False):
    """Process a batch of files and return updated tag collection"""
    all_tags = set(existing_tags)
    processed_count = 0
    
    for file_data in files_to_process:
        file_path = file_data["path"]
        frontmatter = file_data["frontmatter"]
        content = file_data["content"]
        filename = os.path.basename(file_path)
        
        # Get tags from Gemini
        tags = get_tags_from_gemini(
            api_key, 
            content, 
            filename, 
            language, 
            sorted(list(all_tags)), 
            model_config,
            rate_limiter
        )
        
        if tags:
            logger.info(f"Got tags for {filename}: {', '.join(tags)}")
            
            # Update the note with the tags
            if update_note_with_tags(file_path, frontmatter, content, tags, dry_run, append_tags):
                processed_count += 1
                
                # Add new tags to our collection if not in dry-run mode
                if not dry_run:
                    all_tags.update(tags)
        else:
            logger.warning(f"No valid tags obtained for {filename}")
    
    return processed_count, all_tags

def main():
    try:
        # Parse command line arguments
        args = parse_args()
        
        # Configure logging based on arguments
        if args.debug:
            logger.setLevel(logging.DEBUG)
            logger.debug("Debug logging enabled")
            
        # Load API key
        api_key = load_api_key(args.api_key)
        logger.info("Loaded Gemini API key")
        
        # Set up model configuration
        model_config = GEMINI_MODELS.get(args.model, GEMINI_MODELS[DEFAULT_MODEL])
        logger.info(f"Using model: {args.model} (RPM: {model_config['rpm']}, TPM: {model_config['tpm']})")
        
        # Set up rate limiter
        rate_limiter = RateLimiter(model_config["rpm"])
        
        # Find markdown files
        md_files = find_md_files(args.file, args.input_file_list)
        
        # Initialize collection of all tags
        all_tags = set()
        
        # Collect existing tags if requested or load them if file exists
        if args.collect_tags:
            existing_tags = collect_existing_tags(md_files)
            all_tags.update(existing_tags)
        else:
            existing_tags = load_existing_tags()
            all_tags.update(existing_tags)
            logger.info(f"Loaded {len(existing_tags)} existing tags from {TAGS_FILE}")
        
        # Apply limit if specified
        if args.limit and args.limit > 0:
            md_files = md_files[:args.limit]
            logger.info(f"Limited to {args.limit} files")
        
        # Prepare files for batch processing
        files_to_process = []
        for file_path in md_files:
            filename = os.path.basename(file_path)
            logger.info(f"Processing {filename}")
            
            # Extract frontmatter and content
            frontmatter, content = extract_frontmatter_and_content(file_path)
            
            # If this file already has tags, add them to our collection
            if 'tags' in frontmatter and isinstance(frontmatter['tags'], list) and frontmatter['tags']:
                all_tags.update(frontmatter['tags'])
            
            # Skip files that already have tags unless --force is used or --append-tags is used
            if 'tags' in frontmatter and not (args.force or args.append_tags):
                logger.info(f"Skipping {filename} - already has tags")
                continue
                
            # Skip empty files
            if not content.strip():
                logger.info(f"Skipping {filename} - empty content")
                continue
            
            # Add to processing queue
            files_to_process.append({
                "path": file_path,
                "frontmatter": frontmatter,
                "content": content
            })
        
        # Process files in batches
        processed_count = 0
        batch_size = min(args.batch_size, model_config["rpm"])  # Don't exceed RPM limit
        
        for i in range(0, len(files_to_process), batch_size):
            batch = files_to_process[i:i+batch_size]
            logger.info(f"Processing batch of {len(batch)} files")
            
            batch_count, updated_tags = process_files_batch(
                batch,
                api_key,
                args.language,
                all_tags,
                model_config,
                rate_limiter,
                args.dry_run,
                args.append_tags
            )
            
            processed_count += batch_count
            all_tags.update(updated_tags)
            
            # Save updated tags periodically
            if processed_count % 10 == 0 and not args.dry_run and all_tags:
                save_tags(all_tags)
        
        # Save final tag collection
        if not args.dry_run and all_tags:
            save_tags(all_tags)
            
        logger.info(f"Processed {processed_count} out of {len(md_files)} files")
        logger.info(f"Current tag collection has {len(all_tags)} unique tags")
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}")
        raise

if __name__ == "__main__":
    main() 