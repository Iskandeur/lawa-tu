import logging
import os
import gkeepapi
gkeepapi.node.DEBUG = True  # Enable debug logging
import keyring
import os
import getpass
import sys
import gpsoauth # Added for direct token exchange
import random # Added for random Android ID
import string # Added for random Android ID
from dotenv import load_dotenv, set_key # Added for .env support
import json # Added for JSON output
import base64 # Added for blob encoding
import hashlib # Added for generating consistent filenames
from pathlib import Path # Added for path handling
import requests # Added for downloading media from URLs
import time # Added for rate limiting
import traceback # Added for better error reporting
import mimetypes # Added for MIME type detection
import re
import shutil
from datetime import datetime, timezone
import argparse
import yaml # Use PyYAML
import glob # Added for enhanced local file checking

# --- Logging Setup ---
LOG_FILE = 'debug_sync.log'
# Clear log file at the start of the script run IF this is the main execution point
# We might need to adjust this if pull/push call each other or are modules
# For now, assume pull.py is run independently first.
if __name__ == "__main__" and os.path.exists(LOG_FILE):
    try:
        os.remove(LOG_FILE)
        print(f"Cleared old log file: {LOG_FILE}")
    except OSError as e:
        print(f"Warning: Could not clear old log file {LOG_FILE}: {e}")

logging.basicConfig(
    level=logging.DEBUG, # Capture all levels of messages
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        # Optional: Keep console output, but maybe filter it later
        # logging.StreamHandler(sys.stdout)
    ]
)
logging.info("--- pull.py execution started ---")
# --- End Logging Setup ---

# Constants
SERVICE_NAME = "google-keep-token" # Keyring service name
JSON_OUTPUT_FILE = "keep_notes.json" # File to save downloaded notes
ATTACHMENTS_DIR = "KeepVault/Attachments" # Directory for downloaded blobs/attachments
CACHE_FILE = "keep_state.json" # File to store cached note data
DEBUG = False # Set to False to disable detailed debugging output

# Constants from process_notes.py
VAULT_DIR = "KeepVault"            # Root directory for the Obsidian vault
ATTACHMENTS_VAULT_DIR = os.path.join(VAULT_DIR, "Attachments") # Unified attachments dir
ARCHIVED_DIR = os.path.join(VAULT_DIR, "Archived")          # Subdirectory for archived notes
TRASHED_DIR = os.path.join(VAULT_DIR, "Trashed")            # Subdirectory for trashed notes
MAX_FILENAME_LENGTH = 90          # Limit filename length (reduced for safety)
# Windows reserved names (case-insensitive)
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# Helper function to generate metadata dictionary
def _generate_metadata(blob_id, filename, blob_type, file_ext, blob):
    metadata = {
        'id': blob_id,
        'filename': filename,
        'type': blob_type,
        'extension': file_ext,
        'extracted_text': None
    }
    if hasattr(blob, 'extracted_text'):
        metadata['extracted_text'] = blob.extracted_text
    return metadata

def get_master_token(email):
    """
    Attempts to retrieve the master token from keyring.
    If not found, prompts the user for an OAuth token and uses gpsoauth to exchange it.
    Stores the successfully obtained token in keyring if possible.
    """
    try:
        master_token = keyring.get_password(SERVICE_NAME, email)
        if master_token:
            print(f"Found master token for {email} in keyring.")
            return master_token
    except keyring.errors.NoKeyringError:
        print("Warning: No keyring backend found. Token will not be stored securely.")
    except Exception as e:
        print(f"Warning: Could not access keyring: {e}. Token will not be stored securely.")

    print("-" * 60)
    print("Master Token not found or accessible in keyring.")
    print("You need an OAuth Token to generate a Master Token.")
    print("This Master Token grants broad access to your Google account - keep it secure.")
    print("Instructions:")
    print("1. Go to this link in your browser (you might need to use an incognito window):")
    print("   https://accounts.google.com/EmbeddedSetup")
    print("2. Sign in to the Google account you want to use.")
    print("3. Copy the long token that appears on the page (it usually starts with 'oauth2rt_').")
    print("4. Paste the token below when prompted.")
    print("-" * 60)

    oauth_token = None
    while not oauth_token:
        oauth_token = getpass.getpass("Paste the OAuth Token here: ")
        if not oauth_token:
            print("OAuth Token cannot be empty.")

    # Generate random Android ID
    android_id = ''.join(random.choices(string.hexdigits.lower(), k=16))
    print(f"Using randomly generated Android ID: {android_id}")

    master_token = None
    print("Attempting to exchange OAuth token for Master Token...")
    try:
        # Use gpsoauth directly
        master_response = gpsoauth.exchange_token(email, oauth_token, android_id)
        # print(f"DEBUG: Full master response: {master_response}") # Uncomment for debugging

        if 'Token' in master_response:
            master_token = master_response['Token']
            print("Successfully obtained Master Token.") # Don't print the token itself
        else:
            print("Error: Could not obtain Master Token.")
            print("The response from Google did not contain the expected 'Token' field.")
            print("Details:", master_response.get('Error', 'No error details provided.'))
            # Provide more specific advice if possible
            if 'Error' in master_response and master_response['Error'] == 'BadAuthentication':
                print("This often means the OAuth Token was incorrect or expired.")
            elif 'Error' in master_response and master_response['Error'] == 'NeedsBrowser':
                 print("This might indicate that Google requires additional verification.")
            print("Please double-check the OAuth token and try again.")
            return None # Indicate failure

    except ImportError:
         print("Error: The 'gpsoauth' library is not installed.")
         print("Please install it by running: pip install gpsoauth")
         return None
    except Exception as e:
        print(f"An unexpected error occurred during token exchange: {e}")
        return None

    # Store the obtained token
    if master_token:
        try:
            keyring.set_password(SERVICE_NAME, email, master_token)
            print(f"Master token for {email} securely stored in keyring.")
        except keyring.errors.NoKeyringError:
            pass # Already warned about no backend
        except Exception as e:
            print(f"Warning: Could not store master token in keyring: {e}")

    return master_token

def ensure_attachments_dir():
    """Creates the attachments directory if it doesn't exist."""
    os.makedirs(ATTACHMENTS_DIR, exist_ok=True)
    return os.path.abspath(ATTACHMENTS_DIR)

