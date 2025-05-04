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

# --- Logging Setup ---
LOG_FILE = 'debug_sync.log'
# DO NOT clear log file here, pull.py should handle initial clearing
logging.basicConfig(
    level=logging.DEBUG, # Capture all levels of messages
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8', mode='a'), # Append mode
        # Optional: Keep console output, but maybe filter it later
        # logging.StreamHandler(sys.stdout)
    ]
)
logging.info("--- push.py execution started ---")
# --- End Logging Setup ---

# --- Constants ---
SERVICE_NAME = "google-keep-token"
VAULT_DIR = "KeepVault"
ATTACHMENTS_VAULT_DIR = os.path.join(VAULT_DIR, "Attachments")
ARCHIVED_DIR = os.path.join(VAULT_DIR, "Archived")
TRASHED_DIR = os.path.join(VAULT_DIR, "Trashed")
CACHE_FILE = "keep_state.json" # Use the same cache file as pull.py
DEBUG = False

# --- Authentication Functions (Copied from pull.py) ---

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

    android_id = ''.join(random.choices(string.hexdigits.lower(), k=16))
    print(f"Using randomly generated Android ID: {android_id}")

    master_token = None
    print("Attempting to exchange OAuth token for Master Token...")
    try:
        master_response = gpsoauth.exchange_token(email, oauth_token, android_id)
        if 'Token' in master_response:
            master_token = master_response['Token']
            print("Successfully obtained Master Token.")
        else:
            print("Error: Could not obtain Master Token.")
            print("Details:", master_response.get('Error', 'No error details provided.'))
            if 'Error' in master_response and master_response['Error'] == 'BadAuthentication':
                print("This often means the OAuth Token was incorrect or expired.")
            elif 'Error' in master_response and master_response['Error'] == 'NeedsBrowser':
                 print("This might indicate that Google requires additional verification.")
            print("Please double-check the OAuth token and try again.")
            return None

    except ImportError:
         print("Error: The 'gpsoauth' library is not installed.")
         print("Please install it by running: pip install gpsoauth")
         return None
    except Exception as e:
        print(f"An unexpected error occurred during token exchange: {e}")
        traceback.print_exc()
        return None

    if master_token:
        try:
            keyring.set_password(SERVICE_NAME, email, master_token)
            print(f"Master token for {email} securely stored in keyring.")
        except keyring.errors.NoKeyringError:
            pass
        except Exception as e:
            print(f"Warning: Could not store master token in keyring: {e}")

    return master_token

