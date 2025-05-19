import logging
import os
import gkeepapi
import keyring
import getpass
import sys
import gpsoauth
import random
import string
from dotenv import load_dotenv, set_key
import json
import re
from datetime import datetime, timezone
import yaml
import argparse
import traceback
import time
import hashlib
import io
import base64
from pathlib import Path
import requests
import mimetypes
import shutil
import glob

# --- Logging Setup ---
LOG_FILE = 'debug_sync.log'
# Clear log file at the start of the script run
if __name__ == "__main__" and os.path.exists(LOG_FILE):
    try:
        os.remove(LOG_FILE)
        print(f"Cleared old log file: {LOG_FILE}")
    except OSError as e:
        print(f"Warning: Could not clear old log file {LOG_FILE}: {e}")

logging.basicConfig(
    level=logging.INFO, # Default to INFO, can be overridden by --debug
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'), # Append mode
        logging.StreamHandler(sys.stdout) # Also log to console
    ]
)
logging.info("--- sync.py execution started ---")
# --- End Logging Setup ---

# --- Determine Local Timezone ---
LOCAL_TZ = None
try:
    LOCAL_TZ = datetime.now().astimezone().tzinfo
    # Logging of this will be done in main() after logger is fully set up
except Exception: # Broad exception as determining tz can be tricky
    pass # Warning will be logged in main() if it remains None
# --- End Local Timezone Determination ---

# --- Constants ---
SERVICE_NAME = "google-keep-token"
VAULT_DIR = "KeepVault"
ATTACHMENTS_DIR_NAME = "Attachments" # Relative to VAULT_DIR
ATTACHMENTS_VAULT_DIR = os.path.join(VAULT_DIR, ATTACHMENTS_DIR_NAME)
ARCHIVED_DIR = os.path.join(VAULT_DIR, "Archived")
TRASHED_DIR = os.path.join(VAULT_DIR, "Trashed")
CACHE_FILE = "keep_state.json"
JSON_OUTPUT_FILE = "keep_notes_pulled.json" # For debugging pull data
DEBUG = False
MAX_FILENAME_LENGTH = 90
RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"
}

# --- Sync Log Constants ---
SYNC_LOG_FILENAME = "_Sync_Log.md"
SYNC_LOG_TITLE = "Sync Log"


# --- UTF-8 Reconfiguration for stdout/stderr ---
def reconfigure_stdio():
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
            logging.debug("Reconfigured stdout and stderr to UTF-8.")
        except Exception as e:
            logging.warning(f"Failed to reconfigure stdout/stderr to UTF-8: {e}", exc_info=DEBUG)
reconfigure_stdio()


# --- Authentication Functions ---
def get_master_token(email):
    """
    Attempts to retrieve the master token from keyring.
    If not found, prompts for OAuth token and exchanges it.
    Stores the obtained token in keyring.
    """
    try:
        master_token = keyring.get_password(SERVICE_NAME, email)
        if master_token:
            logging.info(f"Found master token for {email} in keyring.")
            return master_token
    except keyring.errors.NoKeyringError:
        logging.warning("No keyring backend found. Token will not be stored securely.")
    except Exception as e:
        logging.warning(f"Could not access keyring: {e}. Token will not be stored securely.", exc_info=DEBUG)

    logging.info("-" * 60)
    logging.info("Master Token not found or accessible in keyring.")
    logging.info("You need an OAuth Token to generate a Master Token.")
    print("This Master Token grants broad access to your Google account - keep it secure.")
    print("Instructions:")
    print("1. Go to this link in your browser (you might need to use an incognito window):")
    print("   https://accounts.google.com/EmbeddedSetup")
    print("2. Sign in to the Google account you want to use.")
    print("3. Copy the long token that appears on the page (it usually starts with 'oauth2rt_').")
    print("4. Paste the token below when prompted.")
    logging.info("-" * 60)

    oauth_token = None
    while not oauth_token:
        oauth_token = getpass.getpass("Paste the OAuth Token here: ")
        if not oauth_token:
            print("OAuth Token cannot be empty.")

    android_id = ''.join(random.choices(string.hexdigits.lower(), k=16))
    logging.info(f"Using randomly generated Android ID: {android_id}")

    master_token = None
    logging.info("Attempting to exchange OAuth token for Master Token...")
    try:
        master_response = gpsoauth.exchange_token(email, oauth_token, android_id)
        if 'Token' in master_response:
            master_token = master_response['Token']
            logging.info("Successfully obtained Master Token.")
        else:
            logging.error("Could not obtain Master Token.")
            logging.error(f"Details: {master_response.get('Error', 'No error details provided.')}")
            if 'Error' in master_response and master_response['Error'] == 'BadAuthentication':
                logging.error("This often means the OAuth Token was incorrect or expired.")
            elif 'Error' in master_response and master_response['Error'] == 'NeedsBrowser':
                 logging.error("This might indicate that Google requires additional verification.")
            logging.error("Please double-check the OAuth token and try again.")
            return None
    except ImportError:
         logging.error("The 'gpsoauth' library is not installed. Please install it: pip install gpsoauth", exc_info=DEBUG)
         return None
    except Exception as e:
        logging.error(f"An unexpected error occurred during token exchange: {e}", exc_info=DEBUG)
        return None

    if master_token:
        try:
            keyring.set_password(SERVICE_NAME, email, master_token)
            logging.info(f"Master token for {email} securely stored in keyring.")
        except keyring.errors.NoKeyringError:
            pass # Already warned
        except Exception as e:
            logging.warning(f"Could not store master token in keyring: {e}", exc_info=DEBUG)
    return master_token

# --- Cache Functions ---
def load_cached_state():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                logging.info(f"Loading cached state from {CACHE_FILE}...")
                state = json.load(f)
                return state
        except (json.JSONDecodeError, IOError) as e:
            logging.warning(f"Error loading cached state: {e}. Performing a full sync.", exc_info=DEBUG)
    return None

def save_cached_state(keep):
    try:
        state = keep.dump()
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)
        logging.info(f"Saved state to {CACHE_FILE} for faster future syncs.")
    except Exception as e:
        logging.warning(f"Could not save state to cache file: {e}", exc_info=DEBUG)

# --- Markdown Processing ---
def escape_hashtags(text):
    if not text: return text
    return re.sub(r'(?<!\\)(^|\\s)#([^\s#])', r'\g<1>\\#\g<2>', text)

def unescape_hashtags(text):
    if not text: return text
    return re.sub(r'\\#([^\s#])', r'#\1', text)

def sanitize_filename(name, note_id):
    if not name: name = f"Untitled_{note_id}"
    sanitized = name.replace('/', '_')
    sanitized = re.sub(r'[<>:"\\|?*]', '', sanitized)
    sanitized = re.sub(r'[\x00-\x1f\x7f]', '', sanitized)
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()
    sanitized = sanitized[:MAX_FILENAME_LENGTH]
    sanitized = sanitized.rstrip('. ')
    name_part = sanitized.split('.')[0]
    if name_part.upper() in RESERVED_NAMES:
        sanitized = f"_{sanitized}"
    if not sanitized: sanitized = f"Note_{note_id}"
    sanitized = sanitized.strip()
    if not sanitized: sanitized = f"Note_{note_id}"
    return f"{sanitized}.md"

# --- Vault Structure and File Indexing ---
def create_vault_structure(base_path):
    paths = [base_path, ATTACHMENTS_VAULT_DIR, ARCHIVED_DIR, TRASHED_DIR]
    for path in paths:
        try:
            os.makedirs(path, exist_ok=True)
        except OSError as e:
            logging.error(f"Error creating directory {path}: {e}", exc_info=DEBUG)
            sys.exit(1)

def parse_markdown_file(filepath, for_push=False):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines or not lines[0].strip() == '---':
            logging.debug(f"Skipping {filepath} - Missing opening frontmatter delimiter.")
            return ({}, "".join(lines)) if for_push else None

        yaml_lines, content_lines = [], []
        in_yaml, yaml_end_found = False, False

        for i, line in enumerate(lines):
            stripped_line = line.strip()
            if i == 0 and stripped_line == '---':
                in_yaml = True
                continue
            elif in_yaml and stripped_line == '---':
                in_yaml, yaml_end_found = False, True
                continue
            if in_yaml: yaml_lines.append(line)
            elif yaml_end_found: content_lines.append(line)

        if not yaml_end_found and for_push: # For push, be more lenient if closing '---' is missing
            logging.warning(f"Frontmatter in {filepath} might be missing closing '---'. Parsing content after opening '---'.")
            # content_lines will be everything after the first '---'
            content_lines = lines[1:] # or decide to parse yaml_lines as is
        elif not yaml_end_found and not for_push:
            logging.warning(f"Skipping {filepath} (pull context) - Missing closing frontmatter delimiter. Friendly reminder to add '---' at the end of frontmatter if you want this file to be synced.")
            return None


        metadata = {}
        if yaml_lines:
            try:
                parsed_yaml = yaml.safe_load("".join(yaml_lines))
                if isinstance(parsed_yaml, dict): metadata = parsed_yaml
                else: logging.warning(f"Frontmatter in {filepath} did not parse as dict. Treating as empty.")
            except yaml.YAMLError as e:
                logging.error(f"Error parsing YAML in {filepath}: {e}. Treating as empty.", exc_info=DEBUG)
            except Exception as e: # Catch other potential errors during YAML parsing
                 logging.error(f"Unexpected error parsing YAML in {filepath}: {e}. Treating as empty.", exc_info=DEBUG)

        # Determine the 'updated_dt' for comparison/push logic
        # Use the LATER of the YAML 'updated' timestamp and the file modification time
        local_updated_dt_yaml = None
        yaml_updated_str = metadata.get('updated')

        if yaml_updated_str:
            try:
                # Attempt to parse YAML timestamp
                aware_dt = datetime.fromisoformat(str(yaml_updated_str))
                # Ensure it's timezone-aware, assume UTC if not specified in string
                if aware_dt.tzinfo is None:
                    # If LOCAL_TZ is available, assume naive YAML time is in local TZ
                    if LOCAL_TZ:
                         aware_dt = aware_dt.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
                    else:
                        # If LOCAL_TZ is not available, assume naive YAML time is UTC
                        aware_dt = aware_dt.replace(tzinfo=timezone.utc)
                else:
                    # If timezone is already in string, convert to UTC for consistency
                    aware_dt = aware_dt.astimezone(timezone.utc)
                local_updated_dt_yaml = aware_dt
                logging.debug(f"  PARSER: Parsed YAML 'updated' timestamp for {os.path.basename(filepath)}: {local_updated_dt_yaml}.")
            except (TypeError, ValueError) as e_ts:
                logging.warning(f"  PARSER: Could not parse YAML 'updated' timestamp ('{yaml_updated_str}') in {os.path.basename(filepath)}: {e_ts}. Ignoring YAML timestamp for comparison.", exc_info=DEBUG)
            except Exception as e: # Catch other potential errors during timestamp parsing
                 logging.warning(f"  PARSER: Unexpected error parsing YAML timestamp in {os.path.basename(filepath)}: {e}. Ignoring YAML timestamp for comparison.", exc_info=DEBUG)

        local_updated_dt_file = None
        try:
            mod_time = os.path.getmtime(filepath)
            # getmtime returns seconds since epoch. Convert to timezone-aware datetime (local time then convert to UTC)
            mod_dt_naive = datetime.fromtimestamp(mod_time)
            # If LOCAL_TZ is available, assume file modification time is in local TZ
            if LOCAL_TZ:
                 local_updated_dt_file = mod_dt_naive.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
            else:
                 # If LOCAL_TZ is not available, assume local system time (from fromtimestamp) is in a usable local timezone
                 # and convert to UTC.
                 local_updated_dt_file = mod_dt_naive.astimezone(timezone.utc) # fromtimestamp usually uses local time

            logging.debug(f"  PARSER: Got file modification time for {os.path.basename(filepath)}: {local_updated_dt_file}.")
        except OSError as e_mod_time:
            logging.warning(f"  PARSER: Could not get file modification time for {os.path.basename(filepath)}: {e_mod_time}. Cannot use file time for comparison.", exc_info=DEBUG)
        except Exception as e: # Catch other potential errors getting file time
             logging.warning(f"  PARSER: Unexpected error getting file modification time for {os.path.basename(filepath)}: {e}. Cannot use file time for comparison.", exc_info=DEBUG)

        # Use the later of the two timestamps
        local_updated_dt = None
        if local_updated_dt_yaml and local_updated_dt_file:
             local_updated_dt = max(local_updated_dt_yaml, local_updated_dt_file)
             logging.debug(f"  PARSER: Using later timestamp for {os.path.basename(filepath)}: {local_updated_dt}.")
        elif local_updated_dt_yaml:
             local_updated_dt = local_updated_dt_yaml
             logging.debug(f"  PARSER: Using YAML timestamp (file time unavailable) for {os.path.basename(filepath)}: {local_updated_dt}.")
        elif local_updated_dt_file:
             local_updated_dt = local_updated_dt_file
             logging.debug(f"  PARSER: Using file timestamp (YAML time unavailable/invalid) for {os.path.basename(filepath)}: {local_updated_dt}.")
        else:
             logging.debug(f"  PARSER: No valid local timestamp found for {os.path.basename(filepath)}.")

        metadata['updated_dt'] = local_updated_dt # Store the determined datetime object

        if for_push:
            # The logic for for_push metadata parsing already handles updated_dt
            # We just enhanced how updated_dt is determined above.
            return metadata, "".join(content_lines)
        else: # For pull
            if 'id' not in metadata: # Ensure 'id' is always present for pull index
                logging.debug(f"Skipping {filepath} (pull context) - missing 'id' in frontmatter.")
                return None
            # Ensure other timestamps are parsed to datetime objects if they exist
            for ts_key in ['created', 'edited']:
                if ts_key in metadata:
                    try:
                        ts_str = str(metadata[ts_key])
                        if ts_str:
                             aware_dt = datetime.fromisoformat(ts_str)
                             # Ensure it's timezone-aware, assume UTC if not specified in string
                             if aware_dt.tzinfo is None:
                                  if LOCAL_TZ:
                                      aware_dt = aware_dt.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
                                  else:
                                      aware_dt = aware_dt.replace(tzinfo=timezone.utc)
                             else:
                                  aware_dt = aware_dt.astimezone(timezone.utc)
                             metadata[f'{ts_key}_dt'] = aware_dt
                        else:
                            metadata[f'{ts_key}_dt'] = None
                    except (TypeError, ValueError) as e_ts:
                        logging.warning(f"Could not parse '{ts_key}' timestamp ('{metadata.get(ts_key)}') in {filepath}: {e_ts}.")
                        metadata[f'{ts_key}_dt'] = None
                    except Exception as e: # Catch other potential errors during timestamp parsing
                         logging.warning(f"Unexpected error parsing '{ts_key}' timestamp in {filepath}: {e}.", exc_info=DEBUG)
                else: metadata[f'{ts_key}_dt'] = None
            return metadata

    except FileNotFoundError:
        logging.error(f"File not found during parsing: {filepath}", exc_info=DEBUG)
        return (None, None) if for_push else None
    except Exception as e: # Catch all other errors during parsing
        logging.error(f"Error processing Markdown file {filepath}: {e}", exc_info=DEBUG)
        return (None, None) if for_push else None