def load_cached_state():
    """Loads cached Google Keep state from file if it exists."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                print(f"Loading cached state from {CACHE_FILE}...")
                state = json.load(f)
                return state
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading cached state: {e}")
            print("Will perform a full sync instead.")
    return None

def save_cached_state(keep):
    """Saves the current Google Keep state to a cache file."""
    try:
        state = keep.dump()
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)
        print(f"Saved state to {CACHE_FILE} for faster future syncs.")
    except Exception as e:
        print(f"Warning: Could not save state to cache file: {e}")

def get_file_extension_from_blob(blob):
    """Determine the file extension just from blob type."""
    blob_type = None
    if hasattr(blob, 'type'):
        if hasattr(blob.type, 'name'):
            blob_type = blob.type.name
        else:
            blob_type = str(blob.type)

        type_map = {
            'PHOTO': 'jpg', 'IMAGE': 'jpg', 'JPEG': 'jpg', 'PNG': 'png',
            'GIF': 'gif', 'DRAWING': 'png', 'AUDIO': 'mp3', 'AUDIO_RECORDING': 'mp3',
            'AMR': 'amr', '3GPP': '3gp', 'MP4': 'mp4', 'MPEG_AUDIO': 'mp3',
            'VIDEO': 'mp4', 'PDF': 'pdf'
        }
        if blob_type in type_map:
            return type_map[blob_type]
    return 'bin' # Fallback if type is unknown or missing

def get_file_extension_from_response(response, blob):
    """Determine the file extension from HTTP response and potentially file content."""
    # Try Content-Type header first
    if 'Content-Type' in response.headers:
        content_type = response.headers['Content-Type']
        ext = mimetypes.guess_extension(content_type)
        if ext:
            ext = ext.lstrip('.')
            if ext in ['jpe', 'jpeg']: ext = 'jpg'
            return ext

    # Try magic number detection
    try:
        import magic
        content_type = magic.from_buffer(response.content, mime=True)
        ext = mimetypes.guess_extension(content_type)
        if ext:
            ext = ext.lstrip('.')
            if ext in ['jpe', 'jpeg']: ext = 'jpg'
            return ext
    except ImportError:
        if DEBUG: print("  Warning: python-magic not installed, skipping file content detection")
    except Exception as e:
        if DEBUG: print(f"  Error detecting file type: {e}")

    # Fallback to blob type
    return get_file_extension_from_blob(blob)

def download_media_blob(keep, blob, note_id):
    """
    Downloads a media blob if it doesn't exist locally.
    Returns a dict with metadata about the attachment.
    """
    try:
        blob_id = str(blob.id)
        # Guess initial extension based on blob type for filename check
        initial_ext = get_file_extension_from_blob(blob)
        filename = f"{blob_id}.{initial_ext}" # This is 'initial_filename'
        filepath = os.path.join(ATTACHMENTS_DIR, filename) # This is 'initial_filepath'

        # Get blob type name
        blob_type_name = "UNKNOWN"
        if hasattr(blob, 'type'):
            blob_type_name = blob.type.name if hasattr(blob.type, 'name') else str(blob.type)

        # Check if file exists with the initial extension guess
        if os.path.exists(filepath):
            print(f"Attachment {filename} (ID: {blob_id}) already exists (initial guess: .{initial_ext}), skipping download.")
            return _generate_metadata(blob_id, filename, blob_type_name, initial_ext, blob)
        else:
            # Initial guess didn't find the file.
            # Try a glob pattern to find any file starting with blob_id.*
            # This catches cases like 'blob_id.jpeg' when initial guess was 'blob_id.jpg', or if initial guess was '.bin'.
            # This check is done BEFORE any network calls.
            possible_matches = glob.glob(os.path.join(ATTACHMENTS_DIR, f"{blob_id}.*"))
            if possible_matches:
                # A file with this blob_id exists, possibly with a different extension.
                existing_filepath_glob = possible_matches[0] # Take the first match
                existing_filename_glob = os.path.basename(existing_filepath_glob)
                _, existing_ext_glob_with_dot = os.path.splitext(existing_filename_glob)
                actual_ext_glob = existing_ext_glob_with_dot.lstrip('.')
                
                print(f"Attachment {existing_filename_glob} (ID: {blob_id}) already exists (found via glob: .{actual_ext_glob}), skipping download.")
                return _generate_metadata(blob_id, existing_filename_glob, blob_type_name, actual_ext_glob, blob)

        # --- If we reach here, file doesn't exist locally (neither by initial guess nor by glob). Proceed with download. ---
        media_url = keep.getMediaLink(blob)
        if not media_url:
            if DEBUG: print(f"Warning: Could not get media link for blob {blob.id}")
            return None

        response = requests.get(media_url, stream=True)
        if response.status_code != 200:
            if DEBUG: print(f"Failed to download blob {blob_id}: HTTP status {response.status_code}")
            return None

        # Determine final file extension using response (might be different from initial guess)
        final_ext = get_file_extension_from_response(response, blob)
        final_filename = f"{blob_id}.{final_ext}"
        final_filepath = os.path.join(ATTACHMENTS_DIR, final_filename)

        # If the extension changed and the new file exists, skip
        if final_filename != filename and os.path.exists(final_filepath):
             print(f"Attachment {final_filename} already exists (after checking content type), skipping download.")
             return _generate_metadata(blob_id, final_filename, blob_type_name, final_ext, blob)
        # Handle case where initial filename needs correction
        elif final_filename != filename:
             filename = final_filename
             filepath = final_filepath


        print(f"Downloading {filename}...")
        with open(filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        return _generate_metadata(blob_id, filename, blob_type_name, final_ext, blob)

    except Exception as e:
        print(f"Error processing blob {getattr(blob, 'id', 'UNKNOWN')}: {e}")
        if DEBUG: print(traceback.format_exc())
        return None

def process_note_media(keep, note, note_data):
    """
    Process all media from a note, download if needed, and add to note data.
    Returns the set of processed attachment filenames for this note.
    """
    processed_filenames = set()
    if 'attachments' not in note_data:
        note_data['attachments'] = []

    media_sources = []
    if hasattr(note, 'images') and note.images: media_sources.extend(note.images)
    if hasattr(note, 'drawings') and note.drawings: media_sources.extend(note.drawings)
    if hasattr(note, 'audio') and note.audio: media_sources.extend(note.audio)
    # Add blobs last as a fallback, avoiding duplicates if possible
    if hasattr(note, 'blobs') and note.blobs:
        processed_blob_ids = {a['id'] for a in note_data['attachments'] if 'id' in a}
        media_sources.extend([b for b in note.blobs if str(b.id) not in processed_blob_ids])

    for medium in media_sources:
        try:
            attachment_info = download_media_blob(keep, medium, note.id)
            if attachment_info:
                # Determine media_type based on source attribute if possible
                if medium in getattr(note, 'images', []): attachment_info['media_type'] = 'image'
                elif medium in getattr(note, 'drawings', []): attachment_info['media_type'] = 'drawing'
                elif medium in getattr(note, 'audio', []): attachment_info['media_type'] = 'audio'
                else: attachment_info['media_type'] = 'blob' # Default if source unknown

                # Avoid adding duplicate metadata if already processed via another attribute (e.g., image vs blob)
                existing_ids = {a['id'] for a in note_data['attachments']}
                if attachment_info['id'] not in existing_ids:
                    note_data['attachments'].append(attachment_info)
                    processed_filenames.add(attachment_info['filename'])
                elif attachment_info['filename'] not in processed_filenames:
                     # If ID exists but filename doesn't, still add filename to track
                     processed_filenames.add(attachment_info['filename'])


        except Exception as e:
            print(f"Error processing media item {getattr(medium, 'id', '?')} from note {note.id}: {e}")

    return processed_filenames

# Custom JSON encoder to handle non-serializable types
class KeepEncoder(json.JSONEncoder):
    def default(self, obj):
        # Convert enum types to strings
        if hasattr(obj, 'name'):
            return obj.name
        # Handle other special types
        try:
            return str(obj)
        except:
            return None
        # Let the base class handle the rest
        return json.JSONEncoder.default(self, obj)

def make_serializable(obj):
    """Convert Keep API objects to serializable types."""
    if hasattr(obj, '__dict__'):
        return {k: make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
    elif isinstance(obj, (list, tuple)):
        return [make_serializable(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif hasattr(obj, 'name'):  # Handle enums
        return obj.name
    elif hasattr(obj, 'timestamp'):  # Handle time objects
        return obj.timestamp()
    else:
        return obj

def escape_hashtags(text):
    """Escape hashtags that might be interpreted as tags/headers by Obsidian."""
    if not text:
        return text
    # Escape # if:
    # - Not already preceded by a backslash (negative lookbehind (?<!\\))
    # - At the start of the line (^) or preceded by whitespace (\\s)
    # - Followed by a non-whitespace, non-# character ([^\s#])
    # Replace with the preceding char/whitespace + \\# + the following char
    # Fix: Use proper regex replacement syntax for captured groups
    return re.sub(r'(?<!\\)(^|\\s)#([^\s#])', r'\g<1>\\#\g<2>', text)

def sanitize_filename(name, note_id):
    """Sanitizes a string to be a valid filename, using note_id as fallback."""
    if not name: # Use note ID if title is empty
        name = f"Untitled_{note_id}"

    # Replace / with _
    sanitized = name.replace('/', '_')

    # Remove invalid characters (note: / is already replaced)
    sanitized = re.sub(r'[<>:"\\\|?*]', '', sanitized) # Use raw string for backslash
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized) # Remove control characters

    # Keep spaces, but replace multiple spaces/tabs with a single space
    sanitized = re.sub(r'\s+', ' ', sanitized).strip() # Replace multiple whitespace with single space and strip ends

    # Limit length *before* checking reserved names
    sanitized = sanitized[:MAX_FILENAME_LENGTH]

    # Remove trailing dots or spaces
    sanitized = sanitized.rstrip('. ')

    # Check for reserved names (case-insensitive)
    name_part = sanitized.split('.')[0]
    if name_part.upper() in RESERVED_NAMES:
        sanitized = f"_{sanitized}" # Prepend underscore if reserved

    # Ensure it's not empty after all sanitization
    if not sanitized:
        sanitized = f"Note_{note_id}"

    # Final strip for any leading/trailing spaces that might have crept in
    sanitized = sanitized.strip()

    # Ensure it's not empty AGAIN after final strip
    if not sanitized:
        sanitized = f"Note_{note_id}"

    return f"{sanitized}.md"

def create_vault_structure(base_path):
    """Creates the necessary directories for the Obsidian vault."""
    paths = [
        base_path,
        ATTACHMENTS_VAULT_DIR, # Use the constant
        ARCHIVED_DIR,
        TRASHED_DIR,
    ]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            print(f"Error creating directory {path}: {e}")
            sys.exit(1)

def is_note_empty(note_data):
    """Check if a note is essentially empty."""
    has_title = bool(note_data.get('title', '').strip())
    has_text = bool(note_data.get('text', '').strip())
    has_list_items = bool(note_data.get('listContent') and any(item.get('text', '').strip() for item in note_data['listContent']))
    has_attachments = bool(note_data.get('attachments') and len(note_data['attachments']) > 0)
    has_annotations = bool(
        note_data.get('annotationsGroup') and
        note_data['annotationsGroup'].get('annotations') and
        len(note_data['annotationsGroup']['annotations']) > 0
    )
    return not (has_title or has_text or has_list_items or has_attachments or has_annotations)

def convert_note_to_markdown(note, note_data):
    """Converts a GKeep note (via note_data) into a Markdown string with frontmatter."""
    # --- Prepare Markdown Body Content ---
    processed_note_text = ""
    if note.text: # Check if note.text is not None and not empty
        # 1. Normalize line endings (as in push.py remote prep)
        text_normalized = note.text.replace('\r\n', '\n').replace('\r', '\n')
        
        # 2. Split into lines
        lines = text_normalized.split('\n')
        
        # 3. Filter blank lines (lines that are empty or only whitespace) (as in push.py remote prep)
        #    A line is blank if line.strip() == ""
        # non_blank_lines = [line for line in lines if line.strip() != ""] # MODIFIED: Removed this line
        
        # 4. Strip trailing whitespace from each non-blank line (as in push.py remote prep)
        stripped_trailing_lines = [line.rstrip() for line in lines] # MODIFIED: Use 'lines'
        
        # 5. Join back
        cleaned_text_block = '\n'.join(stripped_trailing_lines)
        
        # 6. Escape hashtags (this is specific to pull.py's markdown output)
        #    Only apply if cleaned_text_block is not empty, otherwise escape_hashtags might receive empty string.
        if cleaned_text_block:
            processed_note_text = escape_hashtags(cleaned_text_block)
        # If cleaned_text_block is empty after processing, processed_note_text remains ""

    # Use processed_note_text for content_parts
    content_parts = [processed_note_text] if processed_note_text else []

    # --- Attachments Section (using note_data) ---
    # note_data['attachments'] is a list of dicts like {'filename': 'name.ext', ...}
    # These files are already downloaded by process_note_media.
    processed_attachments = note_data.get('attachments', [])
    if processed_attachments:
        attachment_links = []
        for attachment_info in processed_attachments:
            attachment_filename = attachment_info.get('filename')
            if attachment_filename:
                # Construct relative path for Obsidian link, e.g., "Attachments/file.jpg"
                attachment_rel_path = os.path.join(os.path.basename(ATTACHMENTS_VAULT_DIR), attachment_filename).replace("\\", "/")
                attachment_links.append(f"- ![[{attachment_rel_path}]]")

        if attachment_links:
            if content_parts: # Add a blank line for separation if there's preceding text
                content_parts.append("")
            content_parts.append("## Attachments")
            content_parts.extend(attachment_links)

    # Join all parts of the markdown body
    final_content_string = "\n".join(part for part in content_parts if part is not None and part != "")

    # --- Prepare YAML Frontmatter ---
    yaml_metadata = {}
    current_note_id = note.id # Use note.id directly

    yaml_metadata['id'] = current_note_id
    
    # Use note.title directly and verbatim
    yaml_metadata['title'] = note.title if note.title is not None else ""

    # Add color and pinned status from the note object
    yaml_metadata['color'] = note.color.name # e.g., "WHITE", "YELLOW"
    yaml_metadata['pinned'] = note.pinned    # True or False

    timestamps = note_data.get('timestamps', {}) # Keep using note_data for existing timestamp logic for now
    if timestamps.get('created'):
        yaml_metadata['created'] = timestamps['created']
    if timestamps.get('updated'):
        yaml_metadata['updated'] = timestamps['updated']
    if timestamps.get('userEdited'): # from note.timestamps.userEdited
        yaml_metadata['edited'] = timestamps['userEdited']

    labels_data = note_data.get('labels') # Expected: list of dicts [{'name': 'LabelName'}, ...]
    if labels_data and isinstance(labels_data, list):
        label_names = [label.get('name').replace(' ', '_') for label in labels_data if label.get('name')]
        if label_names: # Only add 'tags' key if there are actual label names
            yaml_metadata['tags'] = label_names

    yaml_metadata['archived'] = note.archived
    yaml_metadata['trashed'] = note.trashed

    # Convert metadata dict to YAML string. sort_keys=False preserves order.
    yaml_string = yaml.dump(yaml_metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # Log details if note_id is available
    if current_note_id:
        logging.debug(f"PULL_CONVERT_MARKDOWN ({current_note_id}): Final metadata for YAML: {yaml_metadata}")
        # Truncate long content strings in logs
        log_content_preview = final_content_string[:150].replace('\n', '\\n')
        if len(final_content_string) > 150:
            log_content_preview += "..."
        logging.debug(f"PULL_CONVERT_MARKDOWN ({current_note_id}): Final content string (len={len(final_content_string)}): '{log_content_preview}'")
        logging.debug(f"PULL_CONVERT_MARKDOWN ({current_note_id}): Final YAML string prepared:\n---\n{yaml_string.strip()}\n---")

    # Combine YAML frontmatter and markdown body
    full_file_content = f"---\n{yaml_string.strip()}\n---\n{final_content_string}"

    return full_file_content

def parse_markdown_file(filepath):
    """Loads and parses a single markdown file manually, returning metadata or None."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines or not lines[0].strip() == '---':
            print(f"  Info: Skipping file {filepath} - Missing opening frontmatter delimiter.")
            return None # Not a valid format

        yaml_lines = []
        content_lines = []
        in_yaml = False
        yaml_end_found = False

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            if i == 0 and stripped_line == '---':
                in_yaml = True
                continue
            elif in_yaml and stripped_line == '---':
                in_yaml = False
                yaml_end_found = True
                continue

            if in_yaml:
                yaml_lines.append(line)
            elif yaml_end_found:
                content_lines.append(line)

        if not yaml_end_found:
             print(f"  Warning: Skipping file {filepath} - Missing closing frontmatter delimiter.")
             return None

        metadata = {}
        if yaml_lines:
            try:
                metadata = yaml.safe_load("\n".join(yaml_lines))
                if not isinstance(metadata, dict):
                    print(f"  Warning: Frontmatter in {filepath} did not parse as a dictionary. Skipping.")
                    return None
            except yaml.YAMLError as e:
                print(f"  Error parsing YAML in {filepath}: {e}")
                return None

        # --- Process Metadata (Handle missing keys) ---
        # Ensure 'id' exists, otherwise skip
        if 'id' not in metadata:
            print(f"  Info: Skipping file {filepath} due to missing 'id' frontmatter.")
            return None

        # Attempt to parse timestamps if they exist
        if 'created' in metadata:
            try:
                ts_str = str(metadata['created']).rstrip('Z')
                if ts_str:
                    metadata['created_dt'] = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                else:
                    metadata['created_dt'] = None
            except (TypeError, ValueError) as e_ts:
                print(f"  Warning: Could not parse 'created' timestamp ('{metadata.get('created')}') in {filepath}: {e_ts}.")
                metadata['created_dt'] = None
        else:
             metadata['created_dt'] = None # Key missing

        if 'updated' in metadata:
            try:
                ts_str = str(metadata['updated']).rstrip('Z')
                if ts_str:
                    metadata['updated_dt'] = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                else:
                    metadata['updated_dt'] = None
            except (TypeError, ValueError) as e_ts:
                print(f"  Warning: Could not parse 'updated' timestamp ('{metadata.get('updated')}') in {filepath}: {e_ts}.")
                metadata['updated_dt'] = None
        else:
             metadata['updated_dt'] = None # Key missing

        if 'edited' in metadata:
            try:
                ts_str = str(metadata['edited']).rstrip('Z')
                if ts_str:
                    metadata['edited_dt'] = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                else:
                    metadata['edited_dt'] = None
            except (TypeError, ValueError) as e_ts:
                print(f"  Warning: Could not parse 'edited' timestamp ('{metadata.get('edited')}') in {filepath}: {e_ts}.")
                metadata['edited_dt'] = None
        else:
            metadata['edited_dt'] = None # Key missing

        # ID exists, return metadata (with _dt fields possibly None)
        return metadata

    except FileNotFoundError:
        print(f"  Error: File not found during parsing: {filepath}")
        return None
    except Exception as e:
        print(f"  Error processing Markdown file {filepath}: {e}")
        traceback.print_exc() # Show full traceback for parsing errors
        return None