def load_cached_state():
    """Loads cached Google Keep state from file if it exists."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                print(f"Loading cached state from {CACHE_FILE}...")
                state = json.load(f)
                return state
        except (json.JSONDecodeError, IOError) as e:
            print(f"Error loading cached state: {e}. Performing a full sync.")
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

# --- Markdown Processing Functions ---

def unescape_hashtags(text):
    r"""Convert escaped hashtags (\#tag) back to normal hashtags (#tag)."""
    if not text:
        return text
    return re.sub(r'\\#(\\w)', r'#\\1', text)

def get_markdown_files(directory):
    """Finds all .md files in the vault, excluding Archived and Trashed."""
    md_files = []
    excluded_dirs = {ARCHIVED_DIR, TRASHED_DIR, ATTACHMENTS_VAULT_DIR, os.path.join(VAULT_DIR, ".obsidian")}

    for root, dirs, files in os.walk(directory):
        # Modify dirs in-place to prevent walking into excluded directories
        dirs[:] = [d for d in dirs if os.path.join(root, d) not in excluded_dirs]

        # Check if the current root is itself an excluded directory
        is_excluded = False
        for excluded in excluded_dirs:
             # Handle potential trailing slashes or backslashes
             norm_root = os.path.normpath(root)
             norm_excluded = os.path.normpath(excluded)
             if norm_root == norm_excluded or norm_root.startswith(norm_excluded + os.sep):
                  is_excluded = True
                  break
        if is_excluded:
            continue

        for file in files:
            if file.lower().endswith(".md"):
                md_files.append(os.path.join(root, file))
    return md_files

# --- Helper: Index Local Notes (Manual Parsing) ---
def parse_markdown_file(filepath):
    """Loads and parses a single markdown file manually, returning metadata and content."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        if not lines or not lines[0].strip() == '---':
            # print(f"  Info: Skipping file {filepath} - Missing opening frontmatter delimiter.")
            return {}, "".join(lines) # Return empty metadata and content if no frontmatter

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

        metadata = {}
        if yaml_lines:
            try:
                # Use safe_load for security
                parsed_yaml = yaml.safe_load("\n".join(yaml_lines))
                if isinstance(parsed_yaml, dict):
                    metadata = parsed_yaml
                else:
                    print(f"  Warning: Frontmatter in {filepath} did not parse as a dictionary. Treating as empty.")
            except yaml.YAMLError as e:
                print(f"  Error parsing YAML in {filepath}: {e}. Treating as empty.")

        # --- Add timestamp parsing for push logic ---
        if 'updated' in metadata:
            try:
                ts_str = str(metadata['updated']).rstrip('Z')
                if ts_str:
                    metadata['updated_dt'] = datetime.fromisoformat(ts_str).replace(tzinfo=timezone.utc)
                else:
                    metadata['updated_dt'] = None
            except (TypeError, ValueError):
                metadata['updated_dt'] = None
        else:
            metadata['updated_dt'] = None

        return metadata, "".join(content_lines)

    except FileNotFoundError:
        print(f"  Error: File not found during parsing: {filepath}")
        return None, None # Return None, None on file not found
    except Exception as e:
        print(f"  Error processing Markdown file {filepath}: {e}")
        traceback.print_exc()
        return None, None # Return None, None on other errors

def index_local_files_for_push(vault_base_path):
    """Finds all .md files and parses them for pushing using manual method."""
    print("Indexing local Markdown files for push...")
    local_files = {}
    scan_dirs = [vault_base_path, ARCHIVED_DIR, TRASHED_DIR]
    for directory in scan_dirs:
        if not os.path.exists(directory):
            continue
        for filename in os.listdir(directory):
            if filename.lower().endswith(".md"):
                filepath = os.path.join(directory, filename)
                metadata, content = parse_markdown_file(filepath)
                # Only index if parsing didn't return None for metadata
                if metadata is not None:
                     local_files[filepath] = {'metadata': metadata, 'content': content}
    print(f"Found {len(local_files)} local Markdown files to potentially push.")
    return local_files

# --- Google Keep Interaction Functions ---

def check_changes_needed(gnote, metadata, content, keep):
    """Compares local data with a gnote object without making changes. Returns True if differences exist."""
    note_id = metadata.get('id') # Use metadata which should have the parsed ID
    if not note_id:
        logging.warning(f"check_changes_needed called for note without ID in metadata: {metadata.get('title')}")
        return False # Cannot check without an ID

    logging.debug(f"Checking changes for note ID: {note_id}, Title: '{metadata.get('title')}'")

    # --- Get Local Data --- # Should already be passed in via metadata/content
    local_title = metadata.get('title')
    local_color_str = metadata.get('color', 'WHITE').upper()
    local_pinned = metadata.get('pinned', False)
    local_archived = metadata.get('archived', False)
    local_trashed = metadata.get('trashed', False)
    local_labels_fm = metadata.get('tags', [])
    local_updated_dt = metadata.get('updated_dt') # Parsed datetime obj or None

    # --- Get Remote Data --- # From gnote object
    remote_title = gnote.title
    remote_color = gnote.color
    remote_pinned = gnote.pinned
    remote_archived = gnote.archived
    remote_trashed = gnote.trashed
    remote_labels = {label.name.lower() for label in gnote.labels.all()}
    remote_updated_dt = gnote.timestamps.updated
    if remote_updated_dt:
        remote_updated_dt = remote_updated_dt.replace(tzinfo=timezone.utc)

    # --- Prepare Local Content for Comparison --- START
    try:
        logging.debug(f"    PUSH_PREP_DETAIL: Starting local content prep for {note_id}")
        local_content_step1 = content.lstrip() # Remove leading whitespace/newlines first
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 1 (lstrip) content: '{local_content_step1[:100]}...'") # Log step 1 result

        # Initialize step2 with step1 content
        local_content_step2 = local_content_step1
        # Attempt to find and remove H1
        h1_match = re.match(r'^#\s+(.*?)\r?\n', local_content_step1, re.MULTILINE)
        if h1_match:
            logging.debug(f"    PUSH_PREP_DETAIL: H1 found in local content.")
            h1_title_content = h1_match.group(1).strip()
            # **CRITICAL FIX**: Assign the H1-removed content correctly
            local_content_step2 = local_content_step1[h1_match.end():].lstrip('\r\n')
            if not local_title: # Use H1 content as title if YAML title is missing
                local_title = h1_title_content
        # Ensure local_title is at least an empty string if still None
        if local_title is None: local_title = ""
        # Log the result *after* the conditional H1 removal
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 2 (H1 removal) content: '{local_content_step2[:100]}...' Title: '{local_title}'") # Log step 2 result

        # --- The rest of the preparation steps use local_content_step2 ---
        attachment_header = "\n## Attachments"
        attachment_section_index = local_content_step2.find(attachment_header)
        local_content_step3 = local_content_step2 # Start step 3 with result of step 2
        if attachment_section_index != -1:
            logging.debug(f"    PUSH_PREP_DETAIL: Attachments section found in local content.")
            local_content_step3 = local_content_step2[:attachment_section_index]
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 3 (Attachment removal) content: '{local_content_step3[:100]}...'") # Log step 3 result

        local_content_step4 = local_content_step3.replace('\r\n', '\n').replace('\r', '\n')
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 4 (Line ending norm) content: '{local_content_step4[:100]}...'")

        # *** ADDED STEP: Filter blank lines ***
        local_lines_non_blank = [line for line in local_content_step4.split('\n') if line.strip() != ""]
        local_content_step4_no_blanks = '\n'.join(local_lines_non_blank)
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 4.5 (Filter blanks) content: '{local_content_step4_no_blanks[:100]}...'")

        # Apply line stripping to the non-blank content
        local_lines_stripped = [line.rstrip() for line in local_content_step4_no_blanks.split('\n')]
        local_content_step4_stripped_lines = '\n'.join(local_lines_stripped)

        local_content_cleaned = unescape_hashtags(local_content_step4_stripped_lines).strip(' \t')
        logging.debug(f"    PUSH_PREP_DETAIL: Local step 5 (Unescape/Strip/Line Rstrip) done. Final content: '{local_content_cleaned[:100]}...' Final length: {len(local_content_cleaned)}")

    except Exception as e_prep_local:
        logging.error(f"    PUSH_PREP_DETAIL: ERROR during local content preparation for {note_id}: {e_prep_local}")
        traceback.print_exc() # Log full traceback
        return False

    # --- Prepare Remote Content for Comparison (Apply SAME cleaning) --- START
    try:
        logging.debug(f"    PUSH_PREP_DETAIL: Starting remote content prep for {note_id}")
        remote_text_normalized = gnote.text.replace('\r\n', '\n').replace('\r', '\n')
        logging.debug(f"    PUSH_PREP_DETAIL: Remote step 1 (Line ending norm) done.")

        # *** ADDED STEP: Filter blank lines ***
        remote_lines_non_blank = [line for line in remote_text_normalized.split('\n') if line.strip() != ""]
        remote_text_normalized_no_blanks = '\n'.join(remote_lines_non_blank)
        logging.debug(f"    PUSH_PREP_DETAIL: Remote step 1.5 (Filter blanks) done.")

        # Apply line stripping to the non-blank content
        remote_lines_stripped = [line.rstrip() for line in remote_text_normalized_no_blanks.split('\n')]
        remote_text_normalized_stripped_lines = '\n'.join(remote_lines_stripped)

        remote_text_cleaned = unescape_hashtags(remote_text_normalized_stripped_lines).strip(' \t')
        logging.debug(f"    PUSH_PREP_DETAIL: Remote step 2 (Unescape/Strip/Line Rstrip) done. Final length: {len(remote_text_cleaned)}")
    except Exception as e_prep_remote:
        logging.error(f"    PUSH_PREP_DETAIL: ERROR during remote content preparation for {note_id}: {e_prep_remote}")
        traceback.print_exc() # Log full traceback
        return False
    # --- Prepare Remote Content for Comparison (Apply SAME cleaning) --- END

    # --- Perform Comparisons --- START 
    # (Detailed PUSH_CHECK_DETAIL logs start here - should be reached now)
    # 1. Timestamp Comparison
    change_reason = []
    can_compare_timestamps = isinstance(local_updated_dt, datetime) and isinstance(remote_updated_dt, datetime)
    # Force logging level for this specific block
    logger = logging.getLogger() 
    original_level = logger.level
    # logger.setLevel(logging.DEBUG)
    logging.debug(f"    PUSH_CHECK_DETAIL: Timestamps - Local: {local_updated_dt}, Remote: {remote_updated_dt}, Can Compare: {can_compare_timestamps}")
    if can_compare_timestamps:
        if local_updated_dt > remote_updated_dt:
            logging.debug(f"    PUSH_CHECK_DETAIL: -> Timestamp change detected: Local > Remote")
            change_reason.append("timestamp_local_newer")
    else:
        logging.warning(f"    PUSH_CHECK_DETAIL: -> Cannot compare timestamps reliably for {note_id}. Assuming no change based on timestamp.")

    # 2. Content Comparison (using fully cleaned versions)
    try: # Add try/except specifically around content comparison
        local_hash = hashlib.sha256(local_content_cleaned.encode('utf-8')).hexdigest()[:8]
        remote_hash = hashlib.sha256(remote_text_cleaned.encode('utf-8')).hexdigest()[:8]
        logging.debug(f"    PUSH_CHECK_DETAIL: Content Hashes - Local Cleaned: {local_hash}, Remote Cleaned: {remote_hash}")

        content_differs_by_hash = local_hash != remote_hash
        logging.debug(f"    PUSH_CHECK_DETAIL: Hashes differ? {content_differs_by_hash}")

        if content_differs_by_hash:
            logging.debug(f"    PUSH_CHECK_DETAIL: -> Content change detected (Hash mismatch).")
            logging.debug(f"      PUSH_CHECK_DETAIL: Local Snippet : '{local_content_cleaned[:80].replace('\\n', '\\n                     ')}{'...' if len(local_content_cleaned) > 80 else ''}'")
            logging.debug(f"      PUSH_CHECK_DETAIL: Remote Snippet: '{remote_text_cleaned[:80].replace('\\n', '\\n                     ')}{'...' if len(remote_text_cleaned) > 80 else ''}'")
            change_reason.append("content") # ONLY APPEND IF HASHES DIFFER
    except Exception as e_content_cmp:
         logging.error(f"    PUSH_CHECK_DETAIL: ERROR during content comparison for {note_id}: {e_content_cmp}")
         # Optionally append an error reason?
         # change_reason.append("content_comparison_error")

    # 3. Title Comparison
    logging.debug(f"    PUSH_CHECK_DETAIL: Titles - Local: '{local_title}', Remote: '{remote_title}'")
    if remote_title != local_title:
        logging.debug(f"    PUSH_CHECK_DETAIL: -> Title change detected.")
        change_reason.append("title")

    # 4. List Item Comparison (Placeholder)
    # if isinstance(gnote, gkeepapi.node.List):
    #     # TODO: Implement list item comparison check
    #     pass # Assuming no change for lists for now in check

    # 5. Color Comparison
    target_color_enum = None
    try:
        target_color_enum = gkeepapi.node.ColorValue[local_color_str]
    except KeyError:
        pass # Invalid local color, won't cause a push
    logging.debug(f"    PUSH_CHECK_DETAIL: Colors - Local: {local_color_str} ({target_color_enum}), Remote: {remote_color}")
    if target_color_enum and remote_color != target_color_enum:
            logging.debug(f"    PUSH_CHECK_DETAIL: -> Color change detected.")
            change_reason.append("color")

    # 6. Pinned Status
    logging.debug(f"    PUSH_CHECK_DETAIL: Pinned - Local: {local_pinned}, Remote: {remote_pinned}")
    if remote_pinned != local_pinned:
        logging.debug(f"    PUSH_CHECK_DETAIL: -> Pinned status change detected.")
        change_reason.append("pinned")

    # 7. Archived Status
    logging.debug(f"    PUSH_CHECK_DETAIL: Archived - Local: {local_archived}, Remote: {remote_archived}")
    if remote_archived != local_archived:
        logging.debug(f"    PUSH_CHECK_DETAIL: -> Archived status change detected.")
        change_reason.append("archived")

    # 8. Trashed Status
    logging.debug(f"    PUSH_CHECK_DETAIL: Trashed - Local: {local_trashed}, Remote: {remote_trashed}")
    if local_trashed != remote_trashed:
         logging.debug(f"    PUSH_CHECK_DETAIL: -> Trashed status change detected.")
         change_reason.append("trashed")

    # 9. Labels Comparison
    target_labels = {l.replace("_", " ").lower() for l in local_labels_fm}
    logging.debug(f"    PUSH_CHECK_DETAIL: Labels - Local: {target_labels}, Remote: {remote_labels}")
    labels_to_add = target_labels - remote_labels
    labels_to_remove = remote_labels - target_labels

    if labels_to_add:
        logging.debug(f"    PUSH_CHECK_DETAIL: -> Labels to add detected: {labels_to_add}")
        change_reason.append("labels_add")
    if labels_to_remove:
        logging.debug(f"    PUSH_CHECK_DETAIL: -> Labels to remove detected: {labels_to_remove}")
        change_reason.append("labels_remove")

    # --- Determine Final Result --- START
    needs_push = bool(change_reason)
    reasons_str = ', '.join(change_reason)
    logging.debug(f"    PUSH_CHECK_DETAIL: Final change_reason list: {change_reason}")
    logging.debug(f"    PUSH_CHECK_DETAIL: Final needs_push boolean: {needs_push}")
    if needs_push:
        logging.info(f"  Change(s) detected for {note_id}. Reasons: {reasons_str}")
    else:
        logging.info(f"  No changes detected for {note_id}.")
    # logger.setLevel(original_level) # Restore original level if changed
    return needs_push
    # --- Determine Final Result --- END

def update_gnote_from_local(gnote, metadata, content, keep):
    """Updates an existing gkeepapi Note/List object based on local data. Returns True if changes were made."""
    changed = False
    local_title = metadata.get('title')
    local_color_str = metadata.get('color', 'WHITE').upper()
    local_pinned = metadata.get('pinned', False)
    local_archived = metadata.get('archived', False)
    local_trashed = metadata.get('trashed', False)
    local_labels_fm = metadata.get('tags', [])

    # --- Prepare Local Content for Comparison/Push --- START

    # Clean content string before processing
    content = content.lstrip() # Remove leading whitespace/newlines

    # 1. Check for H1 title in content and remove it if found.
    h1_match = re.match(r'^#\\s+(.*?)\\r?\\n', content, re.MULTILINE)
    if h1_match:
        h1_title_content = h1_match.group(1).strip()
        content = content[h1_match.end():].lstrip('\\r\\n')
        if not local_title:
            local_title = h1_title_content
    if local_title is None:
        local_title = ""

    # 2. Remove Attachments section (if present)
    attachment_header = "\\n## Attachments"
    attachment_section_index = content.find(attachment_header)
    if attachment_section_index != -1:
        content = content[:attachment_section_index]

    # 3. Normalize line endings to \\n
    content = content.replace('\\r\\n', '\\n').replace('\\r', '\\n')

    # 4. Unescape hashtags and strip leading/trailing whitespace ONLY
    content = unescape_hashtags(content).strip(' \t')

    # Prepare remote content for comparison
    remote_text = gnote.text.replace('\\r\\n', '\\n').replace('\\r', '\\n')

    # --- Prepare Local Content for Comparison/Push --- END

    # --- Compare and Apply changes --- START
    # Compare title (now definitely set)
    if gnote.title != local_title:
        print(f"  Updating title: '{local_title}'")
        gnote.title = local_title
        changed = True

    # Compare cleaned & normalized content
    if isinstance(gnote, gkeepapi.node.Note):
        if remote_text != content:
            print("  Updating text content.")
            gnote.text = content
            changed = True
    elif isinstance(gnote, gkeepapi.node.List):
        # TODO: Add list comparison logic here if needed
        pass

    # Color comparison
    target_color_enum = None
    try:
        target_color_enum = gkeepapi.node.ColorValue[local_color_str]
    except KeyError:
        print(f"  Warning: Invalid local color string '{local_color_str}' found in YAML. Skipping color update.")

    if target_color_enum: # Only proceed if local color string was valid
        if gnote.color != target_color_enum:
            print(f"  Updating color: {target_color_enum.name}")
            gnote.color = target_color_enum
            changed = True
    # Note: We are not automatically changing remote colors back to WHITE if local is WHITE

    if gnote.pinned != local_pinned:
        print(f"  Updating pinned status: {local_pinned}")
        gnote.pinned = local_pinned
        changed = True

    if gnote.archived != local_archived:
        print(f"  Updating archived status: {local_archived}")
        gnote.archived = local_archived
        changed = True

    # Handle trash status carefully
    if local_trashed and not gnote.trashed:
         print("  Trashing note.")
         gnote.trash()
         changed = True # trash() implies a change to sync
    elif not local_trashed and gnote.trashed:
         print("  Untrashing note.")
         gnote.untrash()
         changed = True # untrash() implies a change to sync

    # Compare and update labels
    current_labels = {label.name.lower() for label in gnote.labels.all()}
    target_labels = {l.replace("_", " ").lower() for l in local_labels_fm} # Normalize local labels
    labels_to_add_names = target_labels - current_labels
    labels_to_remove_names = current_labels - target_labels

    if labels_to_add_names:
        for label_name in labels_to_add_names:
            keep_label = keep.findLabel(label_name, create=True)
            if keep_label:
                print(f"  Adding label: {label_name}")
                gnote.labels.add(keep_label)
                changed = True

    if labels_to_remove_names:
        for label_name in labels_to_remove_names:
            keep_label = keep.findLabel(label_name)
            if keep_label:
                print(f"  Removing label: {label_name}")
                gnote.labels.remove(keep_label)
                changed = True

    # TODO: Handle Attachments

    if not changed:
         print("  No differences found between local file and Keep note.")

    return changed

def create_gnote_from_local(keep, metadata, content, filepath):
    """Creates a new Note/List in Keep based on local data. Returns the new gnote object or None."""
    # --- Determine Title --- START
    # Priority 1: Title from YAML frontmatter
    local_title = metadata.get('title')

    # Priority 2: Filename (without extension) if YAML title is missing/empty
    if not local_title:
        base_filename = os.path.basename(filepath)
        local_title, _ = os.path.splitext(base_filename)
        print(f"  Using filename as title: '{local_title}'")

    # --- Determine Title --- END

    # Get other attributes from metadata
    local_color_str = metadata.get('color', 'WHITE').upper()
    local_pinned = metadata.get('pinned', False)
    local_archived = metadata.get('archived', False)
    local_trashed = metadata.get('trashed', False)
    local_labels_fm = metadata.get('tags', [])

    # --- Prepare Content for Creation --- START
    # 1. Remove potential H1 from content (as title is handled above)
    h1_match = re.match(r'^#\s+(.*?)\r?\n', content.lstrip(), re.MULTILINE)
    if h1_match:
        content = content.lstrip()[h1_match.end():].lstrip('\r\n')

    # 2. Remove Attachments section (if present)
    attachment_header = "\n## Attachments"
    attachment_section_index = content.find(attachment_header)
    if attachment_section_index != -1:
        content = content[:attachment_section_index]

    # 3. Normalize line endings & Unescape hashtags & strip trailing whitespace
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    content = unescape_hashtags(content).strip(' \t')
    # --- Prepare Content for Creation --- END

    print(f"Creating new Keep note from {os.path.basename(filepath)}...")
    # Pass the determined title and cleaned content
    gnote = keep.createNote(local_title, content)

    # Set non-color attributes
    gnote.pinned = local_pinned
    gnote.archived = local_archived

    # Set color only if it's not WHITE
    if local_color_str != 'WHITE':
        try:
            print(f"DEBUG: Setting non-white color for new note: {local_color_str}")
            gnote.color = gkeepapi.node.ColorValue[local_color_str]
        except KeyError:
            print(f"  Warning: Invalid color '{local_color_str}' specified for new note \"{local_title}\". Using default.")

    # Add labels
    for label_name_fm in local_labels_fm:
        label_name = label_name_fm.replace("_", " ")
        keep_label = keep.findLabel(label_name, create=True)
        if keep_label:
            gnote.labels.add(keep_label)

    # Sync, handle trash, update local frontmatter
    try:
        print("  Syncing Keep to get ID for new note...")
        keep.sync()
        print(f"  New Note ID: {gnote.id}")

        if local_trashed:
            print("  Trashing newly created note.")
            gnote.trash()

        # --- Update local file with ID and timestamps using PyYAML --- START
        try:
            # Use the title that was actually pushed to Keep
            updated_metadata = metadata.copy()
            updated_metadata['id'] = gnote.id
            updated_metadata['title'] = gnote.title # Get title from created gnote
            updated_metadata['created'] = gnote.timestamps.created.isoformat() if gnote.timestamps.created else "UNKNOWN"
            updated_metadata['updated'] = gnote.timestamps.updated.isoformat() if gnote.timestamps.updated else "UNKNOWN"
            updated_metadata['edited'] = gnote.timestamps.edited.isoformat() if gnote.timestamps.edited else "UNKNOWN"
            updated_metadata.pop('updated_dt', None)

            # Ensure color in frontmatter reflects the actual created note
            # (which defaults to WHITE if not set otherwise)
            updated_metadata['color'] = gnote.color.name.upper() # Use actual color

            yaml_string = yaml.dump(updated_metadata, allow_unicode=True, default_flow_style=False, sort_keys=False)

            # Re-read the *original* content to avoid writing the cleaned version back
            # However, we need to ensure the H1 isn't duplicated if it was present
            original_content_body = ""
            with open(filepath, 'r', encoding='utf-8') as f_orig:
                lines = f_orig.readlines()
                in_yaml_orig = False
                yaml_end_found_orig = False
                content_lines_orig = []
                for i, line in enumerate(lines):
                    stripped_line = line.strip()
                    if i == 0 and stripped_line == '---': in_yaml_orig = True; continue
                    if in_yaml_orig and stripped_line == '---': in_yaml_orig = False; yaml_end_found_orig = True; continue
                    if not in_yaml_orig and yaml_end_found_orig: content_lines_orig.append(line)
                original_content_body = "".join(content_lines_orig)

            # Remove H1 from original body if it was present and matched Keep title
            if original_content_body.lstrip().startswith(f"# {gnote.title}"):
                h1_match_orig = re.match(r'^#\s+.*?\r?\n', original_content_body.lstrip(), re.MULTILINE)
                if h1_match_orig:
                    original_content_body = original_content_body.lstrip()[h1_match_orig.end():]

            # Construct the new file content with updated YAML and original body
            new_file_content = f"---\n{yaml_string}---\n{original_content_body}"

            with open(filepath, 'w', encoding='utf-8') as f_write:
                f_write.write(new_file_content)
            print(f"  Updated frontmatter in {os.path.basename(filepath)} with new ID and fetched data.")
        except Exception as e_write:
            print(f"  Error updating frontmatter in {filepath}: {e_write}")
            traceback.print_exc()
        # --- Update local file with ID and timestamps using PyYAML --- END

        return gnote
    except gkeepapi.exception.SyncException as e_sync:
         print(f"  Error syncing to get new note ID or trash note: {e_sync}")
         return None
    except Exception as e_final:
         print(f"  Unexpected error after note creation: {e_final}")
         return None

# --- Main Execution ---

def main():
    # --- Reconfigure stdout for UTF-8 --- START
    # This is crucial for Windows environments where the default encoding (often cp1252)
    # might not support all characters found in filenames, especially when redirecting output.
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8') # Also configure stderr for consistency
            print("Reconfigured stdout and stderr to UTF-8.", file=sys.stderr) # Log to original stderr if needed
        except Exception as e:
            print(f"Warning: Failed to reconfigure stdout/stderr to UTF-8: {e}", file=sys.stderr)
    # --- Reconfigure stdout for UTF-8 --- END

    parser = argparse.ArgumentParser(description="Push Markdown notes from a local vault to Google Keep.")
    parser.add_argument("email", nargs='?', default=None, help="Google account email address (optional, reads from .env if omitted).")
    parser.add_argument("--full-sync", action="store_true",
                        help="Ignore cached state and perform a full Keep sync before pushing.")
    parser.add_argument("--debug", action="store_true",
                        help="Enable detailed debug logging for gkeepapi.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse files and check Keep, but don't make any changes.")
    parser.add_argument("-f", "--force", action="store_true",
                        help="Force push without confirmation, potentially overwriting newer remote notes.")

    args = parser.parse_args()

    if args.debug:
        gkeepapi.node.DEBUG = True
        print("Debug logging enabled.")
        global DEBUG
        DEBUG = True

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


    # --- Authentication ---
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
        if not app_password:
            try:
                app_password = getpass.getpass(f"Enter App Password for {email} (or leave blank to skip): ")
            except EOFError:
                app_password = None
        if app_password:
            try:
                print("Attempting login using App Password...")
                keep.login(email, app_password, sync=False)
                logged_in = True
                print("Login successful using App Password.")
            except gkeepapi.exception.LoginException as e:
                print(f"App Password login failed: {e}")
                app_password = None # Invalidate
            except Exception as e_login:
                 print(f"An unexpected error occurred during app password login: {e_login}")
                 app_password = None # Invalidate

    if not logged_in:
        print("Authentication failed. Cannot proceed.")
        sys.exit(1)

    # --- Initial Sync & Indexing --- START
    print("Performing initial sync with Google Keep...")
    state = None
    if not args.full_sync:
        state = load_cached_state()
    try:
        auth_credential = master_token or app_password
        if not auth_credential:
             print("Error: No valid authentication credential available for sync.")
             sys.exit(1)

        if state:
            keep.resume(email, auth_credential, state=state, sync=True)
        else:
            # Assume login/authenticate already happened, just sync
            keep.sync()

        print("Initial sync complete.")
        save_cached_state(keep) # Save state after initial sync

        # Build remote index
        print("Building index of remote Keep notes...")
        remote_index = {note.id: note for note in keep.all()}
        print(f"Found {len(remote_index)} notes in Google Keep.")

    except gkeepapi.exception.SyncException as e:
        print(f"Error during initial Google Keep sync: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during initial sync/resume: {e}")
        traceback.print_exc()
        sys.exit(1)
    # --- Initial Sync & Indexing --- END

    # --- Find and Process Local Markdown Files --- START
    local_files_to_process = index_local_files_for_push(VAULT_DIR)
    potential_actions = [] # List to store actions: {'action': 'create'|'update'|'conflict'|'skip_deleted', 'filepath': ..., 'metadata': ..., 'content': ..., 'gnote': ... (for update)}

    print("Calculating potential changes...")

    for filepath, data in local_files_to_process.items():
        rel_filepath = os.path.relpath(filepath, VAULT_DIR)
        # Add outer try-except for the whole analysis of a single file
        try: 
            print(f"Analyzing: {rel_filepath}")
            metadata = data['metadata']
            content = data['content']
            local_keep_id = metadata.get('id')
            local_updated_dt = metadata.get('updated_dt') # Parsed datetime or None

            action = {'filepath': filepath, 'metadata': metadata, 'content': content, 'gnote': None}

            # --- Start of inner logic --- 
            if local_keep_id:
                if local_keep_id in remote_index:
                    gnote = remote_index[local_keep_id]
                    remote_updated_dt = gnote.timestamps.updated.replace(tzinfo=timezone.utc) if gnote.timestamps.updated else None
                    should_push = False
                    action['gnote'] = gnote # Store gnote for potential update

                    # Compare timestamps
                    if args.force:
                        logging.debug(f"  --force specified: Checking changes for {local_keep_id} regardless of timestamp.")
                        # Check changes even if forcing, to add correct action type
                        if check_changes_needed(gnote, metadata, content, keep): 
                            should_push = True
                        else:
                             # If no changes needed even when forcing, don't mark for update
                             logging.debug(f"    No changes detected for {local_keep_id} even with --force. Skipping.")
                             action['action'] = 'skip_no_change' # Add a specific skip reason
                    elif local_updated_dt and remote_updated_dt:
                        if local_updated_dt > remote_updated_dt:
                            logging.debug(f"  Local timestamp newer for {local_keep_id}. Checking if changes needed.")
                            if check_changes_needed(gnote, metadata, content, keep):
                                 should_push = True
                            else:
                                 logging.debug(f"    Local timestamp newer but content/metadata identical for {local_keep_id}. Skipping.")
                                 action['action'] = 'skip_no_change'
                        elif remote_updated_dt > local_updated_dt:
                             logging.debug(f"  Conflict: Remote Keep note {local_keep_id} is newer. Will skip unless --force.")
                             action['action'] = 'conflict'
                        else: # Timestamps are equal
                             logging.debug(f"  Timestamps match for {local_keep_id}. Checking content differences...")
                             if check_changes_needed(gnote, metadata, content, keep):
                                 logging.debug(f"    Content/metadata differs. Marked for update.")
                                 should_push = True
                             else:
                                 logging.debug(f"    Content/metadata identical. Skipping.")
                                 action['action'] = 'skip_no_change'
                    else: # Timestamps cannot be compared reliably
                        logging.warning(f"  Warning: Cannot compare timestamps reliably for {local_keep_id}. Checking content...")
                        if check_changes_needed(gnote, metadata, content, keep):
                             logging.debug(f"    Content/metadata differs (unreliable timestamp). Marked for update.")
                             should_push = True
                        else:
                             logging.debug(f"    Content/metadata identical (unreliable timestamp). Skipping.")
                             action['action'] = 'skip_no_change'

                    if should_push:
                        action['action'] = 'update'

                else: # Case 2: Note exists locally, but not remotely (deleted in Keep)
                    logging.warning(f"  Warning: Note ID {local_keep_id} exists locally (in {rel_filepath}) but not found in Keep (deleted remotely?). Will skip.")
                    action['action'] = 'skip_deleted'

            else: # Case 3: Note exists locally, no ID (new local note)
                logging.info(f"  Local file {rel_filepath} has no Keep ID. Marked for creation.")
                action['action'] = 'create'
            # --- End of inner logic ---

            if action.get('action') and action['action'] != 'skip_no_change': # Only add if an actual action is planned
                potential_actions.append(action)

        except Exception as e_analyze: # Catch errors during analysis of this specific file
            logging.error(f"--- ERROR analyzing file {rel_filepath}: {e_analyze} ---")
            traceback.print_exc()
            # Optionally add an 'error' action type if needed, or just skip the file
            # potential_actions.append({'action': 'error', 'filepath': filepath, 'error': str(e_analyze)}) 

    # --- Calculate Potential Changes --- END


    # --- Display Changes and Ask for Confirmation --- START
    updates_planned = [a for a in potential_actions if a['action'] == 'update']
    creates_planned = [a for a in potential_actions if a['action'] == 'create']
    conflicts_found = [a for a in potential_actions if a['action'] == 'conflict']
    skipped_deleted = [a for a in potential_actions if a['action'] == 'skip_deleted']
    # Add other action types here if implemented (e.g., archive, trash)

    total_changes = len(updates_planned) + len(creates_planned)
    proceed = False

    if args.dry_run:
        print("--- [Dry Run] Potential Changes ---")
        if creates_planned: print(f"Would create {len(creates_planned)} notes:")
        for item in creates_planned: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)}")
        if updates_planned: print(f"Would update {len(updates_planned)} notes:")
        for item in updates_planned: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)} (ID: {item['metadata'].get('id')})")
        if conflicts_found: print(f"Conflicts (remote newer, would be skipped without --force): {len(conflicts_found)}")
        for item in conflicts_found: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)} (ID: {item['metadata'].get('id')})")
        if skipped_deleted: print(f"Skipped (deleted remotely?): {len(skipped_deleted)}")
        for item in skipped_deleted: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)} (ID: {item['metadata'].get('id')})")
        print("-" * 30)
        print("[Dry Run] No changes will be made.")
        proceed = False # Ensure no execution in dry run
    elif not total_changes:
        print("No notes marked for creation or update.")
        # Still report conflicts and skips if any
        if conflicts_found: print(f"Conflicts found (remote newer, skipped): {len(conflicts_found)}")
        if skipped_deleted: print(f"Skipped (deleted remotely?): {len(skipped_deleted)}")
        proceed = False # No changes to make
    elif args.force:
        print("--- Applying Changes (--force specified) ---")
        if creates_planned: print(f"Will create {len(creates_planned)} notes.")
        if updates_planned: print(f"Will update {len(updates_planned)} notes (overwriting conflicts if any).")
        if conflicts_found: print(f"  - Including {len(conflicts_found)} notes where remote was newer.")
        if skipped_deleted: print(f"Skipped (deleted remotely?): {len(skipped_deleted)}")
        proceed = True
    else: # Not dry run, not forced, and changes exist
        print("--- Review Potential Changes ---")
        if creates_planned: print(f"Will create {len(creates_planned)} notes:")
        for item in creates_planned: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)}")
        if updates_planned: print(f"Will update {len(updates_planned)} notes:")
        for item in updates_planned: print(f"  - {os.path.relpath(item['filepath'], VAULT_DIR)} (ID: {item['metadata'].get('id')})")
        if conflicts_found: print(f"Conflicts (remote newer, will be skipped): {len(conflicts_found)}")
        # Don't list conflicts here as they won't be acted upon without --force
        if skipped_deleted: print(f"Skipped (deleted remotely?): {len(skipped_deleted)}")
        # Don't list skipped_deleted here as they won't be acted upon

        print("-" * 30)
        confirm = input("Proceed with pushing these changes? (y/N): ")
        if confirm.lower() == 'y':
            proceed = True
        else:
            print("Push aborted by user.")
            proceed = False
    # --- Display Changes and Ask for Confirmation --- END


    # --- Execute Changes --- START
    notes_pushed_update = 0
    notes_pushed_create = 0
    notes_skipped_conflict = len(conflicts_found) if not args.force else 0 # Count conflicts only if not forcing
    notes_skipped_deleted = len(skipped_deleted)
    notes_failed = 0
    sync_needed = False

    if proceed and not args.dry_run:
        print("Applying changes to Google Keep...")
        for action_item in potential_actions:
            filepath = action_item['filepath']
            metadata = action_item['metadata']
            content = action_item['content']
            gnote = action_item.get('gnote') # Will be None for 'create'
            action_type = action_item['action']

            print(f"Processing: {os.path.relpath(filepath, VAULT_DIR)} (Action: {action_type})")

            try:
                if action_type == 'update':
                    if gnote: # Should always have gnote for update
                        if update_gnote_from_local(gnote, metadata, content, keep):
                            sync_needed = True
                            notes_pushed_update += 1
                            # Check if this was originally a conflict that got forced
                            if action_item in conflicts_found and args.force:
                                print(f"  Forced update for conflict on {gnote.id}")
                        else:
                             print("  No actual changes detected by update_gnote_from_local.")
                    else:
                         print(f"  Error: Missing gnote object for update action on {filepath}. Skipping.")
                         notes_failed += 1


                elif action_type == 'create':
                    created_gnote = create_gnote_from_local(keep, metadata, content, filepath)
                    if created_gnote:
                        # Add to remote index immediately in case needed by later steps (though unlikely here)
                        remote_index[created_gnote.id] = created_gnote
                        sync_needed = True
                        notes_pushed_create += 1
                    else:
                        notes_failed += 1
                        print(f"  Failed to create note for {filepath}")


                elif action_type == 'conflict':
                    # If we got here, it means proceed=True, which implies args.force=True
                    if args.force and gnote:
                         print(f"  Forcing update for conflict: {os.path.relpath(filepath, VAULT_DIR)}")
                         if update_gnote_from_local(gnote, metadata, content, keep):
                             sync_needed = True
                             notes_pushed_update += 1
                         else:
                             print("  No actual changes detected by update_gnote_from_local during forced update.")
                    elif not args.force:
                         # This case should ideally not be reached if proceed=False for conflicts without force
                         print(f"  Skipping conflict (remote newer): {os.path.relpath(filepath, VAULT_DIR)}")
                         # notes_skipped_conflict already counted above
                    else: # gnote missing for conflict? error.
                         print(f"  Error: Missing gnote object for conflict action on {filepath}. Skipping.")
                         notes_failed += 1


                elif action_type == 'skip_deleted':
                     print(f"  Skipping (likely deleted remotely): {os.path.relpath(filepath, VAULT_DIR)}")
                     # notes_skipped_deleted already counted


            except Exception as e:
                print(f"Error applying action '{action_type}' for file {filepath}: {e}")
                traceback.print_exc()
                notes_failed += 1
        # --- Execute Changes --- END

        # --- Final Sync --- START
        if sync_needed: # Removed 'and not args.dry_run' check as it's inside the 'if proceed and not args.dry_run' block
            print("-" * 30)
            print("Performing final sync with Google Keep...")
            try:
                keep.sync()
                save_cached_state(keep) # Save state after successful sync
                print("Final sync complete.")
            except gkeepapi.exception.SyncException as e:
                print(f"Error during final sync: {e}")
                notes_failed += 1 # Count sync failure as a failure
            except Exception as e:
                print(f"An unexpected error occurred during final sync: {e}")
                traceback.print_exc()
                notes_failed += 1 # Count sync failure as a failure
        elif not notes_failed: # Only print if no changes were needed *and* no errors occurred during apply phase
             print("No changes needed final sync.")

    # --- Final Sync --- END (Moved outside the 'if proceed' block)

    # --- Summary --- START
    print("--- Push Summary ---")
    print(f"Local Markdown files found: {len(local_files_to_process)}")
    # print(f"Files processed: {notes_processed}") # This counter is less relevant now
    print(f"Notes created in Keep: {notes_pushed_create}")
    print(f"Notes updated in Keep: {notes_pushed_update}")
    print(f"Skipped (Conflict/Remote Newer): {notes_skipped_conflict}") # Updated counting logic
    print(f"Skipped (Deleted Remotely?): {notes_skipped_deleted}") # Updated counting logic
    print(f"Failed during push/sync: {notes_failed}")
    if args.dry_run:
        print("[Dry Run Mode] No changes were made to Google Keep.")
    elif not proceed and total_changes > 0 and not args.force:
         print("Push aborted by user. No changes were made.")
    elif not sync_needed and not notes_failed and proceed:
         print("No actual changes were pushed to Google Keep (content might have matched).")

    print("Push script finished.")
    # --- Summary --- END


if __name__ == "__main__":
    main() 