def index_local_notes_for_pull(vault_base_path):
    logging.info("Indexing local Markdown files for pull...")
    local_index = {}
    scan_dirs = [vault_base_path, ARCHIVED_DIR, TRASHED_DIR]
    for directory in scan_dirs:
        if not os.path.exists(directory): continue
        for filename in os.listdir(directory):
            if filename.lower().endswith(".md"):
                filepath = os.path.join(directory, filename)
                metadata = parse_markdown_file(filepath, for_push=False)
                if metadata and 'id' in metadata:
                    note_id = str(metadata['id'])
                    if note_id in local_index:
                        logging.warning(f"Duplicate Keep ID '{note_id}' found locally: {filepath} and {local_index[note_id]['path']}. Skipping second.")
                    else:
                        local_index[note_id] = {'path': filepath, 'metadata': metadata}
    logging.info(f"Found {len(local_index)} unique notes with IDs in local vault (for pull).")
    return local_index

def index_local_files_for_push(vault_base_path):
    logging.debug("Indexing local Markdown files for push...")
    local_files = {}
    excluded_dirs_abs = {
        os.path.abspath(ATTACHMENTS_VAULT_DIR),
        os.path.abspath(os.path.join(VAULT_DIR, ".obsidian"))
    }
    # We want to include ARCHIVED_DIR and TRASHED_DIR for push, as they might contain notes to be updated.
    # The push logic itself will handle the archived/trashed status based on YAML.
    # The primary vault_base_path already covers non-archived/non-trashed notes.
    scan_root_dirs = [VAULT_DIR] # Start with the main vault directory

    for root_dir_to_scan in scan_root_dirs:
        if not os.path.exists(root_dir_to_scan):
            logging.warning(f"Directory {root_dir_to_scan} does not exist, skipping for push indexing.")
            continue

        for root, dirs, files in os.walk(root_dir_to_scan):
            # Filter out excluded directories from further traversal
            dirs[:] = [d for d in dirs if os.path.abspath(os.path.join(root, d)) not in excluded_dirs_abs]

            current_dir_abs = os.path.abspath(root)
            if any(current_dir_abs.startswith(excluded_abs) for excluded_abs in excluded_dirs_abs):
                continue # Skip if current directory is within an excluded one

            for file in files:
                if file.lower().endswith(".md"):
                    filepath = os.path.join(root, file)

                    # Skip the local sync log file from regular push indexing
                    if os.path.abspath(filepath) == os.path.abspath(os.path.join(VAULT_DIR, SYNC_LOG_FILENAME)):
                        logging.debug(f"PUSH_INDEX: Identified local sync log file '{filepath}'. Skipping regular push indexing.")
                        continue

                    metadata, content = parse_markdown_file(filepath, for_push=True)
                    if metadata is not None: # Ensure metadata parsing was successful
                         local_files[filepath] = {'metadata': metadata, 'content': content}
    logging.debug(f"Found {len(local_files)} local Markdown files to potentially push.")
    return local_files


# --- PULL: Media and Attachments ---
def _generate_attachment_metadata(blob_id, filename, blob_type_name, file_ext, blob):
    return {
        'id': blob_id, 'filename': filename, 'type': blob_type_name,
        'extension': file_ext,
        'extracted_text': blob.extracted_text if hasattr(blob, 'extracted_text') else None
    }

def get_file_extension_from_blob(blob):
    blob_type_name = "UNKNOWN"
    if hasattr(blob, 'type'):
        blob_type_name = blob.type.name if hasattr(blob.type, 'name') else str(blob.type)
    type_map = {
        'PHOTO': 'jpg', 'IMAGE': 'jpg', 'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif',
        'DRAWING': 'png', 'AUDIO': 'mp3', 'AUDIO_RECORDING': 'mp3', 'AMR': 'amr',
        '3GPP': '3gp', 'MP4': 'mp4', 'MPEG_AUDIO': 'mp3', 'VIDEO': 'mp4', 'PDF': 'pdf'
    }
    return type_map.get(blob_type_name, 'bin')

def get_file_extension_from_response(response, blob):
    if 'Content-Type' in response.headers:
        content_type = response.headers['Content-Type']
        ext = mimetypes.guess_extension(content_type)
        if ext:
            ext = ext.lstrip('.')
            if ext in ['jpe', 'jpeg']: ext = 'jpg'
            return ext
    try:
        import magic
        content_type = magic.from_buffer(response.content, mime=True)
        ext = mimetypes.guess_extension(content_type)
        if ext:
            ext = ext.lstrip('.')
            if ext in ['jpe', 'jpeg']: ext = 'jpg'
            return ext
    except ImportError: logging.debug("python-magic not installed, skipping file content type detection.")
    except Exception as e: logging.debug(f"Error detecting file type with magic: {e}")
    return get_file_extension_from_blob(blob)

def download_media_blob(keep, blob, note_id_for_log):
    try:
        blob_id = str(blob.id)
        initial_ext = get_file_extension_from_blob(blob)
        initial_filename = f"{blob_id}.{initial_ext}"
        initial_filepath = os.path.join(ATTACHMENTS_VAULT_DIR, initial_filename)

        blob_type_name = "UNKNOWN"
        if hasattr(blob, 'type'):
            blob_type_name = blob.type.name if hasattr(blob.type, 'name') else str(blob.type)

        if os.path.exists(initial_filepath):
            logging.debug(f"Attachment {initial_filename} (ID: {blob_id}) exists (initial guess), skipping download for note {note_id_for_log}.")
            return _generate_attachment_metadata(blob_id, initial_filename, blob_type_name, initial_ext, blob)

        possible_matches = glob.glob(os.path.join(ATTACHMENTS_VAULT_DIR, f"{blob_id}.*"))
        if possible_matches:
            existing_filepath = possible_matches[0]
            existing_filename = os.path.basename(existing_filepath)
            _, existing_ext_with_dot = os.path.splitext(existing_filename)
            actual_ext = existing_ext_with_dot.lstrip('.')
            logging.debug(f"Attachment {existing_filename} (ID: {blob_id}) exists (glob match), skipping download for note {note_id_for_log}.")
            return _generate_attachment_metadata(blob_id, existing_filename, blob_type_name, actual_ext, blob)

        media_url = keep.getMediaLink(blob)
        if not media_url:
            logging.warning(f"Could not get media link for blob {blob_id} in note {note_id_for_log}")
            return None

        response = requests.get(media_url, stream=True)
        if response.status_code != 200:
            logging.warning(f"Failed to download blob {blob_id} (note {note_id_for_log}): HTTP {response.status_code}")
            return None

        final_ext = get_file_extension_from_response(response, blob)
        final_filename = f"{blob_id}.{final_ext}"
        final_filepath = os.path.join(ATTACHMENTS_VAULT_DIR, final_filename)

        if final_filename != initial_filename and os.path.exists(final_filepath):
             logging.debug(f"Attachment {final_filename} (ID: {blob_id}) exists (corrected ext), skipping download for note {note_id_for_log}.")
             return _generate_attachment_metadata(blob_id, final_filename, blob_type_name, final_ext, blob)

        logging.info(f"Downloading attachment {final_filename} for note {note_id_for_log}...")
        with open(final_filepath, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192): f.write(chunk)
        return _generate_attachment_metadata(blob_id, final_filename, blob_type_name, final_ext, blob)

    except Exception as e:
        logging.error(f"Error processing blob {getattr(blob, 'id', 'UNKNOWN_BLOB_ID')} for note {note_id_for_log}: {e}", exc_info=DEBUG)
        return None

def process_note_media(keep, note, note_data_dict):
    processed_filenames = set()
    if 'attachments' not in note_data_dict: note_data_dict['attachments'] = []
    media_sources = []
    if hasattr(note, 'images') and note.images: media_sources.extend(note.images)
    if hasattr(note, 'drawings') and note.drawings: media_sources.extend(note.drawings)
    if hasattr(note, 'audio') and note.audio: media_sources.extend(note.audio)
    if hasattr(note, 'blobs') and note.blobs:
        processed_blob_ids = {a['id'] for a in note_data_dict['attachments'] if 'id' in a}
        media_sources.extend([b for b in note.blobs if str(b.id) not in processed_blob_ids])

    for medium in media_sources:
        try:
            attachment_info = download_media_blob(keep, medium, note.id)
            if attachment_info:
                if medium in getattr(note, 'images', []): attachment_info['media_type'] = 'image'
                elif medium in getattr(note, 'drawings', []): attachment_info['media_type'] = 'drawing'
                elif medium in getattr(note, 'audio', []): attachment_info['media_type'] = 'audio'
                else: attachment_info['media_type'] = 'blob'

                existing_ids = {a['id'] for a in note_data_dict['attachments']}
                if attachment_info['id'] not in existing_ids:
                    note_data_dict['attachments'].append(attachment_info)
                processed_filenames.add(attachment_info['filename']) # Add filename regardless of duplication in metadata list
        except Exception as e:
            logging.error(f"Error processing media item {getattr(medium, 'id', '?')} for note {note.id}: {e}", exc_info=DEBUG)
    return processed_filenames

# --- PULL: Note Conversion and Processing ---
class KeepEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, 'name'): return obj.name # Enums
        if isinstance(obj, datetime): return obj.isoformat().replace('+00:00', 'Z')
        try: return str(obj)
        except: return None
        return json.JSONEncoder.default(self, obj)