def index_local_notes(vault_base_path):
    """Scans vault directories and builds an index of local notes by Keep ID."""
    print("Indexing local Markdown files...")
    local_index = {}
    # Scan root, Archived, and Trashed directories
    scan_dirs = [vault_base_path, ARCHIVED_DIR, TRASHED_DIR]
    for directory in scan_dirs:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            if filename.lower().endswith(".md"):
                filepath = os.path.join(directory, filename)
                metadata = parse_markdown_file(filepath)
                if metadata and 'id' in metadata:
                    note_id_raw = metadata['id']
                    note_id = str(note_id_raw)
                    if note_id in local_index:
                        print(f"  Warning: Duplicate Keep ID '{note_id}' found locally: {filepath} and {local_index[note_id]['path']}. Skipping second instance.")
                    else:
                        local_index[note_id] = {'path': filepath, 'metadata': metadata}

    print(f"Found {len(local_index)} unique notes with IDs in local vault.")
    return local_index

def process_and_save_notes(all_notes_info, vault_base_path):
    """Processes notes from Keep, compares with local index, and updates/creates/deletes local files."""
    logging.info("Starting Markdown file synchronization...") # Use logging
    create_vault_structure(vault_base_path)
    local_index = index_local_notes(vault_base_path) # {keep_id: {path: str, metadata: dict}}
    processed_keep_ids = set() # Keep track of Keep IDs successfully processed

    created_count = 0
    updated_count = 0
    moved_count = 0
    skipped_empty_count = 0
    skipped_error_count = 0
    skipped_no_change_count = 0 # Track skips due to timestamps

    logging.info(f"Processing {len(all_notes_info)} notes fetched from Google Keep...")

    # --- Pass 1: Process notes from Keep --- START
    for note, note_data in all_notes_info: 
        keep_id = note.id # Get ID directly from note object
        processed_keep_ids.add(keep_id) # Mark as seen from Keep
        logging.debug(f"Processing Keep note ID: {keep_id}, Title: '{note.title}'")

        # Use note_data dict for is_note_empty check as it reflects saved content
        if is_note_empty(note_data):
            logging.debug(f"  Skipping note ID {keep_id}: Empty content.")
            skipped_empty_count += 1
            continue

        try:
            # --- Get Keep note details (use note object where possible) ---
            keep_title = note.title
            keep_archived = note.archived
            keep_trashed = note.trashed
            # --- Get timestamp directly from note object ---
            keep_updated_dt = note.timestamps.updated
            if keep_updated_dt:
                 # Ensure it's timezone-aware (UTC)
                 keep_updated_dt = keep_updated_dt.replace(tzinfo=timezone.utc)
            logging.debug(f"  Keep Note Details - ID: {keep_id}, Title: '{keep_title}', Archived: {keep_archived}, Trashed: {keep_trashed}, Updated: {keep_updated_dt}")

            # --- Determine target path based on *Keep* data ---
            if keep_trashed:
                target_dir = TRASHED_DIR
            elif keep_archived:
                target_dir = ARCHIVED_DIR
            else:
                target_dir = vault_base_path
            target_filename = sanitize_filename(keep_title, keep_id)
            target_filepath_ideal = os.path.join(target_dir, target_filename)
            os.makedirs(target_dir, exist_ok=True) # Ensure target dir exists
            logging.debug(f"  Ideal target path for {keep_id}: {os.path.relpath(target_filepath_ideal)}")

            # --- Check if note exists locally ---
            local_info = local_index.get(keep_id)

            if local_info: # === Note Found Locally ===
                local_filepath = local_info['path']
                local_metadata = local_info['metadata']
                local_updated_dt = local_metadata.get('updated_dt') # Parsed datetime obj or None
                # Also get the raw string for logging comparison consistency
                local_updated_str = local_metadata.get('updated')

                logging.info(f"  Found local file for Keep ID {keep_id} at: {os.path.relpath(local_filepath)}")
                logging.debug(f"    Local Metadata - Updated DT: {local_updated_dt}, Updated Str: '{local_updated_str}', Title: '{local_metadata.get('title')}', Archived: {local_metadata.get('archived')}, Trashed: {local_metadata.get('trashed')}")

                # --- Compare timestamps for update ---
                should_update_content = False
                can_compare_timestamps = isinstance(keep_updated_dt, datetime) and isinstance(local_updated_dt, datetime)

                logging.debug(f"    Timestamp comparison - Can compare: {can_compare_timestamps}, Keep TS: {keep_updated_dt}, Local TS: {local_updated_dt}")
                if can_compare_timestamps:
                    # Using a small tolerance for potential floating point issues if they were floats, though less likely with discrete timestamps
                    # For safety, let's use a simple direct comparison first
                    if keep_updated_dt > local_updated_dt:
                        should_update_content = True
                        logging.info(f"    Decision: Keep timestamp newer. Marking for content update.")
                    else:
                        logging.info(f"    Decision: Local timestamp same or newer ({local_updated_dt} >= {keep_updated_dt}). Skipping content update based on timestamp.")
                        skipped_no_change_count += 1
                else: # Cannot compare reliably
                    # Decide on a default behavior: update or skip? Let's skip to be safe.
                    logging.warning(f"    Decision: Cannot compare timestamps reliably (Keep: {keep_updated_dt}, Local: {local_updated_dt}). Skipping content update.")
                    skipped_no_change_count += 1
                    # should_update_content remains False

                # --- Update content if needed ---
                if should_update_content:
                    logging.debug(f"    Attempting to update content for {keep_id} in {os.path.relpath(local_filepath)}")
                    try:
                        # Pass the original note object to the conversion function
                        updated_markdown = convert_note_to_markdown(note, note_data)
                        # Log content hash before writing?
                        local_content_before = ""
                        try:
                            with open(local_filepath, "r", encoding="utf-8") as f_read:
                                local_content_before = f_read.read()
                        except Exception:
                             pass # Ignore if can't read
                        local_hash_before = hashlib.sha256(local_content_before.encode('utf-8')).hexdigest()[:8]
                        new_hash = hashlib.sha256(updated_markdown.encode('utf-8')).hexdigest()[:8]
                        logging.debug(f"    Content Hash - Before write: {local_hash_before}, New content: {new_hash}")
                        if local_hash_before == new_hash:
                             logging.info(f"    Content hash matches existing file content hash. Skipping write operation for {keep_id}.")
                             updated_count += 1 # Count it as 'updated' conceptually because timestamp triggered it, but file wasn't touched
                        else:
                             logging.info(f"    Content hashes differ. Writing updated content to {os.path.relpath(local_filepath)}")
                             with open(local_filepath, "w", encoding="utf-8") as f:
                                 f.write(updated_markdown)
                             updated_count += 1
                        # Update metadata in memory for move check (do this even if hash matched, as status might change)
                        local_info['metadata']['title'] = keep_title
                        local_info['metadata']['archived'] = keep_archived
                        local_info['metadata']['trashed'] = keep_trashed
                        # Write the *actual* Keep timestamp we used for comparison
                        local_updated_timestamp_str = keep_updated_dt.isoformat().replace('+00:00', 'Z') if keep_updated_dt else "MISSING"
                        local_info['metadata']['updated'] = local_updated_timestamp_str
                        local_info['metadata']['updated_dt'] = keep_updated_dt
                        logging.debug(f"    In-memory metadata updated. New 'updated' string: {local_updated_timestamp_str}")

                    except IOError as e:
                        logging.error(f"    Error writing updated file {local_filepath}: {e}")
                        skipped_error_count += 1
                        continue # Use continue to skip move check on write error
                    except Exception as e_conv:
                        logging.error(f"    Error during markdown conversion or hash for {keep_id}: {e_conv}")
                        traceback.print_exc()
                        skipped_error_count += 1
                        continue # Use continue to skip move check on conversion error
                else: # Content update skipped based on timestamp
                    # === FIX: Check content hash consistency even if timestamp didn't trigger update ===
                    logging.debug(f"    Content update skipped for {keep_id} based on timestamp. Verifying content hash consistency.")
                    try:
                        expected_markdown = convert_note_to_markdown(note, note_data)
                        expected_hash = hashlib.sha256(expected_markdown.encode('utf-8')).hexdigest()[:8]
                        logging.debug(f"    Verification Step 1: Calculated expected hash: {expected_hash}") # Log hash calculation

                        current_content = ""
                        current_hash = "not_calculated"
                        try:
                            logging.debug(f"    Verification Step 2: Attempting to read local file: {local_filepath}")
                            with open(local_filepath, "r", encoding="utf-8") as f_read:
                                current_content = f_read.read()
                            logging.debug(f"    Verification Step 3: Successfully read local file.")
                            current_hash = hashlib.sha256(current_content.encode('utf-8')).hexdigest()[:8]
                            logging.debug(f"    Verification Step 4: Calculated current hash: {current_hash}")
                        except Exception as e_read:
                             logging.warning(f"    Verification Step ERROR: Could not read existing local file {local_filepath} for hash verification: {e_read}")
                             current_hash = "read_error" # Indicate read failure

                        # This log should ALWAYS appear now unless convert_note_to_markdown fails
                        logging.debug(f"    Hash Verification Result - Current: {current_hash}, Expected: {expected_hash}")
                        if current_hash != "read_error" and current_hash != expected_hash:
                             logging.warning(f"    Content hash mismatch for {keep_id} despite timestamp match! Local file might be stale or edited. (Current: {current_hash}, Expected: {expected_hash})")
                             # Decide whether to overwrite. Overwriting ensures consistency for push.
                             logging.warning(f"    Overwriting local file {os.path.relpath(local_filepath)} to ensure consistency with Keep format.")
                             try:
                                 with open(local_filepath, "w", encoding="utf-8") as f_write:
                                     f_write.write(expected_markdown)
                                 # This wasn't technically an update based on timestamp, more like a correction.
                                 # Maybe add a new counter? For now, let's not increment updated_count here.
                                 logging.info(f"    Successfully overwrote inconsistent local file {os.path.relpath(local_filepath)}")
                                 # Update metadata in memory as well, as content AND timestamp in file now match remote
                                 local_info['metadata']['title'] = keep_title
                                 local_info['metadata']['archived'] = keep_archived
                                 local_info['metadata']['trashed'] = keep_trashed
                                 local_updated_timestamp_str = keep_updated_dt.isoformat().replace('+00:00', 'Z') if keep_updated_dt else "MISSING"
                                 local_info['metadata']['updated'] = local_updated_timestamp_str
                                 local_info['metadata']['updated_dt'] = keep_updated_dt

                             except IOError as e_write_fix:
                                  logging.error(f"    Error overwriting inconsistent local file {local_filepath}: {e_write_fix}")
                                  skipped_error_count += 1
                                  # If overwrite fails, skip the move check below
                                  continue
                        elif current_hash == expected_hash:
                             logging.debug(f"    Hash verification passed for {keep_id}. Local content is consistent.")
                        # else: current_hash == "read_error", already logged warning

                    except Exception as e_verify:
                         logging.error(f"    Error during outer hash verification block for {keep_id}: {e_verify}")
                         traceback.print_exc()
                         skipped_error_count += 1
                         # If verification fails, skip the move check below
                         continue
                    # === END FIX ===

                # --- Check if file needs moving/renaming --- START
                # (This check should happen regardless of content update, unless an error occurred above)
                # Use the potentially updated local_info['metadata'] title for target path calculation
                current_keep_title = local_info['metadata'].get('title', '')
                current_keep_archived = local_info['metadata'].get('archived', False)
                current_keep_trashed = local_info['metadata'].get('trashed', False)
                if current_keep_trashed:
                     current_target_dir = TRASHED_DIR
                elif current_keep_archived:
                     current_target_dir = ARCHIVED_DIR
                else:
                     current_target_dir = vault_base_path
                current_target_filename = sanitize_filename(current_keep_title, keep_id)
                current_target_filepath_ideal = os.path.join(current_target_dir, current_target_filename)

                needs_move = os.path.normpath(local_filepath) != os.path.normpath(current_target_filepath_ideal)

                if needs_move:
                    move_reason = "status change" if os.path.dirname(local_filepath) != os.path.dirname(current_target_filepath_ideal) else "rename"
                    logging.info(f"    File needs move/rename (Reason: {move_reason}) from {os.path.relpath(local_filepath)} to {os.path.relpath(current_target_filepath_ideal)}")
                    final_target_filepath = current_target_filepath_ideal
                    counter = 1
                    # Check for collisions, avoiding self-comparison
                    while os.path.exists(final_target_filepath) and os.path.normpath(final_target_filepath) != os.path.normpath(local_filepath):
                         logging.warning(f"    Target path {os.path.relpath(final_target_filepath)} exists. Generating new name...")
                         name, ext = os.path.splitext(current_target_filename)
                         max_name_len = MAX_FILENAME_LENGTH - len(ext) - len(str(counter)) - 1
                         name = name[:max_name_len]
                         new_filename = f"{name}_{counter}{ext}"
                         final_target_filepath = os.path.join(current_target_dir, new_filename)
                         counter += 1
                         if counter > 100:
                              logging.error(f"    Could not find unique target path for moving/renaming note {keep_id}. Skipping move.")
                              final_target_filepath = None # Mark as None if no unique name found
                              break

                    # Refactored logic to handle potential None for final_target_filepath
                    if final_target_filepath: # Check if a valid path was determined (not None)
                        if os.path.normpath(final_target_filepath) != os.path.normpath(local_filepath):
                            try:
                                logging.info(f"    Executing move to {os.path.relpath(final_target_filepath)}")
                                # Ensure target directory exists before moving
                                os.makedirs(os.path.dirname(final_target_filepath), exist_ok=True)
                                shutil.move(local_filepath, final_target_filepath)
                                moved_count += 1
                                local_info['path'] = final_target_filepath # Update index path
                            except Exception as e_move:
                                logging.error(f"    Error moving file {local_filepath} to {final_target_filepath}: {e_move}")
                                skipped_error_count += 1
                        else: # Paths are the same after normalization, no move needed
                             logging.debug(f"    Target move path is same as source ({os.path.relpath(local_filepath)}), no move needed for {keep_id}.")
                    else: # final_target_filepath is None (collision resolution failed)
                         logging.error(f"    Skipping move for {keep_id} due to collision resolution failure finding a unique name.")
                         skipped_error_count += 1
                # --- Check if file needs moving/renaming --- END

            else: # === Note is New Locally (local_info is None) ===
                logging.info(f"  Keep ID {keep_id} not found locally. Creating new file...")
                final_target_filepath = target_filepath_ideal
                counter = 1
                while os.path.exists(final_target_filepath):
                     logging.warning(f"    Target path {os.path.relpath(final_target_filepath)} exists. Generating new name...")
                     name, ext = os.path.splitext(target_filename)
                     max_name_len = MAX_FILENAME_LENGTH - len(ext) - len(str(counter)) - 1
                     name = name[:max_name_len]
                     new_filename = f"{name}_{counter}{ext}"
                     final_target_filepath = os.path.join(target_dir, new_filename)
                     counter += 1
                     if counter > 100:
                          logging.error(f"    Could not find unique filename for new note {keep_id} in {target_dir}. Skipping creation.")
                          final_target_filepath = None
                          break

                if final_target_filepath:
                    try:
                        # Pass the original note object to the conversion function
                        new_markdown = convert_note_to_markdown(note, note_data)
                        logging.debug(f"    Writing new content for {keep_id} (Hash: {hashlib.sha256(new_markdown.encode('utf-8')).hexdigest()[:8]})")
                        with open(final_target_filepath, "w", encoding="utf-8") as f:
                            f.write(new_markdown)
                        created_count += 1
                        logging.info(f"    Created new file: {os.path.relpath(final_target_filepath)}")
                    except IOError as e:
                        logging.error(f"    Error writing new file {final_target_filepath}: {e}")
                        skipped_error_count += 1
                    except Exception as e_conv:
                        logging.error(f"    Error during markdown conversion for new file {keep_id}: {e_conv}")
                        traceback.print_exc()
                        skipped_error_count += 1

        except Exception as e_proc:
            logging.error(f"  ERROR: Unexpected error processing note {keep_id}: {e_proc}")
            traceback.print_exc()
            skipped_error_count += 1
            # Ensure it's not accidentally deleted if local file exists
            if keep_id in local_index:
                logging.warning(f"    Removing {keep_id} from local index due to processing error to prevent deletion.")
                del local_index[keep_id] # Remove from index to prevent deletion

    # --- Pass 1: Process notes from Keep --- END

    # --- Pass 2: Delete Local Orphan Notes --- START
    # Notes still in local_index were not in the processed_keep_ids set from Keep
    orphaned_ids = set(local_index.keys()) - processed_keep_ids
    deleted_count = 0
    if orphaned_ids:
        logging.info(f"\nFound {len(orphaned_ids)} local notes not present in latest Keep sync. Deleting local files...")
        for orphan_id in orphaned_ids:
            if orphan_id in local_index: # Check it wasn't removed due to error earlier
                orphan_path = local_index[orphan_id]['path']
                try:
                    logging.info(f"  Deleting orphaned file: {os.path.relpath(orphan_path)} (ID: {orphan_id})")
                    os.remove(orphan_path)
                    deleted_count += 1
                except OSError as e_del:
                    logging.error(f"  Error deleting orphaned file {orphan_path}: {e_del}")
                    skipped_error_count += 1
            else:
                 logging.warning(f"  Warning: Orphan ID {orphan_id} was expected in local index but not found during deletion phase.")

    # --- Pass 2: Delete Local Orphan Notes --- END

    print("-" * 30)
    logging.info("Pull Sync Summary:")
    logging.info(f"Notes Created Locally: {created_count}")
    logging.info(f"Notes Updated Locally (incl. content hash match): {updated_count}")
    logging.info(f"Notes Skipped Content Update (Timestamp): {skipped_no_change_count}")
    logging.info(f"Notes Moved/Renamed Locally: {moved_count}")
    logging.info(f"Notes Deleted Locally (Orphaned): {deleted_count}")
    logging.info(f"Empty Notes Skipped: {skipped_empty_count}")
    if skipped_error_count > 0:
        logging.warning(f"Notes Skipped due to Errors: {skipped_error_count}")
    logging.info(f"Vault location: {os.path.abspath(vault_base_path)}")
    print("-" * 30)

def main():
    # --- Argument Parsing (Use argparse from merged logic) ---
    parser = argparse.ArgumentParser(description="Download Google Keep notes and convert to Obsidian Markdown.")
    parser.add_argument("email", nargs='?', default=None, help="Google account email address (optional, reads from .env if omitted).")
    parser.add_argument("--skip-markdown", action="store_true", help="Only download notes to JSON, skip Markdown conversion.")
    parser.add_argument("--full-sync", action="store_true", help="Ignore cached state and perform a full download.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging for gkeepapi.")
    args = parser.parse_args()

    if args.debug:
        gkeepapi.node.DEBUG = True
        print("Debug logging enabled.")
        global DEBUG
        DEBUG = True

    # Initialize mimetypes
    mimetypes.init()

    # --- Get Email (Command line -> .env -> Error) ---
    load_dotenv()
    email = args.email # Get from command line if provided
    env_email = os.getenv("GOOGLE_KEEP_EMAIL")

    if not email:
        if env_email:
            print(f"Using email from .env file: {env_email}")
            email = env_email
        else:
            print("Error: Email address not provided via command line or .env file (GOOGLE_KEEP_EMAIL).")
            sys.exit(1)
    elif env_email and email != env_email:
        print(f"Warning: Provided email '{email}' differs from GOOGLE_KEEP_EMAIL '{env_email}' in .env")

    # --- Authentication Flow (Use merged logic) ---
    master_token = os.getenv("GOOGLE_KEEP_MASTER_TOKEN")
    app_password = os.getenv("GOOGLE_KEEP_APP_PASSWORD")

    keep = gkeepapi.Keep()
    logged_in = False

    # 1. Try Master Token
    if not logged_in and not master_token:
        master_token = get_master_token(email)
    if master_token:
        try:
            print("Attempting authentication using Master Token...")
            # Use authenticate for master token
            keep.authenticate(email, master_token, sync=False)
            logged_in = True
            print("Authentication successful using Master Token.")
        except gkeepapi.exception.LoginException as e:
            print(f"Master Token authentication failed: {e}")
            master_token = None # Invalidate
        except Exception as e_auth:
             print(f"An unexpected error occurred during master token authentication: {e_auth}")
             master_token = None # Invalidate

    # 2. Try App Password
    if not logged_in:
        if not app_password: # Check .env first
            try:
                # Prompt only if not in .env
                app_password = getpass.getpass(f"Enter App Password for {email} (or leave blank to skip): ")
            except EOFError:
                app_password = None
        if app_password:
            try:
                print("Attempting login using App Password...")
                # Keep using login for app password
                keep.login(email, app_password, sync=False)
                logged_in = True
                print("Login successful using App Password.")
                if not os.getenv("GOOGLE_KEEP_APP_PASSWORD"):
                    if set_key(".env", "GOOGLE_KEEP_APP_PASSWORD", app_password):
                        print("Saved App Password to .env file.")
                    else:
                        print("Could not save App Password to .env file.")
            except gkeepapi.exception.LoginException as e:
                print(f"App Password login failed: {e}")
                app_password = None # Invalidate
            except Exception as e_login:
                 print(f"An unexpected error occurred during app password login: {e_login}")
                 app_password = None # Invalidate

    if not logged_in:
        print("Authentication failed. Please check credentials.")
        sys.exit(1)

    # Save email to .env if needed
    if logged_in and email != os.getenv("GOOGLE_KEEP_EMAIL"):
        if set_key(".env", "GOOGLE_KEEP_EMAIL", email):
            print("Saved email to .env file.")

    # --- Sync with Google Keep ---
    print("Syncing with Google Keep...")
    state = None
    if not args.full_sync:
        state = load_cached_state()

    try:
        auth_credential = master_token or app_password
        if not auth_credential:
             print("Error: No valid authentication credential available for sync.")
             sys.exit(1)

        # Use resume if state exists, otherwise sync normally
        if state:
            # Resume requires the token/password used for the initial *successful* login
            # The authenticate call doesn't store the credential in keep object
            # We might need to just call sync() after authenticate
            print("Resuming session with cached state...")
            keep.resume(email, auth_credential, state=state, sync=True)
        else:
            print("Performing full sync...")
            # keep.authenticate already called, just sync
            keep.sync()

        print("Sync complete.")
        save_cached_state(keep)
    except gkeepapi.exception.SyncException as e:
        print(f"Error during Google Keep sync: {e}")
        print("Try running with --full-sync if this persists.")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during sync/resume: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Ensure attachments directory exists (using the vault path)
    abs_attachments_dir = ensure_attachments_dir()
    print(f"Attachments will be downloaded/verified in: {abs_attachments_dir}")

    # --- Download Notes and Media ---
    print("Downloading notes and processing media...")
    # Change: Store tuples of (note_object, note_data_dict)
    all_notes_info = [] 
    notes = keep.all()
    total_notes = len(notes)
    download_errors = 0
    all_expected_filenames = set() # Track all expected filenames for orphan cleanup

    for i, note in enumerate(notes):
        try:
            # --- Get raw note object and create serializable dict ---
            note_data_raw = note.save()
            # --- Fixes/Enhancements ---
            if hasattr(note, 'text') and note.text:
                note_data_raw['text'] = note.text
            if hasattr(note, 'labels') and hasattr(note.labels, 'all'):
                labels = note.labels.all()
                if labels:
                    note_data_raw['labels'] = [{'id': label.id, 'name': label.name} for label in labels]
            # No longer need to add timestamps manually here
            # --- Fixes/Enhancements END ---
            note_data = make_serializable(note_data_raw)

            # Process media (updates note_data in-place)
            filenames_for_note = process_note_media(keep, note, note_data)
            all_expected_filenames.update(filenames_for_note)

            # Store both the original note object and the processed data dict
            all_notes_info.append((note, note_data))

        except Exception as e:
            print(f"Error processing note {note.id}: {e}")
            traceback.print_exc()
            download_errors += 1

    print(f"Finished processing {total_notes} notes from Keep.")
    if download_errors > 0:
        print(f"\nWarning: Encountered errors processing {download_errors} notes.")

    # --- Clean up Orphaned Attachments --- (Keep this)
    print("Checking for orphaned attachments...")
    try:
        if os.path.exists(ATTACHMENTS_DIR):
            existing_files = set(os.listdir(ATTACHMENTS_DIR))
            orphaned_files = existing_files - all_expected_filenames
            deleted_count = 0
            if orphaned_files:
                print(f"Found {len(orphaned_files)} orphaned attachments to delete.")
                for filename in orphaned_files:
                    try:
                        file_path = os.path.join(ATTACHMENTS_DIR, filename)
                        os.remove(file_path)
                        # print(f"Deleted orphaned attachment: {filename}") # Reduce verbosity
                        deleted_count += 1
                    except OSError as e:
                        print(f"Error deleting orphaned file {filename}: {e}")
                if deleted_count > 0:
                    print(f"Deleted {deleted_count} orphaned attachments.")
            # else:
                # print("No orphaned attachments found.") # Reduce verbosity
        # else:
            # print("Attachments directory does not exist, skipping cleanup.")
    except Exception as e:
        print(f"An error occurred during orphaned attachment cleanup: {e}")

    # --- Save raw note data to JSON --- (Save only the note_data part)
    print(f"\nSaving {len(all_notes_info)} processed notes data to {JSON_OUTPUT_FILE}...")
    try:
        # Extract just the note_data dictionaries for saving
        notes_data_to_save = [info[1] for info in all_notes_info]
        with open(JSON_OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(notes_data_to_save, f, indent=2, ensure_ascii=False)
        print("Successfully saved notes data to JSON.")
    except Exception as e:
        print(f"Error saving notes data to JSON: {e}")
        traceback.print_exc()

    # --- <<< CORE CHANGE: Process Notes using New Logic >>> ---
    if not args.skip_markdown:
        print("\nStarting Markdown file synchronization...")
        # Pass the list of tuples (note, note_data)
        if all_notes_info:
             process_and_save_notes(all_notes_info, VAULT_DIR) # Call the new function
        else:
             print("No notes data fetched from Keep, skipping Markdown synchronization.")
             # Optionally, run orphan check even if no notes fetched?
             # process_and_save_notes([], VAULT_DIR) # Would trigger only orphan check
    else:
        print("\nSkipping Markdown file synchronization as requested (--skip-markdown).")

    print("\nPull script finished.")


if __name__ == "__main__":
    main()