def make_serializable(obj):
    if isinstance(obj, gkeepapi.node.Node): # Handle gkeepapi Node objects (like Note, List, Label)
        data = {}
        # Common attributes
        for attr in ['id', 'title', 'archived', 'trashed', 'pinned', 'parent', 'server_id', 'merge_key']:
            if hasattr(obj, attr):
                data[attr] = make_serializable(getattr(obj, attr))
        
        if isinstance(obj, (gkeepapi.node.Note, gkeepapi.node.List)):
            data['text'] = obj.text # Keep text as is
            if hasattr(obj, 'timestamps'): data['timestamps'] = make_serializable(obj.timestamps)
            if hasattr(obj, 'color'): data['color'] = make_serializable(obj.color)
            if hasattr(obj, 'labels') and obj.labels: data['labels'] = [make_serializable(l) for l in obj.labels.all()]
            if hasattr(obj, 'annotations') and obj.annotations: data['annotations'] = make_serializable(obj.annotations)
            # Blobs (images, drawings, audio) are handled by process_note_media and added to 'attachments'
            if isinstance(obj, gkeepapi.node.List):
                 data['items'] = [{'text': item.text, 'checked': item.checked, 'id': item.id} for item in obj.items]

        elif isinstance(obj, gkeepapi.node.Label):
            data['name'] = obj.name
        
        # For timestamps specifically (e.g. gkeepapi.node.Timestamp)
        elif hasattr(obj, 'timestamp') and callable(obj.timestamp): # Check if it's a method
            return datetime.fromtimestamp(obj.timestamp(), timezone.utc).isoformat().replace('+00:00', 'Z')
        elif hasattr(obj, '_MAX_TIMESTAMP') or hasattr(obj, '_MIN_TIMESTAMP'): # Is it a Timestamp object itself?
             # Try to get the datetime object directly
             dt_obj = obj._save_helper() # This seems to give the raw datetime
             if isinstance(dt_obj, datetime):
                 return dt_obj.isoformat().replace('+00:00', 'Z')
             return str(obj) # Fallback

        return data

    elif hasattr(obj, '__dict__') and not isinstance(obj, datetime): # Generic objects, but not datetimes
        return {k: make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
    elif isinstance(obj, (list, tuple)):
        return [make_serializable(i) for i in obj]
    elif isinstance(obj, dict):
        return {k: make_serializable(v) for k, v in obj.items()}
    elif hasattr(obj, 'name'):  # Enums not caught by Node check
        return obj.name
    elif isinstance(obj, datetime):
         return obj.isoformat().replace('+00:00', 'Z') # Ensure UTC 'Z'
    else:
        return obj # Primitives or unhandled

def is_note_empty(note_obj, note_data_dict): # Pass both for flexibility
    has_title = bool(note_obj.title and note_obj.title.strip())
    has_text = bool(note_obj.text and note_obj.text.strip())
    # For lists, check items directly from note_obj if possible
    has_list_items = False
    if isinstance(note_obj, gkeepapi.node.List):
        has_list_items = bool(note_obj.items and any(item.text.strip() for item in note_obj.items))
    
    # Attachments check can use note_data_dict as it's populated by process_note_media
    has_attachments = bool(note_data_dict.get('attachments') and len(note_data_dict['attachments']) > 0)
    
    # Annotations check (can use note_obj)
    has_annotations = bool(note_obj.annotations and len(note_obj.annotations) > 0)
    
    is_empty = not (has_title or has_text or has_list_items or has_attachments or has_annotations)
    if is_empty:
        logging.debug(f"Note {note_obj.id} determined empty. Title: {has_title}, Text: {has_text}, List: {has_list_items}, Attach: {has_attachments}, Annot: {has_annotations}")
    return is_empty

def convert_note_to_markdown(note_obj, note_data_dict):
    # --- Markdown Body ---
    body_content = ""
    if isinstance(note_obj, gkeepapi.node.List):
        list_items_md = []
        for item in sorted(note_obj.items, key=lambda x: x.sort): # Sort by sort value
            if item.text: # Only include items with text
                checked_char = '[x]' if item.checked else '[ ]'
                list_items_md.append(f"- {checked_char} {escape_hashtags(item.text.rstrip())}")
        body_content = "\n".join(list_items_md)
    elif note_obj.text: # Regular note
        text_normalized = note_obj.text.replace('\r\n', '\n').replace('\r', '\n')
        lines = text_normalized.split('\n')
        stripped_trailing_lines = [line.rstrip() for line in lines]
        cleaned_text_block = '\n'.join(stripped_trailing_lines)
        if cleaned_text_block:
            body_content = escape_hashtags(cleaned_text_block)

    content_parts = [body_content] if body_content else []

    # --- Attachments Section (using note_data_dict) ---
    processed_attachments = note_data_dict.get('attachments', [])
    if processed_attachments:
        attachment_links = []
        for attachment_info in processed_attachments:
            attachment_filename = attachment_info.get('filename')
            if attachment_filename:
                # Relative path from VAULT_DIR, e.g., "Attachments/file.jpg"
                # os.path.basename(ATTACHMENTS_VAULT_DIR) gives "Attachments"
                attachment_rel_path = os.path.join(ATTACHMENTS_DIR_NAME, attachment_filename).replace("\\", "/")
                attachment_links.append(f"- ![[{attachment_rel_path}]]")
        if attachment_links:
            if content_parts and content_parts[-1] != "": content_parts.append("") # Separator
            content_parts.append("## Attachments")
            content_parts.extend(attachment_links)

    final_content_string = "\n".join(part for part in content_parts if part is not None).strip()


    # --- YAML Frontmatter ---
    yaml_metadata = {
        'id': note_obj.id,
        'title': note_obj.title if note_obj.title is not None else "",
        'color': note_obj.color.name,
        'pinned': note_obj.pinned
    }
    if note_obj.timestamps.created:
        dt_utc = note_obj.timestamps.created
        if LOCAL_TZ:
            yaml_metadata['created'] = dt_utc.astimezone(LOCAL_TZ).isoformat()
        else:
            yaml_metadata['created'] = dt_utc.isoformat().replace('+00:00', 'Z')
    if note_obj.timestamps.updated:
        dt_utc = note_obj.timestamps.updated
        if LOCAL_TZ:
            yaml_metadata['updated'] = dt_utc.astimezone(LOCAL_TZ).isoformat()
        else:
            yaml_metadata['updated'] = dt_utc.isoformat().replace('+00:00', 'Z')
    if hasattr(note_obj.timestamps, 'userEdited') and note_obj.timestamps.userEdited:
         dt_utc = note_obj.timestamps.userEdited
         if LOCAL_TZ:
             yaml_metadata['edited'] = dt_utc.astimezone(LOCAL_TZ).isoformat()
         else:
             yaml_metadata['edited'] = dt_utc.isoformat().replace('+00:00', 'Z')
    elif hasattr(note_obj.timestamps, 'edited') and note_obj.timestamps.edited: # Fallback
         dt_utc = note_obj.timestamps.edited
         if LOCAL_TZ:
             yaml_metadata['edited'] = dt_utc.astimezone(LOCAL_TZ).isoformat()
         else:
             yaml_metadata['edited'] = dt_utc.isoformat().replace('+00:00', 'Z')

    labels = note_obj.labels.all()
    if labels:
        yaml_metadata['tags'] = sorted([label.name.replace(' ', '_') for label in labels])

    yaml_metadata['archived'] = note_obj.archived
    yaml_metadata['trashed'] = note_obj.trashed

    yaml_string = yaml.dump(yaml_metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)
    
    logging.debug(f"PULL_CONVERT_MARKDOWN ({note_obj.id}): Final YAML:\n{yaml_string.strip()}")
    logging.debug(f"PULL_CONVERT_MARKDOWN ({note_obj.id}): Final Content (len={len(final_content_string)}): '{final_content_string[:100].replace(chr(10), chr(92) + 'n')}{'...' if len(final_content_string) > 100 else ''}'")

    return f"---\n{yaml_string.strip()}\n---\n{final_content_string}"

def run_pull(keep, args, counters):
    """Fetches notes from Google Keep, processes media, and updates/creates local Markdown files."""
    logging.info("--- Starting PULL Operation ---")
    create_vault_structure(VAULT_DIR)
    local_notes_index = index_local_notes_for_pull(VAULT_DIR) # {keep_id: {path: str, metadata: dict}}
    processed_keep_ids_from_remote = set()
    all_expected_attachment_filenames = set() # For cleaning orphaned attachments

    pulled_notes_for_json_debug = [] # For saving rawish data if needed

    logging.info(f"Processing {len(keep.all())} notes fetched from Google Keep...")
    for note_obj in keep.all():
        current_keep_id = note_obj.id

        # Skip the dedicated sync log note from regular pull processing
        if note_obj.title == SYNC_LOG_TITLE and not note_obj.trashed:
            logging.debug(f"PULL: Identified sync log note '{note_obj.title}' (ID: {current_keep_id}). Skipping regular pull processing as it will be handled separately.")
            processed_keep_ids_from_remote.add(current_keep_id) # Mark as seen
            continue

        processed_keep_ids_from_remote.add(current_keep_id)
        logging.debug(f"PULL: Processing Keep note ID: {current_keep_id}, Title: '{note_obj.title}'")

        # Create a serializable dict for media processing and potential JSON dump
        # This dict is modified by process_note_media
        try:
            # Start with basic serializable version, then add attachments
            note_data_dict = make_serializable(note_obj) # Basic conversion
            if 'attachments' not in note_data_dict: note_data_dict['attachments'] = [] # Ensure key exists
        except Exception as e_serial:
            logging.error(f"PULL: Error serializing base note object {current_keep_id}: {e_serial}", exc_info=DEBUG)
            counters['pull_errors'] += 1
            continue
            
        # Process and download media, updates note_data_dict['attachments']
        # and returns set of filenames for this note
        try:
            filenames_for_this_note = process_note_media(keep, note_obj, note_data_dict)
            all_expected_attachment_filenames.update(filenames_for_this_note)
        except Exception as e_media:
            logging.error(f"PULL: Error processing media for note {current_keep_id}: {e_media}", exc_info=DEBUG)
            counters['pull_errors'] += 1
            # Continue processing the note text if media fails, but log error

        if args.debug_json_output: # If user wants to dump the processed data
            pulled_notes_for_json_debug.append(note_data_dict)

        if is_note_empty(note_obj, note_data_dict): # Check emptiness after media processing
            logging.debug(f"PULL: Skipping note ID {current_keep_id}: Empty content.")
            counters['pull_skipped_empty'] += 1
            continue

        try:
            keep_title = note_obj.title
            keep_archived = note_obj.archived
            keep_trashed = note_obj.trashed
            # Ensure remote timestamp is in UTC
            keep_updated_dt = note_obj.timestamps.updated.replace(tzinfo=timezone.utc) if note_obj.timestamps.updated else None
            logging.debug(f"  PULL Details - ID: {current_keep_id}, Upd: {keep_updated_dt}, Arch: {keep_archived}, Trash: {keep_trashed}")

            target_dir = TRASHED_DIR if keep_trashed else (ARCHIVED_DIR if keep_archived else VAULT_DIR)
            target_filename = sanitize_filename(keep_title, current_keep_id)
            target_filepath_ideal = os.path.join(target_dir, target_filename)
            os.makedirs(target_dir, exist_ok=True)

            local_info = local_notes_index.get(current_keep_id)

            if local_info: # Note found locally
                local_filepath = local_info['path']
                local_metadata = local_info['metadata']
                local_updated_dt = local_metadata.get('updated_dt') # Parsed datetime or None
                
                # Convert local timestamp to UTC for comparison if it exists
                if local_updated_dt and local_updated_dt.tzinfo is None:
                    if LOCAL_TZ:
                        local_updated_dt = local_updated_dt.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
                    else:
                        local_updated_dt = local_updated_dt.replace(tzinfo=timezone.utc)
                
                logging.debug(f"  PULL: Found local for {current_keep_id} at {os.path.relpath(local_filepath)}. Local TS: {local_updated_dt}, Remote TS: {keep_updated_dt}")

                should_update_file_content = False
                if args.force_pull_overwrite:
                    should_update_file_content = True
                    logging.info(f"    PULL: --force-pull-overwrite used. Marking {current_keep_id} for update.")
                elif keep_updated_dt and local_updated_dt and keep_updated_dt > local_updated_dt:
                    should_update_file_content = True
                    logging.info(f"    PULL: Remote timestamp newer for {current_keep_id}. Marking for update.")
                elif not keep_updated_dt or not local_updated_dt: # Timestamps unreliable
                    # Heuristic: if timestamps are unreliable, check content hash
                    logging.warning(f"    PULL: Timestamps unreliable for {current_keep_id}. Comparing content hash.")
                    try:
                        expected_markdown = convert_note_to_markdown(note_obj, note_data_dict)
                        expected_hash = hashlib.sha256(expected_markdown.encode('utf-8')).hexdigest()[:8]
                        current_content_hash = "no_local_file_for_hash_check"
                        if os.path.exists(local_filepath):
                            with open(local_filepath, "r", encoding="utf-8") as f_read:
                                current_content_hash = hashlib.sha256(f_read.read().encode('utf-8')).hexdigest()[:8]
                        if expected_hash != current_content_hash:
                            should_update_file_content = True
                            logging.info(f"    PULL: Content hash mismatch for {current_keep_id} (Timestamps unreliable). Marking for update.")
                        else:
                            logging.debug(f"    PULL: Content hash matches for {current_keep_id} (Timestamps unreliable). Skipping update.")
                            counters['pull_skipped_no_change'] +=1
                    except Exception as e_hash_comp:
                        logging.error(f"    PULL: Error during hash comparison for {current_keep_id}: {e_hash_comp}. Defaulting to update.", exc_info=DEBUG)
                        should_update_file_content = True
                else: # Local is same or newer
                    logging.debug(f"    PULL: Local timestamp same or newer for {current_keep_id}. Skipping content update based on timestamp.")
                    counters['pull_skipped_no_change'] += 1

                if should_update_file_content:
                    logging.debug(f"    PULL: Updating content for {current_keep_id} in {os.path.relpath(local_filepath)}")
                    try:
                        updated_markdown = convert_note_to_markdown(note_obj, note_data_dict)
                        with open(local_filepath, "w", encoding="utf-8") as f: f.write(updated_markdown)
                        counters['pull_updated_local'] += 1
                        # Update in-memory metadata for subsequent move check
                        local_info['metadata']['title'] = keep_title
                        local_info['metadata']['archived'] = keep_archived
                        local_info['metadata']['trashed'] = keep_trashed
                        local_info['metadata']['updated'] = keep_updated_dt.isoformat().replace('+00:00', 'Z') if keep_updated_dt else None
                        local_info['metadata']['updated_dt'] = keep_updated_dt
                    except Exception as e_write:
                        logging.error(f"    PULL: Error writing updated file {local_filepath}: {e_write}", exc_info=DEBUG)
                        counters['pull_errors'] += 1
                        continue # Skip move check on write error

                # Location/Rename Check (using updated local_info if content was updated)
                # Determine where the file *should* be based on current (possibly updated) metadata
                current_local_title = local_info['metadata'].get('title', note_obj.title) # Fallback to note_obj.title
                current_local_archived = local_info['metadata'].get('archived', note_obj.archived)
                current_local_trashed = local_info['metadata'].get('trashed', note_obj.trashed)

                ideal_dir_after_update = TRASHED_DIR if current_local_trashed else \
                                         (ARCHIVED_DIR if current_local_archived else VAULT_DIR)
                ideal_filename_after_update = sanitize_filename(current_local_title, current_keep_id)
                ideal_filepath_after_update = os.path.join(ideal_dir_after_update, ideal_filename_after_update)
                os.makedirs(ideal_dir_after_update, exist_ok=True) # Ensure dir exists

                if os.path.normpath(local_filepath) != os.path.normpath(ideal_filepath_after_update):
                    logging.info(f"    PULL: File for {current_keep_id} needs move/rename from {os.path.relpath(local_filepath)} to {os.path.relpath(ideal_filepath_after_update)}")
                    final_target_for_move = ideal_filepath_after_update
                    # Collision check for move
                    move_counter = 1
                    while os.path.exists(final_target_for_move) and os.path.normpath(final_target_for_move) != os.path.normpath(local_filepath):
                        logging.warning(f"      PULL: Target move path {os.path.relpath(final_target_for_move)} exists. Appending counter.")
                        name_part, ext_part = os.path.splitext(ideal_filename_after_update)
                        final_target_for_move = os.path.join(ideal_dir_after_update, f"{name_part}_{move_counter}{ext_part}")
                        move_counter+=1
                        if move_counter > 20: # Safety break
                            logging.error(f"      PULL: Could not find unique name for moving {current_keep_id}. Skipping move.")
                            final_target_for_move = None; break
                    
                    if final_target_for_move and os.path.normpath(final_target_for_move) != os.path.normpath(local_filepath):
                        try:
                            shutil.move(local_filepath, final_target_for_move)
                            counters['pull_moved_local'] += 1
                            local_info['path'] = final_target_for_move # Update index
                        except Exception as e_move:
                            logging.error(f"    PULL: Error moving file {local_filepath} to {final_target_for_move}: {e_move}", exc_info=DEBUG)
                            counters['pull_errors'] += 1
            
            else: # Note is new locally
                logging.info(f"  PULL: Keep ID {current_keep_id} not found locally. Creating new file...")
                final_target_filepath_new = target_filepath_ideal
                new_file_counter = 1
                while os.path.exists(final_target_filepath_new): # Collision check for new file
                    logging.warning(f"    PULL: Target path {os.path.relpath(final_target_filepath_new)} exists for new note. Appending counter.")
                    name_part, ext_part = os.path.splitext(target_filename)
                    final_target_filepath_new = os.path.join(target_dir, f"{name_part}_{new_file_counter}{ext_part}")
                    new_file_counter += 1
                    if new_file_counter > 20: # Safety break
                        logging.error(f"    PULL: Could not find unique name for new note {current_keep_id}. Skipping creation.")
                        final_target_filepath_new = None; break
                
                if final_target_filepath_new:
                    try:
                        new_markdown = convert_note_to_markdown(note_obj, note_data_dict)
                        with open(final_target_filepath_new, "w", encoding="utf-8") as f: f.write(new_markdown)
                        counters['pull_created_local'] += 1
                        logging.info(f"    PULL: Created new file: {os.path.relpath(final_target_filepath_new)}")
                    except Exception as e_new_write:
                        logging.error(f"    PULL: Error writing new file {final_target_filepath_new}: {e_new_write}", exc_info=DEBUG)
                        counters['pull_errors'] += 1

        except Exception as e_proc_note:
            logging.error(f"  PULL: Unexpected error processing note {current_keep_id}: {e_proc_note}", exc_info=DEBUG)
            counters['pull_errors'] += 1
            if current_keep_id in local_notes_index: # Prevent deletion if error
                del local_notes_index[current_keep_id]

    # Clean up orphaned local notes
    orphaned_ids = set(local_notes_index.keys()) - processed_keep_ids_from_remote
    if orphaned_ids:
        logging.info(f"\nFound {len(orphaned_ids)} local notes not in Keep. Deleting local files...")
        for orphan_id in orphaned_ids:
            if orphan_id in local_notes_index:
                orphan_path = local_notes_index[orphan_id]['path']
                try:
                    logging.info(f"  PULL: Deleting orphaned file: {os.path.relpath(orphan_path)} (ID: {orphan_id})")
                    os.remove(orphan_path)
                    counters['pull_deleted_local_orphan'] += 1
                except OSError as e_del:
                    logging.error(f"  PULL: Error deleting orphaned file {orphan_path}: {e_del}", exc_info=DEBUG)
                    counters['pull_errors'] += 1

    # Clean up orphaned attachments
    logging.debug("PULL: Checking for orphaned attachments...")
    try:
        if os.path.exists(ATTACHMENTS_VAULT_DIR):
            existing_attachments = set(os.listdir(ATTACHMENTS_VAULT_DIR))
            orphaned_attachments = existing_attachments - all_expected_attachment_filenames
            if orphaned_attachments:
                logging.info(f"PULL: Found {len(orphaned_attachments)} orphaned attachments to delete.")
                for filename in orphaned_attachments:
                    try:
                        os.remove(os.path.join(ATTACHMENTS_VAULT_DIR, filename))
                        counters['pull_deleted_orphaned_attachments'] += 1
                    except OSError as e: logging.error(f"PULL: Error deleting orphaned attachment {filename}: {e}", exc_info=DEBUG)
    except Exception as e_clean_attach:
        logging.error(f"PULL: Error during orphaned attachment cleanup: {e_clean_attach}", exc_info=DEBUG)

    if args.debug_json_output and pulled_notes_for_json_debug:
        try:
            with open(JSON_OUTPUT_FILE, 'w', encoding='utf-8') as f_json:
                json.dump(pulled_notes_for_json_debug, f_json, indent=2, ensure_ascii=False, cls=KeepEncoder)
            logging.info(f"PULL: Saved detailed pulled notes data to {JSON_OUTPUT_FILE}")
        except Exception as e_json_dump:
            logging.error(f"PULL: Error saving debug JSON output: {e_json_dump}", exc_info=DEBUG)

    logging.info("--- PULL Operation Finished ---")


# --- PUSH: Note Comparison and Update Logic ---
def update_local_file_from_remote(gnote, local_filepath, keep_instance):
    """Updates the local .md file with content and metadata from the remote gnote. (Used by push cherry-pick)"""
    logging.info(f"  PUSH_CHERRYPICK: Updating local file '{os.path.basename(local_filepath)}' from remote note ID {gnote.id}")
    try:
        # This function is tricky because it needs to simulate `convert_note_to_markdown`
        # but using a `gnote` object directly.
        # For simplicity, let's adapt parts of `convert_note_to_markdown` here.
        # We need a `note_data_dict` equivalent for `convert_note_to_markdown`
        note_data_for_conversion = make_serializable(gnote) # Convert gnote to a dict structure
        # Attachments might need special handling if not directly on gnote in serializable form
        # Let's assume `process_note_media` would have populated it if we had the full pull flow here.
        # For cherry-pick, we might not have full attachment data. This is a simplification.
        if 'attachments' not in note_data_for_conversion: note_data_for_conversion['attachments'] = []
        # Manually add media that might be directly on the gnote object if not in `blobs`
        # This part is complex to replicate fully outside `process_note_media`
        # Simplification: Assume `gnote.blobs` covers what we need for text content and basic metadata.

        full_file_content = convert_note_to_markdown(gnote, note_data_for_conversion) # Use the main converter

        with open(local_filepath, 'w', encoding='utf-8') as f:
            f.write(full_file_content)
        logging.debug(f"    PUSH_CHERRYPICK: Successfully wrote remote content to {local_filepath}")
        return True
    except Exception as e:
        logging.error(f"    PUSH_CHERRYPICK: Error updating local file {local_filepath} from remote: {e}", exc_info=DEBUG)
        return False

def perform_cherry_pick_interaction(gnote, local_metadata, local_content_raw, local_filepath, keep_instance, args, vault_base_dir, counters):
    rel_filepath = os.path.relpath(local_filepath, vault_base_dir)
    note_id_str = local_metadata.get('id', 'NO_ID')
    print(f"\nCherry-pick required for: '{rel_filepath}' (ID: {note_id_str})")
    print("  Differences detected between local version and remote Google Keep note.")

    if args.dry_run:
        print("  [Dry Run] Would prompt to choose: (L)ocal, (R)emote, or (S)kip.")
        counters['push_cherrypick_dry_run_prompts'] += 1
        return 'DRY_RUN_PROMPT'

    while True:
        choice = input("    Choose version to keep: (L)ocal (push to Keep), (R)emote (overwrite local file), (S)kip this note [L/R/S]: ").lower()
        if choice == 'l':
            logging.info(f"  PUSH_CHERRYPICK: User chose LOCAL for '{rel_filepath}'. Queued for push.")
            counters['push_cherrypick_local_chosen'] += 1
            return 'CHOOSE_LOCAL'
        elif choice == 'r':
            logging.info(f"  PUSH_CHERRYPICK: User chose REMOTE for '{rel_filepath}'. Updating local file...")
            if update_local_file_from_remote(gnote, local_filepath, keep_instance): # Pass keep_instance
                logging.info(f"    PUSH_CHERRYPICK: Local file '{rel_filepath}' successfully updated from remote.")
                counters['push_cherrypick_remote_chosen_local_updated'] += 1
            else:
                logging.error(f"    PUSH_CHERRYPICK: Failed to update local file '{rel_filepath}' from remote.")
            return 'CHOOSE_REMOTE' # Indicates local was (or attempted to be) updated
        elif choice == 's':
            logging.info(f"  PUSH_CHERRYPICK: User chose to SKIP '{rel_filepath}'.")
            counters['push_cherrypick_user_skipped'] += 1
            return 'CHOOSE_SKIP'
        else:
            print("    Invalid choice. Please enter L, R, or S.")


def check_changes_needed_for_push(gnote, local_metadata, local_content_raw, keep_instance):
    note_id = local_metadata.get('id')
    if not note_id:
        logging.warning(f"PUSH_CHECK: Called for note without ID in local_metadata: {local_metadata.get('title')}")
        return False, [] # No ID, no changes

    logging.debug(f"PUSH_CHECK: Note ID: {note_id}, Title: '{local_metadata.get('title')}'")
    change_reasons = []

    # --- Local Data Preparation ---
    local_title_from_yaml = local_metadata.get('title', "") # Default to empty string
    local_color_str = local_metadata.get('color', 'WHITE').upper()
    local_pinned = local_metadata.get('pinned', False)
    local_archived = local_metadata.get('archived', False)
    local_trashed = local_metadata.get('trashed', False)
    local_labels_fm = local_metadata.get('tags', []) # List of strings
    local_updated_dt = local_metadata.get('updated_dt') # Parsed datetime obj or None

    # --- Remote Data ---
    remote_title = gnote.title if gnote.title is not None else ""
    remote_color = gnote.color # Enum
    remote_pinned = gnote.pinned
    remote_archived = gnote.archived
    remote_trashed = gnote.trashed
    remote_labels_set = {label.name.lower() for label in gnote.labels.all()} # Set of strings
    remote_updated_dt = gnote.timestamps.updated.replace(tzinfo=timezone.utc) if gnote.timestamps.updated else None
    
    logging.debug(f"  PUSH_CHECK Details - LocalTS: {local_updated_dt}, RemoteTS: {remote_updated_dt}")

    # --- Content Cleaning and Comparison ---
    # 1. Process local_content_raw: lstrip, handle H1, remove attachments, normalize, unescape
    temp_local_content = local_content_raw.lstrip()
    current_local_title_for_push = local_title_from_yaml # Start with YAML title

    h1_match = re.match(r'^#\s+(.*?)\r?\n', temp_local_content, re.MULTILINE)
    if h1_match:
        h1_title_content = h1_match.group(1).strip()
        # If YAML title was empty, use H1 content as title AND remove H1 from content body
        if not current_local_title_for_push:
            current_local_title_for_push = h1_title_content
            temp_local_content = temp_local_content[h1_match.end():].lstrip('\r\n')
            logging.debug(f"    PUSH_CHECK: Used H1 for title ('{current_local_title_for_push}'), H1 removed from content body.")
        # Else (YAML title exists), H1 in content is part of body, do not remove it from temp_local_content. current_local_title_for_push remains YAML title.
    
    # Ensure title is at least empty string if still None after H1 logic
    if current_local_title_for_push is None: current_local_title_for_push = ""


    lines_before_attachments = []
    found_attachments_header = False
    for line in temp_local_content.split('\n'):
        if line.strip() == "## Attachments":
            found_attachments_header = True; break
        lines_before_attachments.append(line)
    content_body_local_cleaned = '\n'.join(lines_before_attachments)
    content_body_local_cleaned = content_body_local_cleaned.replace('\r\n', '\n').replace('\r', '\n')
    
    # New step: Filter blank lines THEN rstrip each line
    lines_non_blank = [l for l in content_body_local_cleaned.split('\n') if l.strip() != ""]
    lines_stripped_trailing = [l.rstrip() for l in lines_non_blank]
    content_body_local_cleaned = '\n'.join(lines_stripped_trailing)
    
    content_body_local_cleaned = unescape_hashtags(content_body_local_cleaned).strip() # Final strip for leading/trailing on whole block

    # Process remote text similarly (normalize, filter blanks, rstrip lines, unescape, strip block)
    remote_text_for_compare = gnote.text if gnote.text else ""
    remote_text_for_compare = remote_text_for_compare.replace('\r\n', '\n').replace('\r', '\n')
    remote_lines_non_blank = [l for l in remote_text_for_compare.split('\n') if l.strip() != ""]
    remote_lines_stripped_trailing = [l.rstrip() for l in remote_lines_non_blank]
    remote_text_for_compare = '\n'.join(remote_lines_stripped_trailing)
    remote_text_for_compare = unescape_hashtags(remote_text_for_compare).strip()

    local_hash = hashlib.sha256(content_body_local_cleaned.encode('utf-8')).hexdigest()[:16]
    remote_hash = hashlib.sha256(remote_text_for_compare.encode('utf-8')).hexdigest()[:16]
    logging.debug(f"  PUSH_CHECK: Content Hashes - Local: {local_hash}, Remote: {remote_hash}")
    if local_hash != remote_hash:
        logging.debug(f"    PUSH_CHECK: -> Content change (Hash mismatch).")
        logging.debug(f"      Local Cleaned : '{content_body_local_cleaned[:80].replace(chr(10), chr(92)+'n')}{'...' if len(content_body_local_cleaned) > 80 else ''}'")
        logging.debug(f"      Remote Cleaned: '{remote_text_for_compare[:80].replace(chr(10), chr(92)+'n')}{'...' if len(remote_text_for_compare) > 80 else ''}'")
        change_reasons.append("content")

    # --- Metadata Comparisons ---
    # Timestamp (only if local is newer)
    if local_updated_dt and remote_updated_dt and local_updated_dt > remote_updated_dt:
        logging.debug(f"    PUSH_CHECK: -> Timestamp change (Local > Remote).")
        change_reasons.append("timestamp_local_newer")
    elif local_updated_dt and not remote_updated_dt: # Remote has no updated timestamp, local does
        logging.debug(f"    PUSH_CHECK: -> Timestamp change (Local has TS, Remote does not).")
        change_reasons.append("timestamp_local_has_remote_missing")


    # Title (using current_local_title_for_push which considers H1 if YAML title was empty)
    # Normalize titles for comparison: replace newlines/tabs with spaces, collapse multiple spaces, then strip.
    norm_local_title = ' '.join(current_local_title_for_push.replace('\n', ' ').replace('\t', ' ').split()).strip()
    norm_remote_title = ' '.join(remote_title.replace('\n', ' ').replace('\t', ' ').split()).strip()
    logging.debug(f"  PUSH_CHECK: Titles - Local Norm: '{norm_local_title}', Remote Norm: '{norm_remote_title}'")
    if norm_remote_title != norm_local_title:
        logging.debug(f"    PUSH_CHECK: -> Title change.")
        change_reasons.append("title")

    # Color
    try:
        target_color_enum = gkeepapi.node.ColorValue[local_color_str]
        if remote_color != target_color_enum:
            logging.debug(f"    PUSH_CHECK: -> Color change (Local: {local_color_str}, Remote: {remote_color.name}).")
            change_reasons.append("color")
    except KeyError: pass # Invalid local color, won't cause a push for color

    # Pinned
    if remote_pinned != local_pinned:
        logging.debug(f"    PUSH_CHECK: -> Pinned change (Local: {local_pinned}, Remote: {remote_pinned}).")
        change_reasons.append("pinned")

    # Archived
    if remote_archived != local_archived:
        logging.debug(f"    PUSH_CHECK: -> Archived change (Local: {local_archived}, Remote: {remote_archived}).")
        change_reasons.append("archived")

    # Trashed
    if remote_trashed != local_trashed: # Compare local YAML 'trashed' with remote gnote.trashed
         logging.debug(f"    PUSH_CHECK: -> Trashed change (Local: {local_trashed}, Remote: {remote_trashed}).")
         change_reasons.append("trashed")

    # Labels
    target_labels_set = {l.replace("_", " ").lower() for l in local_labels_fm} # Normalize local labels
    if target_labels_set != remote_labels_set:
        logging.debug(f"    PUSH_CHECK: -> Labels change (Local: {target_labels_set}, Remote: {remote_labels_set}).")
        if target_labels_set - remote_labels_set: change_reasons.append("labels_add")
        if remote_labels_set - target_labels_set: change_reasons.append("labels_remove")
    
    # List item comparison (if applicable)
    if isinstance(gnote, gkeepapi.node.List):
        # Convert local markdown list to a structure comparable with gnote.items
        # This requires parsing the local_content_raw for list items.
        # For simplicity in check_changes, this is a coarse check. update_gnote will do finer-grained.
        # A more robust check would parse local_content_raw into list items.
        # If content hash differs, it might be due to list changes.
        # A simple check: number of items or if any text/checked status differs.
        # This is complex to do perfectly here without full parsing, rely on content hash for now.
        # If content hash matched, but list structure metadata changed (e.g. a sort order attribute not in text)
        # that would be missed. But gkeepapi doesn't expose sort for items in a way that's easy to check against raw MD.
        pass


    # Determine if changes are material (i.e., not just timestamp related)
    # Define non-material reasons. Add to this list if other non-material reasons emerge.
    non_material_reasons_set = {'timestamp_local_newer', 'timestamp_local_has_remote_missing'}
    material_reasons = [r for r in change_reasons if r not in non_material_reasons_set]

    if not change_reasons:
        logging.debug(f"  PUSH_CHECK: No changes detected for {note_id} ('{local_metadata.get('title')}').")
    elif not material_reasons:
        logging.debug(f"  PUSH_CHECK: Non-material changes detected for {note_id} ('{local_metadata.get('title')}'). Reasons: {', '.join(change_reasons)}")
    else:
        # Log at INFO if there are material reasons
        logging.info(f"  PUSH_CHECK: Material change(s) detected for {note_id} ('{local_metadata.get('title')}'). Reasons: {', '.join(change_reasons)}")
    
    needs_push = bool(change_reasons) # This reflects if *any* difference was found
    return needs_push, change_reasons


def update_gnote_from_local_data(gnote, local_metadata, local_content_raw, keep_instance, counters):
    """Updates an existing gkeepapi Note/List object. Returns True if changes were made to gnote."""
    changes_made_to_gnote = False
    note_id = local_metadata.get('id', 'UNKNOWN_ID_IN_UPDATE')

    # --- Data from local_metadata ---
    local_title_from_yaml = local_metadata.get('title', "")
    local_color_str = local_metadata.get('color', 'WHITE').upper()
    local_pinned = local_metadata.get('pinned', False)
    local_archived = local_metadata.get('archived', False)
    local_trashed = local_metadata.get('trashed', False)
    local_labels_fm = local_metadata.get('tags', [])

    # --- Prepare local content and title for push (same logic as check_changes_needed_for_push) ---
    content_to_push = local_content_raw.lstrip()
    title_to_push = local_title_from_yaml

    h1_match = re.match(r'^#\s+(.*?)\r?\n', content_to_push, re.MULTILINE)
    if h1_match:
        h1_title = h1_match.group(1).strip()
        if not title_to_push: # YAML title was empty
            title_to_push = h1_title
            content_to_push = content_to_push[h1_match.end():].lstrip('\r\n')
            logging.debug(f"    PUSH_UPDATE ({note_id}): Using H1 for title ('{title_to_push}'), H1 removed from content.")
    if title_to_push is None: title_to_push = "" # Ensure not None

    lines_before_attachments = []
    for line in content_to_push.split('\n'):
        if line.strip() == "## Attachments": break
        lines_before_attachments.append(line)
    content_to_push = '\n'.join(lines_before_attachments)
    # content_to_push = content_to_push.replace('\r\n', '\n').replace('\r', '\n') # Already split by \n and rejoined
    content_to_push = unescape_hashtags(content_to_push).strip() # Strip leading/trailing on whole block

    # --- Apply changes to gnote object ---
    # Title
    # Normalize titles for comparison before assigning
    norm_push_title = ' '.join(title_to_push.replace('\n', ' ').replace('\t', ' ').split()).strip()
    norm_remote_title_current = ' '.join(gnote.title.replace('\n', ' ').replace('\t', ' ').split()).strip() if gnote.title else ""
    if norm_remote_title_current != norm_push_title:
        logging.info(f"  PUSH_UPDATE ({note_id}): Updating title to: '{norm_push_title}' (from '{norm_remote_title_current}')")
        gnote.title = norm_push_title # Assign the normalized one, or title_to_push if strictness isn't an issue for Keep
        changes_made_to_gnote = True

    # Content (Text Note or List Note)
    if isinstance(gnote, gkeepapi.node.Note):
        # Clean remote text for comparison (same way as check_changes)
        remote_text_cleaned = gnote.text.replace('\r\n', '\n').replace('\r', '\n') if gnote.text else ""
        remote_lines_nb = [l for l in remote_text_cleaned.split('\n') if l.strip() != ""]
        remote_lines_st = [l.rstrip() for l in remote_lines_nb]
        remote_text_cleaned = '\n'.join(remote_lines_st)
        remote_text_cleaned = unescape_hashtags(remote_text_cleaned).strip()

        if remote_text_cleaned != content_to_push:
            logging.info(f"  PUSH_UPDATE ({note_id}): Updating text content.")
            if DEBUG:
                logging.debug(f"    Local push content snippet: {content_to_push[:100].replace(chr(10), chr(92)+'n')}")
                logging.debug(f"    Remote curr content snippet: {remote_text_cleaned[:100].replace(chr(10), chr(92)+'n')}")
            gnote.text = content_to_push
            changes_made_to_gnote = True
            
    elif isinstance(gnote, gkeepapi.node.List):
        # This is where Obsidian Markdown list items need to be parsed and applied to gnote.items
        # For each line in content_to_push (which should be the list items):
        #   - Parse "- [x] Text" or "- [ ] Text"
        #   - Match with existing items in gnote.items by text or by ID (if we had IDs from MD)
        #   - Update existing, add new, remove deleted.
        # This is complex. A simpler approach for now is to clear and re-add if different.
        # Or, if check_changes_needed saw a content diff, just set the new text and let Keep parse it.
        # Gkeepapi might not directly support setting raw markdown for a list to be parsed.
        # It expects manipulation of `gnote.items`.

        # Create a representation of local list items
        local_list_items_parsed = []
        for line in content_to_push.split('\n'):
            line = line.strip()
            if not line.startswith("- ["): continue
            match = re.match(r'-\s*\[(x| )\]\s*(.*)', line, re.IGNORECASE)
            if match:
                local_list_items_parsed.append({
                    'text': match.group(2).strip(),
                    'checked': match.group(1).lower() == 'x'
                })
        
        # Compare with remote items: gnote.items is a list of ListItem objects
        # This needs a more robust diffing and applying mechanism.
        # For now, if the raw content_to_push (which is the MD list) differs from
        # a similar MD rendering of gnote.items, then we mark for update.
        current_remote_list_md_parts = []
        for item in sorted(gnote.items, key=lambda x: x.sort): # Use sort order
            checked_char = '[x]' if item.checked else '[ ]'
            current_remote_list_md_parts.append(f"- {checked_char} {item.text.rstrip()}") # item.text should be unescaped already
        current_remote_list_md = "\n".join(current_remote_list_md_parts)

        # Compare the generated MD from remote items with our `content_to_push`
        if current_remote_list_md != content_to_push:
            logging.info(f"  PUSH_UPDATE ({note_id}): Updating list items.")
            changes_made_to_gnote = True
            # Clear existing items and add new ones
            # We need to be careful about item IDs if we want to preserve them.
            # For now, simple clear and add. This will lose existing item IDs.
            existing_ids_to_text = {item.id: item.text for item in gnote.items}
            new_items_to_add = [] # list of (text, checked) tuples

            # Try to match new items to old items by text to preserve IDs somewhat
            # This is a very basic matching strategy.
            # A full diff algorithm would be better (e.g., using difflib)
            
            # Clear all items from the remote note
            while len(gnote.items) > 0:
                gnote.items.pop(0) # Remove from the beginning

            # Add items from local_list_items_parsed
            for local_item_data in local_list_items_parsed:
                # This creates new items, new IDs.
                gnote.add(local_item_data['text'], local_item_data['checked'])
            logging.debug(f"    PUSH_UPDATE ({note_id}): Cleared and re-added {len(local_list_items_parsed)} list items.")
        else:
            logging.debug(f"  PUSH_UPDATE ({note_id}): List items content matches. No direct list item update needed via clear/add.")


    # Color
    target_color_enum = None
    try: target_color_enum = gkeepapi.node.ColorValue[local_color_str]
    except KeyError: logging.warning(f"  PUSH_UPDATE ({note_id}): Invalid local color '{local_color_str}'. Skipping color update.")
    if target_color_enum and gnote.color != target_color_enum:
        logging.info(f"  PUSH_UPDATE ({note_id}): Updating color to {target_color_enum.name}")
        gnote.color = target_color_enum
        changes_made_to_gnote = True

    # Pinned
    if gnote.pinned != local_pinned:
        logging.info(f"  PUSH_UPDATE ({note_id}): Updating pinned to {local_pinned}")
        gnote.pinned = local_pinned
        changes_made_to_gnote = True

    # Archived
    if gnote.archived != local_archived:
        logging.info(f"  PUSH_UPDATE ({note_id}): Updating archived to {local_archived}")
        gnote.archived = local_archived # This archives/unarchives
        changes_made_to_gnote = True

    # Trashed
    if local_trashed and not gnote.trashed:
         logging.info(f"  PUSH_UPDATE ({note_id}): Trashing note.")
         gnote.trash() # gnote object's trashed status updates automatically
         changes_made_to_gnote = True
    elif not local_trashed and gnote.trashed:
         logging.info(f"  PUSH_UPDATE ({note_id}): Untrashing note.")
         gnote.untrash() # gnote object's trashed status updates
         changes_made_to_gnote = True

    # Labels
    current_remote_labels = {label.name.lower() for label in gnote.labels.all()}
    target_local_labels = {l.replace("_", " ").lower() for l in local_labels_fm}
    labels_to_add_names = target_local_labels - current_remote_labels
    labels_to_remove_names = current_remote_labels - target_local_labels

    for label_name in labels_to_add_names:
        keep_label = keep_instance.findLabel(label_name, create=True)
        if keep_label:
            logging.info(f"  PUSH_UPDATE ({note_id}): Adding label: {label_name}")
            gnote.labels.add(keep_label)
            changes_made_to_gnote = True
    for label_name in labels_to_remove_names:
        keep_label = keep_instance.findLabel(label_name) # Don't create if not found for removal
        if keep_label:
            logging.info(f"  PUSH_UPDATE ({note_id}): Removing label: {label_name}")
            gnote.labels.remove(keep_label)
            changes_made_to_gnote = True
    
    if not changes_made_to_gnote:
         logging.info(f"  PUSH_UPDATE ({note_id}): No direct changes applied to gnote object by this function.")
    return changes_made_to_gnote


def create_gnote_from_local_data(keep_instance, local_metadata, local_content_raw, local_filepath, counters):
    note_id_for_log = os.path.basename(local_filepath) # Use filepath for logs before ID exists
    logging.info(f"PUSH_CREATE: Creating new Keep note from {note_id_for_log}...")

    # --- Determine Title for new note (Priority: YAML -> Filename) ---
    title_for_new_note = local_metadata.get('title')
    if not title_for_new_note: # YAML title missing or empty
        base_fn, _ = os.path.splitext(os.path.basename(local_filepath))
        title_for_new_note = base_fn
        logging.debug(f"  PUSH_CREATE ({note_id_for_log}): Using filename as title: '{title_for_new_note}'")
    if not title_for_new_note: title_for_new_note = "" # Ensure it's at least an empty string

    # --- Prepare content for new note (Remove H1 if title came from H1, remove attachments section, unescape) ---
    content_for_new_note = local_content_raw.lstrip()
    # If title_for_new_note was derived from H1, that H1 should be removed from content.
    # This is implicitly handled if local_metadata.get('title') was empty and filename was used.
    # If local_metadata.get('title') was present, H1 in content is body.
    # If local_metadata.get('title') was empty, AND filename was used, then H1 in content is body.
    # This needs careful H1 removal only if the H1 was *the source* of the title.
    # The `title_to_push` logic in `update_gnote` is more robust. Let's adapt.
    
    # Re-evaluate H1 removal for create:
    # If YAML title exists, H1 in body is content.
    # If YAML title is empty, H1 in body becomes title, and is removed from body.
    # If YAML title is empty AND no H1, title is from filename, body is as-is.
    
    temp_title_from_yaml = local_metadata.get('title') # This is the original YAML title
    h1_match_create = re.match(r'^#\s+(.*?)\r?\n', content_for_new_note, re.MULTILINE)
    if h1_match_create:
        h1_title_candidate = h1_match_create.group(1).strip()
        if not temp_title_from_yaml: # YAML title was empty
            title_for_new_note = h1_title_candidate # H1 becomes the title
            content_for_new_note = content_for_new_note[h1_match_create.end():].lstrip('\r\n') # Remove H1 from body
            logging.debug(f"  PUSH_CREATE ({note_id_for_log}): Used H1 for new note title ('{title_for_new_note}'), H1 removed from body.")
    # If title_for_new_note is still from filename (no YAML title, no H1 title), it's already set.

    lines_before_attachments = []
    for line in content_for_new_note.split('\n'):
        if line.strip() == "## Attachments": break
        lines_before_attachments.append(line)
    content_for_new_note = '\n'.join(lines_before_attachments)
    content_for_new_note = unescape_hashtags(content_for_new_note).strip()

    # --- Get other attributes for new note ---
    local_color_str = local_metadata.get('color', 'WHITE').upper()
    local_pinned = local_metadata.get('pinned', False)
    local_archived = local_metadata.get('archived', False) # New notes are typically not archived/trashed by default
    local_trashed = local_metadata.get('trashed', False)   # but we'll respect YAML if set.
    local_labels_fm = local_metadata.get('tags', [])

    # --- Create Note or List based on content ---
    # Heuristic: if content contains "- [ ]" or "- [x]", treat as list.
    is_list_from_content = bool(re.search(r'-\s*\[( |x)\]', content_for_new_note, re.IGNORECASE))
    
    created_gnote = None
    if is_list_from_content:
        logging.debug(f"  PUSH_CREATE ({note_id_for_log}): Detected list content. Creating List.")
        created_gnote = keep_instance.createList(title_for_new_note)
        # Parse content_for_new_note and add items to created_gnote.items
        for line in content_for_new_note.split('\n'):
            line = line.strip()
            match = re.match(r'-\s*\[(x| )\]\s*(.*)', line, re.IGNORECASE)
            if match:
                item_text = match.group(2).strip()
                is_checked = match.group(1).lower() == 'x'
                if item_text: # Only add if there's text
                    created_gnote.add(item_text, is_checked, gkeepapi.node.NewListItemPlacementValue.Bottom)
    else:
        logging.debug(f"  PUSH_CREATE ({note_id_for_log}): Creating Note with title '{title_for_new_note}'.")
        created_gnote = keep_instance.createNote(title_for_new_note, content_for_new_note)

    # --- Set attributes on the new gnote ---
    created_gnote.pinned = local_pinned
    # Color (only if not default WHITE, as createNote defaults to WHITE)
    if local_color_str != 'WHITE':
        try:
            created_gnote.color = gkeepapi.node.ColorValue[local_color_str]
        except KeyError: logging.warning(f"  PUSH_CREATE ({note_id_for_log}): Invalid color '{local_color_str}' for new note. Using default.")
    
    # Labels
    for label_name_fm in local_labels_fm:
        label_name = label_name_fm.replace("_", " ") # Convert underscore to space for Keep
        keep_label_obj = keep_instance.findLabel(label_name, create=True)
        if keep_label_obj: created_gnote.labels.add(keep_label_obj)

    # Initial sync to get ID - this is done by the main push loop after all creations/updates in a batch
    # For now, we return the gnote, the main loop will sync.
    # After sync, we will need to update the local file with ID.

    # Handle archive/trash state for the new note *after* potential sync and ID assignment
    # These are applied after the main sync in the calling function.
    # created_gnote.archived = local_archived # This will be set after sync by caller
    # if local_trashed: created_gnote.trash() # This will be set after sync by caller

    return created_gnote # Return the object, caller handles sync and local file update


def run_push(keep, args, counters):
    """Scans local Markdown files, compares with Keep, and pushes changes."""
    logging.info("--- Starting PUSH Operation ---")
    
    # Index local files for push operation
    local_files_map = index_local_files_for_push(VAULT_DIR) # {filepath: {metadata:dict, content:str}}
    
    # Get all remote notes (already synced by main function)
    # We need a way to quickly find remote notes by ID.
    # keep.all() is fine, but for many notes, an index is better.
    # However, the number of notes is usually manageable for iterating here.
    remote_notes_index = {note.id: note for note in keep.all()}
    logging.debug(f"PUSH: Found {len(remote_notes_index)} notes in Google Keep after initial sync/resume.")

    actions_to_perform = [] # Store dicts: {'type': 'create'/'update', 'filepath': ..., 'gnote': ..., ...}
    
    # --- 1. Calculate Potential Changes (Iterate local files) ---
    logging.debug("PUSH: Calculating potential changes from local files...")
    for filepath, local_data in local_files_map.items():
        rel_filepath = os.path.relpath(filepath, VAULT_DIR)
        local_metadata = local_data['metadata']
        local_content_raw = local_data['content'] # Raw content from MD file
        local_keep_id = local_metadata.get('id')
        local_updated_dt = local_metadata.get('updated_dt') # Parsed datetime

        action_disposition = 'skip_no_decision' # Default
        conflict_details_for_automatic_exit = None


        try:
            if local_keep_id: # Local file has a Keep ID
                gnote = remote_notes_index.get(str(local_keep_id))
                if gnote: # Corresponding remote note exists
                    is_different, diff_reasons = check_changes_needed_for_push(gnote, local_metadata, local_content_raw, keep)
                    
                    if is_different:
                        # Determine action based on differences and sync mode
                        action_disposition = 'skip_no_decision' # Default
                        conflict_details_for_automatic_exit = None

                        # A note needs pushing if check_changes_needed_for_push found *any* difference
                        # that is not *just* the timestamp being newer.
                        material_changes_detected = any(reason != 'timestamp_local_newer' for reason in diff_reasons)

                        if not is_different:
                            # No differences detected at all
                            action_disposition = 'skip_no_change'
                            counters['push_skipped_no_change'] += 1
                            logging.debug(f"  PUSH: No changes detected for {local_keep_id} ('{gnote.title}'). Skipping.")
                        elif is_different and not material_changes_detected:
                            # Differences were detected, but the only reason was timestamp_local_newer.
                            # This means the file was likely just touched, not materially edited.
                            action_disposition = 'skip_no_material_change'
                            # Use a new counter for this specific skip reason
                            counters['push_skipped_no_material_change'] += 1
                            logging.debug(f"  PUSH: Differences detected for {local_keep_id} ('{gnote.title}'), but only timestamp is newer ({diff_reasons}). Skipping update to remote as no material change found.") # Changed to debug
                        elif args.automatic_sync:
                            # Material changes detected, in automatic sync mode
                            if args.cherry_pick:
                                logging.warning("  PUSH: --automatic-sync is enabled, --cherry-pick will be ignored.")
                            
                            remote_updated_dt = gnote.timestamps.updated.replace(tzinfo=timezone.utc) if gnote.timestamps.updated else None
                            local_updated_dt = local_metadata.get('updated_dt') # This now correctly uses the later of YAML/file time

                            if args.force_push:
                                action_disposition = 'update_remote'
                                logging.debug(f"  PUSH (AUTO): --force-push active for {local_keep_id}. Marking for update.")
                            # Check if local timestamp is valid AND (newer than remote OR remote is missing timestamp)
                            elif local_updated_dt and (remote_updated_dt is None or local_updated_dt > remote_updated_dt):
                                action_disposition = 'update_remote'
                                logging.debug(f"  PUSH (AUTO): Local timestamp ({local_updated_dt}) is valid and newer than remote ({remote_updated_dt}). Marking for update.")
                            else: # Material differences exist, but timestamps don't clearly favor local, and not forced.
                                # This includes cases where remote is newer, timestamps are equal, or local timestamp is None.
                                conflict_message = (
                                    f"Unresolved conflict for note ID {local_keep_id} ('{gnote.title}') in automatic mode.\n"
                                    f"  File: {rel_filepath}\n"
                                    f"  Differences: {', '.join(diff_reasons)}\n"
                                    f"  Local Timestamp: {local_updated_dt}, Remote Timestamp: {remote_updated_dt}\n"
                                    f"  Run manually or use --cherry-pick to resolve."
                                )
                                conflict_details_for_automatic_exit = conflict_message
                                action_disposition = 'exit_on_conflict' # Special disposition
                        elif args.cherry_pick:
                            # Material changes detected, in cherry-pick mode
                            decision = perform_cherry_pick_interaction(gnote, local_metadata, local_content_raw, filepath, keep, args, VAULT_DIR, counters)
                            if decision == 'CHOOSE_LOCAL': action_disposition = 'update_remote'
                            # CHOOSE_REMOTE (local updated), CHOOSE_SKIP, DRY_RUN_PROMPT => no remote update action
                        elif args.force_push: # Not cherry-pick, but force specified, AND material differences exist
                            action_disposition = 'update_remote'
                            logging.debug(f"  PUSH: --force-push specified for {local_keep_id} and material differences found. Marking for update.")
                        else: # Material differences exist, not cherry-picking, not forcing. Default logic.
                             remote_updated_dt = gnote.timestamps.updated.replace(tzinfo=timezone.utc) if gnote.timestamps.updated else None
                             local_updated_dt = local_metadata.get('updated_dt')

                             # In interactive mode without --force or --cherry-pick, if material differences exist,
                             # we push if the local timestamp is same or newer. Remote being strictly newer is a conflict.
                             if local_updated_dt and remote_updated_dt and local_updated_dt >= remote_updated_dt:
                                 action_disposition = 'update_remote' # Local timestamp is same or newer
                                 logging.debug(f"  PUSH: Material differences found for {local_keep_id}. Local timestamp same or newer. Marking for update.")
                             elif not remote_updated_dt and local_updated_dt:
                                  action_disposition = 'update_remote' # Remote has no timestamp, local does (with material diffs).
                                  logging.debug(f"  PUSH: Material differences found for {local_keep_id}. Remote timestamp missing. Marking for update.")
                             else:
                                  # Remote is clearly newer by timestamp, or timestamps are missing on both but material diffs exist.
                                  # This is a conflict in non-automatic, non-forced mode.
                                  # Given the previous logic in check_changes covers content/title/labels etc,
                                  # if we reach here and remote TS is newer, it's a genuine remote-newer conflict.
                                  logging.warning(f"  PUSH: Material differences found for {local_keep_id} ('{gnote.title}'), but remote timestamp ({remote_updated_dt}) is newer than local ({local_updated_dt}). Skipping push to avoid overwriting newer remote version.")
                                  counters['push_skipped_conflict_remote_newer'] += 1
                                  action_disposition = 'skip_conflict_remote_newer'
                    else: # Not different
                        action_disposition = 'skip_no_change'
                        counters['push_skipped_no_change'] += 1
                        logging.debug(f"  PUSH: No changes detected for {local_keep_id} ('{gnote.title}'). Skipping.")
                else: # Local ID exists, but no remote note (deleted in Keep)
                    logging.warning(f"  PUSH: Note ID {local_keep_id} for '{rel_filepath}' exists locally but not in Keep (deleted remotely). Skipping push. Consider removing ID from local file.")
                    counters['push_skipped_deleted_remotely'] += 1
                    action_disposition = 'skip_remote_deleted'
            else: # No local Keep ID (new local note)
                # Check if a note with the same title (or filename if title empty) already exists in Keep
                # This is to prevent accidental duplicates if IDs were stripped locally
                potential_title_from_yaml = local_metadata.get('title')
                potential_title_from_filename, _ = os.path.splitext(os.path.basename(filepath))
                title_to_check = potential_title_from_yaml if potential_title_from_yaml else potential_title_from_filename
                
                existing_remote_with_title = None
                if title_to_check: # Only check if we have a title candidate
                    for r_note in remote_notes_index.values():
                        if r_note.title and r_note.title.strip().lower() == title_to_check.strip().lower() and not r_note.trashed:
                            existing_remote_with_title = r_note
                            break
                
                if existing_remote_with_title:
                    logging.warning(f"  PUSH: Local file '{rel_filepath}' has no Keep ID, but a remote note with a similar title ('{existing_remote_with_title.title}', ID: {existing_remote_with_title.id}) already exists. Skipping creation to prevent duplicates.")
                    logging.warning(f"    Consider adding id: {existing_remote_with_title.id} to '{rel_filepath}' frontmatter if it's the same note, or rename local file.")
                    counters['push_skipped_potential_duplicate_new_note'] +=1
                    action_disposition = 'skip_potential_duplicate'
                else:
                    action_disposition = 'create_new_remote'
                    logging.info(f"  PUSH: Local file '{rel_filepath}' has no Keep ID. Marked for creation in Keep.")

            # Add to actions based on disposition
            if action_disposition == 'update_remote':
                actions_to_perform.append({'type': 'update', 'filepath': filepath, 'local_metadata': local_metadata, 'local_content_raw': local_content_raw, 'gnote_to_update': gnote})
            elif action_disposition == 'create_new_remote':
                actions_to_perform.append({'type': 'create', 'filepath': filepath, 'local_metadata': local_metadata, 'local_content_raw': local_content_raw})
            elif action_disposition == 'exit_on_conflict' and conflict_details_for_automatic_exit:
                logging.error("PUSH (AUTO): Exiting due to unresolved conflict.")
                print(f"AUTOMATIC SYNC ERROR: {conflict_details_for_automatic_exit}", file=sys.stderr)
                sys.exit(1) # Exit the script
        
        except Exception as e_analyze:
            actual_error_string = str(e_analyze)
            logging.debug(f"PUSH_EXCEPTION_HANDLER: Caught exception. String form: >>>{actual_error_string}<<<")

            # Check if the error is the specific 'push_skipped_no_material_change' case
            # which should have already been logged at DEBUG level by line ~1476.
            # Using 'in' for a more robust check against potential minor string variations (e.g., surrounding quotes if any)
            if 'push_skipped_no_material_change' in actual_error_string:
                logging.debug(f"PUSH: Analysis for {rel_filepath} resulted in '{actual_error_string}' status (handled as non-material skip).")
                # We might not even need to increment push_errors_analysis if this is considered a normal skip.
                # For now, keeping the counter increment to align with original behavior if an exception truly occurred.
                # If this path means NO actual error occurred, then the counter increment might be misleading.
                # However, altering counter logic is out of scope for reducing verbosity here.
            else:
                logging.error(f"PUSH: Error analyzing file {rel_filepath} for push: {e_analyze}", exc_info=DEBUG)
            counters['push_errors_analysis'] += 1


    # --- 2. Display Changes and Ask for Confirmation (if not dry_run or force_push) ---
    updates_planned = [a for a in actions_to_perform if a['type'] == 'update']
    creates_planned = [a for a in actions_to_perform if a['type'] == 'create']
    total_to_push = len(updates_planned) + len(creates_planned)
    proceed_with_push = False

    if args.dry_run:
        print("\n--- [Dry Run] PUSH: Potential Remote Changes ---")
        if creates_planned: print(f"Would create {len(creates_planned)} notes in Keep:")
        for item in creates_planned: print(f"  - From: {os.path.relpath(item['filepath'], VAULT_DIR)}")
        if updates_planned: print(f"Would update {len(updates_planned)} notes in Keep:")
        for item in updates_planned: print(f"  - ID {item['gnote_to_update'].id} from: {os.path.relpath(item['filepath'], VAULT_DIR)}")
        # Display cherry-pick dry run info
        if args.cherry_pick and counters['push_cherrypick_dry_run_prompts'] > 0:
            print(f"Would prompt for cherry-pick decisions on {counters['push_cherrypick_dry_run_prompts']} notes.")
        print("[Dry Run] No changes will be made to Google Keep.")
    elif not total_to_push:
        print("\nPUSH: No notes marked for creation or update in Google Keep.")
        # Report cherry-pick outcomes even if no push happens
        if args.cherry_pick and not args.automatic_sync: # Only report if cherry_pick was active and not overridden
            if counters['push_cherrypick_remote_chosen_local_updated'] > 0: print(f"  (Cherry-pick: {counters['push_cherrypick_remote_chosen_local_updated']} local files were updated from remote choice)")
            if counters['push_cherrypick_user_skipped'] > 0: print(f"  (Cherry-pick: {counters['push_cherrypick_user_skipped']} notes were skipped by user choice)")
    elif args.force_push or args.automatic_sync: # Proceed if force_push or automatic_sync enabled
        print("\n--- PUSH: Applying Changes to Keep ---")
        if args.force_push and not args.automatic_sync:
             print("(Note: --force-push specified, will overwrite remote if newer, unless cherry-pick)")
        elif args.automatic_sync:
            print("(Note: --automatic-sync enabled, proceeding with calculated changes)")
        if creates_planned: print(f"Will create {len(creates_planned)} notes in Keep.")
        if updates_planned: print(f"Will update {len(updates_planned)} notes in Keep.")
        proceed_with_push = True
    else: # Not dry run, not forced, not automatic_sync, and changes exist
        print("\n--- PUSH: Review Potential Changes to Google Keep ---")
        if creates_planned: print(f"Will create {len(creates_planned)} notes:")
        for item in creates_planned: print(f"  - From: {os.path.relpath(item['filepath'], VAULT_DIR)}")
        if updates_planned: print(f"Will update {len(updates_planned)} notes:")
        for item in updates_planned: print(f"  - ID {item['gnote_to_update'].id} from: {os.path.relpath(item['filepath'], VAULT_DIR)}")
        
        # Display cherry-pick outcomes if any happened
        if args.cherry_pick:
            if counters['push_cherrypick_remote_chosen_local_updated'] > 0: print(f"  (Cherry-pick: {counters['push_cherrypick_remote_chosen_local_updated']} local files were ALREADY updated from remote choice during analysis)")
            if counters['push_cherrypick_user_skipped'] > 0: print(f"  (Cherry-pick: {counters['push_cherrypick_user_skipped']} notes were SKIPPED by user choice during analysis)")
        
        if counters['push_skipped_conflict_remote_newer'] > 0:
            print(f"Skipped pushing {counters['push_skipped_conflict_remote_newer']} notes where remote was newer (no --force).")

        confirm = input("Proceed with pushing these changes to Google Keep? (y/N): ")
        if confirm.lower() == 'y':
            proceed_with_push = True
        else:
            print("Push to Keep aborted by user.")

    # --- 3. Execute Push Changes (if proceed_with_push) ---
    sync_needed_after_push = False
    if proceed_with_push and not args.dry_run:
        logging.info("PUSH: Applying changes to Google Keep...")
        for action in actions_to_perform:
            filepath = action['filepath']
            rel_filepath_log = os.path.relpath(filepath, VAULT_DIR)
            local_meta = action['local_metadata']
            local_content = action['local_content_raw']

            try:
                if action['type'] == 'update':
                    gnote_to_update = action['gnote_to_update']
                    logging.info(f"PUSH: Updating Keep note ID {gnote_to_update.id} from {rel_filepath_log}...")
                    if update_gnote_from_local_data(gnote_to_update, local_meta, local_content, keep, counters):
                        sync_needed_after_push = True
                        counters['push_updated_remote'] += 1
                    else:
                        logging.info(f"  PUSH: No actual changes made to remote note {gnote_to_update.id} by update_gnote function.")
                
                elif action['type'] == 'create':
                    logging.info(f"PUSH: Creating Keep note from {rel_filepath_log}...")
                    created_gnote = create_gnote_from_local_data(keep, local_meta, local_content, filepath, counters)
                    if created_gnote:
                        # The new gnote needs an ID from Keep. This requires a sync.
                        # We'll do one big sync at the end.
                        # For now, store the created_gnote and its original filepath to update its ID later.
                        action['created_gnote_object'] = created_gnote # Store for post-sync update
                        sync_needed_after_push = True # Mark that a sync is essential
                        counters['push_created_remote'] += 1
                    else:
                        logging.error(f"  PUSH: Failed to create gnote object for {rel_filepath_log}.")
                        counters['push_errors_apply'] += 1
            
            except Exception as e_apply:
                logging.error(f"PUSH: Error applying action '{action['type']}' for {rel_filepath_log}: {e_apply}", exc_info=DEBUG)
                counters['push_errors_apply'] += 1
        
        # --- 4. Final Sync after Push operations (if any changes made or new notes created) ---
        if sync_needed_after_push:
            logging.info("PUSH: Performing sync with Google Keep after push operations...")
            try:
                keep.sync()
                save_cached_state(keep) # Save state after successful sync
                logging.info("PUSH: Sync after push complete.")

                # Update local files that were newly created with their new Keep IDs and timestamps
                for action in actions_to_perform:
                    if action['type'] == 'create' and 'created_gnote_object' in action:
                        created_gnote = action['created_gnote_object']
                        original_filepath = action['filepath']
                        original_local_meta = action['local_metadata'] # Before creation
                        original_local_content = action['local_content_raw'] # Before creation

                        if created_gnote.id: # Check if ID was populated by sync
                            logging.info(f"  PUSH: Updating local file {os.path.relpath(original_filepath)} with new Keep ID: {created_gnote.id}")
                            try:
                                # Create new metadata with ID and fresh timestamps from created_gnote
                                updated_yaml_metadata = original_local_meta.copy() # Start with original
                                updated_yaml_metadata['id'] = created_gnote.id
                                updated_yaml_metadata['title'] = created_gnote.title # Use title from Keep
                                if created_gnote.timestamps.created:
                                    dt_utc_created = created_gnote.timestamps.created
                                    if LOCAL_TZ:
                                        updated_yaml_metadata['created'] = dt_utc_created.astimezone(LOCAL_TZ).isoformat()
                                    else:
                                        updated_yaml_metadata['created'] = dt_utc_created.isoformat().replace('+00:00', 'Z')
                                if created_gnote.timestamps.updated:
                                    dt_utc_updated = created_gnote.timestamps.updated
                                    if LOCAL_TZ:
                                        updated_yaml_metadata['updated'] = dt_utc_updated.astimezone(LOCAL_TZ).isoformat()
                                    else:
                                        updated_yaml_metadata['updated'] = dt_utc_updated.isoformat().replace('+00:00', 'Z')
                                
                                updated_yaml_metadata.pop('updated_dt', None) # Remove parsed dt object

                                # Ensure color in frontmatter reflects actual created note (Keep might default color)
                                updated_yaml_metadata['color'] = created_gnote.color.name.upper()
                                # Ensure labels are from the created note
                                if created_gnote.labels.all():
                                    updated_yaml_metadata['tags'] = sorted([lbl.name.replace(' ', '_') for lbl in created_gnote.labels.all()])
                                else:
                                    updated_yaml_metadata.pop('tags', None)


                                new_yaml_string = yaml.dump(updated_yaml_metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)
                                
                                # The original_local_content might have had H1 removed if it became the title.
                                # We need to ensure the content written back is correct.
                                # The `content_for_new_note` used in `create_gnote_from_local_data` is the correct body.
                                # Let's re-fetch that logic or pass it through.
                                # Simplification: use original_local_content, assuming H1 handling was for `create_gnote`'s parameters only.
                                # A more robust way: `created_gnote.text` or parsed list items, then re-MD-ify.
                                # For now, write back the *original* content body.
                                new_file_content = f"---\n{new_yaml_string.strip()}\n---\n{original_local_content}"

                                with open(original_filepath, 'w', encoding='utf-8') as f_update_local:
                                    f_update_local.write(new_file_content)
                                logging.debug(f"    Successfully updated frontmatter in {original_filepath} with ID {created_gnote.id}")
                            except Exception as e_update_local_id:
                                logging.error(f"    Error updating local file {original_filepath} with new ID {created_gnote.id}: {e_update_local_id}", exc_info=DEBUG)
                                counters['push_errors_local_id_update'] +=1
                        else:
                            logging.error(f"  PUSH: Failed to get ID for newly created note from {os.path.relpath(original_filepath)} after sync. Local file not updated with ID.")
                            counters['push_errors_local_id_update'] +=1
            except gkeepapi.exception.SyncException as e_sync_final:
                logging.error(f"PUSH: Error during final sync after push: {e_sync_final}", exc_info=DEBUG)
                counters['push_errors_final_sync'] += 1
            except Exception as e_final_push_logic:
                logging.error(f"PUSH: Unexpected error after push operations or during final sync: {e_final_push_logic}", exc_info=DEBUG)
                counters['push_errors_final_sync'] += 1 # Group under sync errors
        elif not counters['push_errors_apply'] > 0 and total_to_push > 0 :
             logging.info("PUSH: Changes were made to Keep, but final sync was skipped as 'sync_needed_after_push' was false (should not happen if changes occurred).")
        elif not sync_needed_after_push and not counters['push_errors_apply'] > 0: # No changes made that required a sync
             logging.info("PUSH: No remote changes made that required a final sync.")


    logging.info("--- PUSH Operation Finished ---")


# --- Sync Log Note Update Function ---
def update_sync_log_note(keep, counters, vault_dir, sync_start_time_iso, args):
    """
    Creates or updates a dedicated sync log note in Keep and locally.
    This note contains a summary of the last sync operation.
    """
    logging.info("SYNC_LOG_DEBUG: Entered update_sync_log_note function.") # ADDED DEBUG
    logging.info(f"Updating sync log note: {SYNC_LOG_TITLE}")
    sync_log_filepath = os.path.join(vault_dir, SYNC_LOG_FILENAME)
    current_op_time_utc = datetime.now(timezone.utc)
    sync_completed_time_iso = current_op_time_utc.isoformat().replace('+00:00', 'Z')

    # Prepare summary content
    summary_parts = []
    
    # Convert sync_start_time_iso (string from main, UTC 'Z') to local for display
    display_start_time_str = sync_start_time_iso # Fallback to original UTC string
    if LOCAL_TZ:
        try:
            # Parse the UTC 'Z' string
            dt_start_utc = datetime.fromisoformat(sync_start_time_iso.replace('Z', '+00:00'))
            display_start_time_str = dt_start_utc.astimezone(LOCAL_TZ).isoformat(sep=' ', timespec='seconds')
        except Exception as e_log_time:
            logging.warning(f"SYNC_LOG: Could not convert start time to local for log display: {e_log_time}")

    # Convert current_op_time_utc (datetime object, UTC) to local for display
    display_completed_time_str = sync_completed_time_iso # Fallback to original UTC string
    if LOCAL_TZ:
        try:
            display_completed_time_str = current_op_time_utc.astimezone(LOCAL_TZ).isoformat(sep=' ', timespec='seconds')
        except Exception as e_log_time:
            logging.warning(f"SYNC_LOG: Could not convert completed time to local for log display: {e_log_time}")

    summary_parts.append(f"Sync operation started: {display_start_time_str}")
    summary_parts.append(f"Sync operation completed: {display_completed_time_str}")
    summary_parts.append("") # Add a blank line

    summary_parts.append("## Pull Summary") # Changed to H2 Markdown header
    # summary_parts.append("--------------------") # Removed underline, H2 is enough
    if not args.skip_pull:
        summary_parts.append(f"  Local files created: {counters['pull_created_local']}")
        summary_parts.append(f"  Local files updated: {counters['pull_updated_local']}")
        summary_parts.append(f"  Local content updates skipped (remote not newer): {counters['pull_skipped_no_change']}")
        summary_parts.append(f"  Local files moved/renamed: {counters['pull_moved_local']}")
        summary_parts.append(f"  Orphaned local notes deleted: {counters['pull_deleted_local_orphan']}")
        summary_parts.append(f"  Orphaned local attachments deleted: {counters['pull_deleted_orphaned_attachments']}")
        summary_parts.append(f"  Empty remote notes skipped: {counters['pull_skipped_empty']}")
        if counters['pull_errors'] > 0:
            summary_parts.append(f"  Errors during pull: {counters['pull_errors']}")
    else:
        summary_parts.append("  Pull operation was skipped.")

    summary_parts.append("") # Add a blank line
    summary_parts.append("## Push Summary") # Changed to H2 Markdown header
    # summary_parts.append("--------------------") # Removed underline, H2 is enough
    if not args.skip_push:
        summary_parts.append(f"  Remote notes created in Keep: {counters['push_created_remote']}")
        summary_parts.append(f"  Remote notes updated in Keep: {counters['push_updated_remote']}")
        summary_parts.append(f"  Remote updates skipped (no changes): {counters['push_skipped_no_change']}")
        if counters['push_skipped_conflict_remote_newer'] > 0:
            summary_parts.append(f"  Skipped pushing {counters['push_skipped_conflict_remote_newer']} notes where remote was newer (no --force).")
        if counters['push_skipped_deleted_remotely'] > 0:
             summary_parts.append(f"  Skipped pushing {counters['push_skipped_deleted_remotely']} notes (deleted in Keep).")
        if counters['push_skipped_potential_duplicate_new_note'] > 0:
            summary_parts.append(f"  Skipped creating {counters['push_skipped_potential_duplicate_new_note']} new notes (potential title duplicate in Keep).")
        if counters['push_errors_analysis'] > 0:
             summary_parts.append(f"  Errors during push analysis: {counters['push_errors_analysis']}")
        if counters['push_errors_apply'] > 0:
             summary_parts.append(f"  Errors applying push changes to Keep: {counters['push_errors_apply']}")
        if counters['push_errors_final_sync'] > 0:
            summary_parts.append(f"  Errors during final sync after push: {counters['push_errors_final_sync']}")
        if counters['push_errors_local_id_update'] > 0:
            summary_parts.append(f"  Errors updating local files with new Keep IDs: {counters['push_errors_local_id_update']}")
        if args.cherry_pick:
            summary_parts.append("  Cherry-Pick Details:")
            if counters['push_cherrypick_dry_run_prompts'] > 0: summary_parts.append(f"    Dry run prompts: {counters['push_cherrypick_dry_run_prompts']}")
            if counters['push_cherrypick_local_chosen'] > 0: summary_parts.append(f"    User chose local: {counters['push_cherrypick_local_chosen']}")
            if counters['push_cherrypick_remote_chosen_local_updated'] > 0: summary_parts.append(f"    User chose remote (local updated): {counters['push_cherrypick_remote_chosen_local_updated']}")
            if counters['push_cherrypick_user_skipped'] > 0: summary_parts.append(f"    User skipped: {counters['push_cherrypick_user_skipped']}")

    else:
        summary_parts.append("  Push operation was skipped.")

    if args.dry_run:
        summary_parts.append("") # Add a blank line
        summary_parts.append("[Dry Run Mode] No actual changes were made by this sync operation.")

    new_content_for_log = "\n".join(summary_parts) # Reverted to \n for consistency

    gnote_log = None
    existing_log_id = None

    if os.path.exists(sync_log_filepath):
        local_meta_sync_log = parse_markdown_file(sync_log_filepath, for_push=False)
        if local_meta_sync_log and 'id' in local_meta_sync_log:
            existing_log_id = str(local_meta_sync_log['id'])
            try:
                candidate_note = keep.get(existing_log_id)
                if candidate_note: # Note with ID exists
                    if candidate_note.title == SYNC_LOG_TITLE and not candidate_note.trashed:
                        gnote_log = candidate_note
                        logging.debug(f"SYNC_LOG: Found note in Keep by ID {existing_log_id} from local file '{SYNC_LOG_FILENAME}'.")
                    elif candidate_note.trashed:
                         logging.warning(f"SYNC_LOG: Note with ID {existing_log_id} (expected for '{SYNC_LOG_TITLE}') is TRASHED in Keep. Will create a new one.")
                         # To ensure it's not used, explicitly set gnote_log to None
                         gnote_log = None
                    else: # ID exists, but title mismatch or other issue
                        logging.warning(f"SYNC_LOG: Note with ID {existing_log_id} found, but title is '{candidate_note.title}' (expected '{SYNC_LOG_TITLE}'). Will search by title or create new.")
                        gnote_log = None # Don't use this one, it might be a re-purposed ID
            except gkeepapi.exception.DoesNotExist:
                logging.debug(f"SYNC_LOG: ID {existing_log_id} from local '{SYNC_LOG_FILENAME}' not found in Keep.")
            except Exception as e_get_id:
                logging.warning(f"SYNC_LOG: Error fetching note by presumed ID {existing_log_id}: {e_get_id}", exc_info=DEBUG)

    if not gnote_log:
        logging.debug(f"SYNC_LOG: Searching for note in Keep by title: '{SYNC_LOG_TITLE}'")
        for note in keep.all(): # Iterate through all notes
            if note.title == SYNC_LOG_TITLE and not note.trashed:
                gnote_log = note
                logging.info(f"SYNC_LOG: Found existing note in Keep by title '{SYNC_LOG_TITLE}' (ID: {gnote_log.id}).")
                break
            elif note.title == SYNC_LOG_TITLE and note.trashed:
                 logging.warning(f"SYNC_LOG: A TRASHED note with title '{SYNC_LOG_TITLE}' (ID: {note.id}) exists. A new sync log note will be created if no active one is found.")


    try:
        if gnote_log: # Update existing remote note
            logging.info(f"SYNC_LOG: Updating remote note '{SYNC_LOG_TITLE}' (ID: {gnote_log.id}).")
            if gnote_log.text != new_content_for_log : gnote_log.text = new_content_for_log
            if gnote_log.title != SYNC_LOG_TITLE : gnote_log.title = SYNC_LOG_TITLE
            if gnote_log.archived : gnote_log.archived = False
            if gnote_log.trashed : gnote_log.untrash() # Make sure it's not trashed
            if not gnote_log.pinned : gnote_log.pinned = True # Pin it for visibility
        else: # Create new remote note
            logging.info(f"SYNC_LOG: Creating new remote note titled '{SYNC_LOG_TITLE}'.")
            gnote_log = keep.createNote(SYNC_LOG_TITLE, new_content_for_log)
            gnote_log.pinned = True

        if args.dry_run:
            logging.info(f"SYNC_LOG: [Dry Run] Would ensure '{SYNC_LOG_TITLE}' is up-to-date in Keep.")
            # For dry run, we need a placeholder gnote_log for local file writing if it was 'created'
            if not hasattr(gnote_log, 'id') or not gnote_log.id: # If it was a new note in dry run
                 # Invent temporary data for dry run local file
                 gnote_log.id = "dry_run_new_log_id"
                 gnote_log.timestamps.created = current_op_time_utc
                 gnote_log.timestamps.updated = current_op_time_utc
                 if not hasattr(gnote_log, 'color') or not gnote_log.color: # gkeepapi might not init color on createNote
                     gnote_log.color = gkeepapi.node.ColorValue.White


        else: # Not a dry run
            logging.debug("SYNC_LOG: Calling keep.sync() to commit log note changes.")
            keep.sync()
            save_cached_state(keep) # Save state after sync
            logging.info(f"SYNC_LOG: Remote note '{SYNC_LOG_TITLE}' (ID: {gnote_log.id}) saved. Updated: {gnote_log.timestamps.updated.isoformat()}")

        # Prepare YAML and write local file
        # Ensure timestamps object exists, especially for newly created notes pre-sync
        if not hasattr(gnote_log.timestamps, 'created') or not gnote_log.timestamps.created:
            gnote_log.timestamps.created = current_op_time_utc # Fallback for dry run or if sync didn't populate
        if not hasattr(gnote_log.timestamps, 'updated') or not gnote_log.timestamps.updated:
            gnote_log.timestamps.updated = current_op_time_utc # Fallback

        yaml_metadata = {
            'id': str(gnote_log.id), # Ensure ID is string
            'title': str(gnote_log.title),
            'updated': gnote_log.timestamps.updated.isoformat().replace('+00:00', 'Z'),
            'created': gnote_log.timestamps.created.isoformat().replace('+00:00', 'Z'),
            'pinned': gnote_log.pinned,
            'archived': gnote_log.archived, # Should be False
            'trashed': gnote_log.trashed,   # Should be False
            'color': gnote_log.color.name,
            'tags': ['sync_log'] # Add a specific tag
        }
        yaml_string = yaml.dump(yaml_metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)
        # Ensure a blank line after YAML frontmatter for better Markdown rendering
        local_log_markdown = f"---\n{yaml_string.strip()}\n---\n\n{new_content_for_log}"

        with open(sync_log_filepath, 'w', encoding='utf-8') as f:
            f.write(local_log_markdown)
        logging.info(f"SYNC_LOG: Local file '{sync_log_filepath}' for sync log (ID: {gnote_log.id}) has been updated.")

    except gkeepapi.exception.SyncException as e_sync:
        logging.error(f"SYNC_LOG: SyncException while updating log note: {e_sync}", exc_info=DEBUG)
    except Exception as e:
        logging.error(f"SYNC_LOG: Failed to update sync log note: {e}", exc_info=DEBUG)
        if args.dry_run:
             logging.error("SYNC_LOG: [Dry Run] Error occurred, see above. Log note would not have been updated.")
    # The erroneous recursive call block that was here has been removed.


# --- Main Execution ---
def main():
    reconfigure_stdio() # Ensure UTF-8 early
    sync_start_time = datetime.now(timezone.utc) # Record sync start time

    parser = argparse.ArgumentParser(description="Two-way sync between local Markdown vault and Google Keep.")
    parser.add_argument("email", nargs='?', default=None, help="Google account email (optional, reads from .env).")
    parser.add_argument("--full-sync", action="store_true", help="Ignore cached state for a full Keep sync.")
    parser.add_argument("--debug", action="store_true", help="Enable detailed debug logging (gkeepapi and script).")
    parser.add_argument("--dry-run", action="store_true", help="Simulate pull and push, make no actual changes.")
    
    # Pull specific args
    pull_group = parser.add_argument_group('Pull Options')
    pull_group.add_argument("--skip-markdown-conversion", action="store_true", help="PULL: Only download notes to JSON, skip local Markdown processing.")
    pull_group.add_argument("--force-pull-overwrite", action="store_true", help="PULL: Force overwrite local files even if remote timestamp isn't newer.")
    pull_group.add_argument("--debug-json-output", action="store_true", help="PULL: Save detailed JSON of pulled notes to keep_notes_pulled.json.")

    # Push specific args
    push_group = parser.add_argument_group('Push Options')
    push_group.add_argument("--force-push", action="store_true", help="PUSH: Force push local changes, potentially overwriting newer remote notes (unless cherry-pick).")
    push_group.add_argument("--cherry-pick", dest="cherry_pick", action="store_true", help="PUSH: For notes with differences, prompt user to choose between local and remote versions.")
    
    # Combined operation args
    parser.add_argument("--skip-pull", action="store_true", help="Skip the PULL operation.")
    parser.add_argument("--skip-push", action="store_true", help="Skip the PUSH operation.")
    parser.add_argument("--automatic-sync", action="store_true", help="Enable automatic sync mode: no prompts for push, exit on unresolved conflicts.")


    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
        gkeepapi.node.DEBUG = True # Enable gkeepapi's internal debug
        global DEBUG; DEBUG = True
        logging.debug("Debug logging enabled for script and gkeepapi.")
    else:
        # If not debug, set gkeepapi's logger to WARNING or ERROR to reduce its verbosity
        gkeepapi_logger = logging.getLogger('gkeepapi.parser')
        gkeepapi_logger.setLevel(logging.WARNING)

    if LOCAL_TZ:
        logging.info(f"Successfully determined local timezone: {LOCAL_TZ}. Timestamps in YAML will use this offset.")
    else:
        logging.warning("Could not automatically determine local timezone. Timestamps in YAML will be UTC ('Z').")

    load_dotenv()
    email = args.email or os.getenv("GOOGLE_KEEP_EMAIL")
    if not email:
        logging.error("Email address not provided via command line or .env (GOOGLE_KEEP_EMAIL).")
        sys.exit(1)
    if args.email and os.getenv("GOOGLE_KEEP_EMAIL") and args.email != os.getenv("GOOGLE_KEEP_EMAIL"):
        logging.warning(f"Provided email '{args.email}' differs from .env GOOGLE_KEEP_EMAIL '{os.getenv('GOOGLE_KEEP_EMAIL')}'. Using '{args.email}'.")

    master_token = os.getenv("GOOGLE_KEEP_MASTER_TOKEN")
    app_password = os.getenv("GOOGLE_KEEP_APP_PASSWORD")
    keep = gkeepapi.Keep()
    logged_in = False

    if not logged_in and not master_token: master_token = get_master_token(email)
    if master_token:
        try:
            logging.info("Attempting authentication using Master Token...")
            keep.authenticate(email, master_token, sync=False) # Sync=False initially
            logged_in = True
            logging.info("Authentication successful using Master Token.")
        except gkeepapi.exception.LoginException as e:
            logging.warning(f"Master Token authentication failed: {e}", exc_info=DEBUG)
            master_token = None
        except Exception as e_auth:
            logging.error(f"Unexpected error during master token auth: {e_auth}", exc_info=DEBUG)
            master_token = None


    if not logged_in:
        if not app_password:
            try: app_password = getpass.getpass(f"Enter App Password for {email} (or leave blank): ")
            except EOFError: app_password = None
        if app_password:
            try:
                logging.info("Attempting login using App Password...")
                keep.login(email, app_password, sync=False) # Sync=False initially
                logged_in = True
                logging.info("Login successful using App Password.")
            except gkeepapi.exception.LoginException as e:
                logging.warning(f"App Password login failed: {e}", exc_info=DEBUG)
                app_password = None
            except Exception as e_login:
                logging.error(f"Unexpected error during app password login: {e_login}", exc_info=DEBUG)
                app_password = None


    if not logged_in:
        logging.error("Authentication failed. Cannot proceed.")
        sys.exit(1)

    # Initial Sync with Keep
    logging.info("Performing initial sync with Google Keep service...")
    state = None
    if not args.full_sync: state = load_cached_state()
    
    try:
        # Determine the credential that worked, or default to master_token if both present
        auth_credential_for_resume = master_token if master_token else app_password
        if not auth_credential_for_resume: # Should not happen if logged_in is True
            logging.error("No valid authentication credential available for sync/resume. This is unexpected.")
            sys.exit(1)

        if state:
            logging.info("Resuming session with cached state...")
            keep.authenticate(email, auth_credential_for_resume, state=state, sync=True) # CORRECTED
        else:
            logging.info("Performing full sync as no cache state or --full-sync specified...")
            keep.sync()
        logging.info("Initial sync with Google Keep service complete.")
        save_cached_state(keep)
    except gkeepapi.exception.SyncException as e:
        logging.error(f"Error during initial Google Keep sync: {e}", exc_info=DEBUG)
        if not state: logging.error("Full sync failed.")
        else: logging.error("Resuming from cache failed. Try --full-sync.")
        sys.exit(1)
    except Exception as e_initial_sync:
        logging.error(f"Unexpected error during initial sync/resume: {e_initial_sync}", exc_info=DEBUG)
        sys.exit(1)

    # Initialize counters for summary
    counters = {
        'pull_created_local': 0, 'pull_updated_local': 0, 'pull_skipped_no_change':0,
        'pull_moved_local': 0, 'pull_deleted_local_orphan': 0, 'pull_skipped_empty': 0,
        'pull_errors': 0, 'pull_deleted_orphaned_attachments':0,
        
        'push_created_remote': 0, 'push_updated_remote': 0,
        'push_skipped_no_change': 0, 'push_skipped_conflict_remote_newer': 0,
        'push_skipped_deleted_remotely': 0, 'push_skipped_potential_duplicate_new_note': 0,
        'push_skipped_no_clear_local_precedence':0,
        'push_cherrypick_dry_run_prompts': 0, 'push_cherrypick_local_chosen': 0,
        'push_cherrypick_remote_chosen_local_updated': 0, 'push_cherrypick_user_skipped': 0,
        'push_errors_analysis': 0, 'push_errors_apply': 0, 'push_errors_final_sync':0,
        'push_errors_local_id_update':0,
    }
    mimetypes.init() # For PULL's attachment handling

    # Ensure vault structure exists before any operations that might need it
    create_vault_structure(VAULT_DIR)
    logging.debug(f"Ensured vault directory structure exists at: {VAULT_DIR}")

    # --- Run PULL Operation ---
    if not args.skip_pull:
        if args.dry_run: print("\n--- [Dry Run] Simulating PULL operation ---")
        run_pull(keep, args, counters)
        if args.dry_run: print("--- [Dry Run] PULL simulation finished ---")
        
        # After pull, if not skipping push, a resync might be beneficial if pull made many changes
        # or if there's a long pause, but typically push will use the `keep` object state.
        # For simplicity, push will operate on the `keep` object as modified by pull's syncs.
    else:
        logging.info("Skipping PULL operation as requested.")

    # --- Run PUSH Operation ---
    if not args.skip_push:
        if args.dry_run: print("\n--- [Dry Run] Simulating PUSH operation ---")
        # Push needs the latest state from Keep, which initial sync should have provided.
        # If pull ran and did its own syncs, `keep` object is up-to-date.
        # If pull was skipped, `keep` object is from initial sync.
        run_push(keep, args, counters)
        if args.dry_run: print("--- [Dry Run] PUSH simulation finished ---")
    else:
        logging.info("Skipping PUSH operation as requested.")

    # --- Summary ---
    print("\n--- Sync Summary ---")
    if not args.skip_pull:
        print("PULL Operation:")
        print(f"  Local files created: {counters['pull_created_local']}")
        print(f"  Local files updated: {counters['pull_updated_local']}")
        print(f"  Local content updates skipped (remote not newer): {counters['pull_skipped_no_change']}")
        print(f"  Local files moved/renamed: {counters['pull_moved_local']}")
        print(f"  Orphaned local notes deleted: {counters['pull_deleted_local_orphan']}")
        print(f"  Orphaned local attachments deleted: {counters['pull_deleted_orphaned_attachments']}")
        print(f"  Empty remote notes skipped: {counters['pull_skipped_empty']}")
        if counters['pull_errors'] > 0: print(f"  Errors during pull: {counters['pull_errors']}")
    
    if not args.skip_push:
        print("PUSH Operation:")
        print(f"  Remote notes created in Keep: {counters['push_created_remote']}")
        print(f"  Remote notes updated in Keep: {counters['push_updated_remote']}")
        print(f"  Remote updates skipped (no changes): {counters['push_skipped_no_change']}")
        if counters['push_skipped_conflict_remote_newer'] > 0:
            print(f"Skipped pushing {counters['push_skipped_conflict_remote_newer']} notes where remote was newer (no --force).")

    if args.dry_run:
        print("\n[Dry Run Mode] No actual changes were made to local files or Google Keep.")
    
    # Update the dedicated sync log note (after pull/push, before final console summary)
    if not args.dry_run: # Don't update log note file/remote on dry run, but summary construction can be tested by function if needed
        # The update_sync_log_note function has its own dry_run checks for remote operations
        logging.info("MAIN_DEBUG: About to call update_sync_log_note.")
        update_sync_log_note(keep, counters, VAULT_DIR, sync_start_time.isoformat().replace('+00:00', 'Z'), args)
        logging.info("MAIN_DEBUG: Returned from update_sync_log_note.")
    elif args.dry_run:
        print(f"\n[Dry Run] Sync log note ('{SYNC_LOG_FILENAME}') would be updated with the summary above.")
        logging.info(f"MAIN_DEBUG: Dry run - would have updated sync log note.")

    logging.info("--- sync.py execution finished ---")

if __name__ == "__main__":
    main() 