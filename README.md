# Google Keep <=> Obsidian Synchronization Scripts

## Goal

This project provides a Python script (`sync.py`) to facilitate a two-way synchronization between Google Keep notes and a local Obsidian vault. It aims to bridge the gap between the quick capture capabilities of Google Keep and the powerful linking and organization features of Obsidian.

Notes are converted to Markdown files with YAML frontmatter preserving key metadata.

## Features

*   **Two-Way Synchronization (`sync.py`):**
    *   **Pull from Keep (first phase of sync):**
        *   Downloads notes (including text, lists, titles) from Google Keep.
        *   Downloads media attachments (images, audio, etc.) associated with notes.
        *   Converts notes into Markdown files (`.md`).
        *   Stores Keep metadata (ID, created/updated timestamps, color, pinned status, archived status, trashed status, labels) in YAML frontmatter.
        *   **All notes get `archived`, `trashed`, and `pinned` fields** in frontmatter for consistency.
        *   Formats lists with Markdown checkboxes (`- [ ]` or `- [x]`).
        *   Places notes in the appropriate local folder (`KeepVault/`, `KeepVault/Archived/`, `KeepVault/Trashed/`) based on their status in Keep.
        *   Moves local files between these folders if their status changes in Keep.
        *   Creates Obsidian-friendly attachment links (`![[Attachments/file.png]]`).
        *   Handles basic filename sanitization (removes invalid characters, keeps spaces).
        *   Uses Keep's `updated` timestamp to only update local files if the remote note is newer (can be overridden with `--force-pull-overwrite`).
        *   Deletes local files ("orphans") corresponding to notes deleted in Keep.

    *   **Push to Keep (second phase of sync):**
        *   Scans local Markdown files in the vault structure (`KeepVault/`, `KeepVault/Archived/`, `KeepVault/Trashed/`).
        *   Parses YAML frontmatter and Markdown content.
        *   Compares local note data with the corresponding Google Keep note.
        *   **Title Handling Logic:**
            *   For notes with empty YAML title: uses filename as title, **UNLESS** filename follows "Untitled_[ID]" pattern (keeps title empty for cleaner remote display).
            *   H1 headers are **always preserved in content** (no longer extracted as title).
        *   **Conflict Handling & Update Detection:**
            *   Offers `--cherry-pick` mode to interactively decide between local and remote versions for conflicting notes.
            *   If not cherry-picking, prioritizes timestamps and material content/metadata differences to decide whether to push.
            *   `--force-push` overrides certain checks to force pushing local changes.
        *   Updates existing Keep notes with changes to title, text content, color, pinned status, archived status, trashed status, and labels.
        *   Creates *new* Keep notes for local Markdown files that don't have a Keep ID in their frontmatter.
        *   **Immediately adds `archived`, `trashed`, and `pinned` fields** to newly created local files after sync.
        *   Updates the local file\'s frontmatter with the new Keep ID and timestamps after creating a note in Keep.
    *   **Automatic Sync Log Feature:**
        *   Creates and maintains a dedicated sync log note (`_Sync_Log.md`) in both Keep and local vault.
        *   Contains summary of each sync operation (files created, updated, errors, timestamps).
        *   Pinned in Keep for easy access and automatically updated after each sync.
*   **Authentication:**
    *   Supports Google Master Token (recommended, obtained via an OAuth flow) and App Passwords.
    *   Uses the system keyring (`keyring` library) to securely store/retrieve the Master Token if available.
    *   Uses a `.env` file for storing email and optionally the App Password or Master Token.
*   **Caching:**
    *   Uses a cache file (`keep_state.json`) for potentially faster subsequent syncs by resuming the Keep session.

## Setup

1.  **Prerequisites:**
    *   Python 3.x installed.
    *   `pip` (Python package installer).

2.  **Install Dependencies:**
    *   Create a `requirements.txt` file (if one doesn't exist) with the following content:
        ```
        gkeepapi>=0.14.3
        keyring
        gpsoauth
        python-dotenv
        PyYAML
        requests
        matplotlib
        numpy
        # Optional: python-magic (for better attachment type detection)
        ```
    *   Run: `pip install -r requirements.txt`

3.  **Configuration (`.env` file):**
    *   Create a file named `.env` in the same directory as the scripts.
    *   Add your Google account email:
        ```dotenv
        GOOGLE_KEEP_EMAIL="your_email@gmail.com"
        ```
    *   **(Optional but Recommended)** Add authentication credentials (use *one* of the following):
        *   `GOOGLE_KEEP_MASTER_TOKEN="your_master_token"` (See Authentication section below)
        *   `GOOGLE_KEEP_APP_PASSWORD="your_16_digit_app_password"` (See Google Account settings for App Passwords)

4.  **Authentication:**
    *   **Master Token (Recommended):**
        *   If `GOOGLE_KEEP_MASTER_TOKEN` is *not* in your `.env` file, the scripts will attempt to retrieve it from your system keyring.
        *   If not found in keyring, the script will guide you through an OAuth flow: You'll visit a Google URL, authorize access, and paste back a temporary OAuth token (`oauth2rt_...`). The script uses `gpsoauth` to exchange this for a long-lived Master Token.
        *   The script will attempt to save the obtained Master Token to your system keyring for future use. You can also manually add it to the `.env` file.
        *   **Security:** Master Tokens grant broad access. Keep yours secure. Use keyring if possible.
    *   **App Password (Alternative):**
        *   Generate a 16-digit App Password in your Google Account security settings (requires 2-Step Verification).
        *   Add it to your `.env` file as `GOOGLE_KEEP_APP_PASSWORD`.
        *   If not in `.env`, the script will prompt you to enter it securely. It can save it to `.env` if you enter it at the prompt.

## Usage

Run the scripts from your terminal in the project directory.

### Default shell and command execution rules

This repository assumes Linux with Bash as the default shell for examples and automation.

- Default shell: `bash` (Linux). If you use another shell, adapt commands accordingly.
- All commands should be wrapped with a timeout and end by printing the exit code separator.

Example on Linux (bash):
```bash
timeout 59s <your_command>; echo "--- Execution Finished --- Exit Code: $? ---"
```

If a command times out, it should return exit code `124`. When detected, display:
```
[timeout] Aborted after 59s. Re-run with a higher limit if needed.
```

On macOS (zsh), install GNU Coreutils and use `gtimeout` similarly:
```bash
gtimeout 59s <your_command>; echo "--- Execution Finished --- Exit Code: $? ---"
```

On Windows PowerShell:
```powershell
timeout 59s <your_command>; echo "--- Execution Finished --- Exit Code: $LastExitCode ---"
```

### Tracking specific Obsidian configuration files

Although Obsidian vaults are typically user-specific, this project intentionally tracks a few safe configuration/data files for reproducibility:

- `KeepVault/.obsidian/bookmarks.json`
- `KeepVault/.obsidian/plugins/obsidian-shellcommands/data.json`
- `KeepVault/.obsidian/plugins/obsidian-custom-frames/data.json`

Rationale:
- These files do not contain sensitive personal information in this workflow.
- Keeping them versioned helps preserve workspace shortcuts and UI integrations that support the sync tooling.

Note: The `.gitignore` includes these paths commented out to document the default safety posture. If your use case differs, uncomment them to exclude from version control.

*   **Synchronize Notes (Pull then Push):**
    ```bash
    python sync.py [email] [options]
    ```
    *   `[email]` (Optional): Your Google email. Overrides `.env` if provided.
    *   `--full-sync`: Ignores `keep_state.json` cache for a full Keep sync (affects initial connection).
    *   `--debug`: Enables verbose logging.
    *   `--dry-run`: Simulates pull and push operations, making no actual changes.
    *   `--skip-pull`: Skips the pull operation (local -> Keep only).
    *   `--skip-push`: Skips the push operation (Keep -> local only).
    *   `--automatic-sync`: Enable automatic sync mode: no prompts for push, exit on unresolved conflicts.

    **Pull Specific Options (used if pull is not skipped):**
    *   `--skip-markdown-conversion`: PULL: Only download notes to JSON, skip local Markdown processing.
    *   `--force-pull-overwrite`: PULL: Force overwrite local files even if remote timestamp isn't newer.
    *   `--debug-json-output`: PULL: Save detailed JSON of pulled notes to `keep_notes_pulled.json`.

    **Push Specific Options (used if push is not skipped):**
    *   `--force-push`: PUSH: Force push local changes, potentially overwriting newer remote notes (unless `--cherry-pick` chooses remote).
    *   `--cherry-pick`: PUSH: For notes with differences, prompt user to choose between local and remote versions.

## Workflow

1.  **Initial Sync:** Run `python sync.py` to download all your Keep notes into `KeepVault` and then push any initial local interpretations (though likely minimal changes on first push).
2.  **Edit in Obsidian/Keep:** Edit notes in your Obsidian `KeepVault` or directly in Google Keep.
3.  **Synchronize:** Run `python sync.py` regularly. This will:
    *   Pull changes from Google Keep to your Obsidian vault.
    *   Push changes from your Obsidian vault back to Google Keep.
    *   **Automatically update the sync log** with operation summary.
4.  **Clean up Single-Use Tags:** Run `python tools/tag_cleanup/remove_single_use_tags.py` to remove tags that are only used in a single note.
5.  **Archive Connected Notes:** Run `python tools/archive_connected_notes.py` to automatically archive notes that have connections (outgoing or incoming `[[]]` links).

*Repeat steps 2-5 as needed.*

### Export entire vault to a single JSON file (excluding Trashed)

Generate a unified JSON export designed for RAG/agentic AI. The output path is fixed to `tools/vault_export.json` and is ignored by git.

```bash
timeout 59s python tools/export_vault_to_markdown.py; echo "--- Execution Finished --- Exit Code: $? ---"
```

- Optional custom vault path:

```bash
timeout 59s python tools/export_vault_to_markdown.py --vault-path /absolute/path/to/KeepVault; echo "--- Execution Finished --- Exit Code: $? ---"
```

Notes:
- Trashed notes (any file under a directory named `Trashed`) are excluded.
- Only `.md` files are included as sources.
- Each note includes normalized metadata (id, title, color, pinned, archived, trashed, created, updated, edited), content, outbound internal links, external links, and computed backlinks.

## File Structure

*   `KeepVault/`: Default directory for active Markdown notes.
*   `KeepVault/Archived/`: Local Markdown notes corresponding to archived notes in Keep.
*   `KeepVault/Trashed/`: Local Markdown notes corresponding to trashed notes in Keep.
*   `KeepVault/Attachments/`: Downloaded media files (images, audio, etc.).
*   `KeepVault/_Sync_Log.md`: **Automatic sync log note** with history of all sync operations.
*   `sync.py`: Main script for two-way synchronization.
*   `tools/tag_cleanup/remove_single_use_tags.py`: Script to clean up tags that are only used in one note.
*   `tools/archive_connected_notes.py`: Script to automatically archive notes that have connections (outgoing or incoming `[[]]` links).
*   `tools/backup_utils.py`: Utility functions for backup operations.
*   `KeepVault/.obsidian/`: Obsidian configuration files for the vault.
*   `keep_state.json`: Cache file storing state from Google Keep to speed up syncs. Can be deleted to force a full refresh (`--full-sync`).
*   `backup_state.json`: Tracks backup timing and sync count for automatic backup feature.
*   `keep_notes_pulled.json`: (Optional, if `--debug-json-output` is used) Raw JSON dump of notes downloaded during the pull phase.
*   `.env`: Stores configuration (email, optional credentials). **Add this to `.gitignore` if using version control.**
*   `README.md`: This file.
*   `requirements.txt`: Python dependencies.

## Automatic Sync Log Feature

The script automatically creates and maintains a sync log to track all synchronization operations.

**Key Features:**
*   **Automatic Creation:** A dedicated note titled "Sync Log" is created in both Google Keep and locally as `_Sync_Log.md`.
*   **Pinned for Visibility:** The sync log note is automatically pinned in Google Keep for easy access.
*   **Operation Summary:** Each sync updates the log with:
    *   Sync start and completion timestamps (in local timezone).
    *   Pull summary: files created, updated, moved, deleted, errors.
    *   Push summary: notes created, updated, conflicts, errors.
    *   Cherry-pick decisions (if `--cherry-pick` was used).
*   **Persistent History:** The log accumulates history across multiple sync operations.
*   **Dual Location:** Available both in Obsidian (for local reference) and Google Keep (for mobile access).

**Sync Log Location:**
*   **Local:** `KeepVault/_Sync_Log.md`
*   **Remote:** "Sync Log" note in Google Keep (pinned)

## Archive Connected Notes Feature

The project includes a utility script to automatically archive notes that are part of your knowledge graph (have connections to other notes).

**Key Features:**
*   **Comprehensive Link Detection:** Scans all markdown files for Obsidian-style `[[]]` links
*   **Intelligent Link Resolution:** Matches links using:
    *   Direct filename matching (`[[filename]]` → `filename.md`)
    *   YAML title matching (`[[Note Title]]` → file with `title: "Note Title"`)
    *   Case-insensitive matching for better compatibility
*   **Bidirectional Connection Tracking:** Identifies notes with both outgoing links (notes that link to others) and incoming links (notes that are referenced by others)
*   **Active Note Focus:** Only processes notes that are not already archived or trashed
*   **Safe Operation:** Shows preview of what will be changed and asks for confirmation

**Usage:**
```bash
python tools/archive_connected_notes.py
```

**How it Works:**
1. **Discovery Phase:** Scans all `.md` files in the vault (including `Archived/` and `Trashed/` folders)
2. **Link Resolution:** Builds a complete map of all `[[]]` links and their targets
3. **Connection Analysis:** Identifies which notes have connections (either as source or target of links)
4. **Archive Candidates:** Filters to show only active notes that would be archived
5. **Preview & Confirmation:** Shows exactly which notes will be affected before making changes
6. **Safe Execution:** Updates only the `archived: true` field in YAML frontmatter

**Example Output:**
```
Found 875 total notes in the vault
Found 478 notes with connections (outgoing or incoming links)
Found 37 ACTIVE notes that need to be archived
```

This helps maintain a clean active workspace by automatically archiving notes that are part of your connected knowledge while preserving standalone notes for easy access.

## Title and H1 Handling Logic

The script has sophisticated logic for handling note titles and H1 headers:

### Title Priority (Push Operation)
1. **YAML `title` field** (highest priority)
2. **Filename** (if YAML title is empty)
3. **Special case:** Notes with filenames matching "Untitled_[ID]" pattern keep empty title for cleaner remote display

### H1 Header Behavior
*   **H1 headers are ALWAYS preserved in content** (changed from previous behavior)
*   **No longer extracted as title** - H1 stays in the markdown body
*   This ensures Obsidian display consistency while maintaining content integrity

### Examples
```markdown
# Scenario 1: YAML title present
---
title: "My Important Note"
---
# This H1 stays in content
Content here...

# Scenario 2: Empty YAML title, normal filename
---
title: ""
---
# This H1 stays in content
Content here...
# Result: Title becomes filename, H1 preserved

# Scenario 3: Untitled with ID pattern
---
title: ""
---
# This H1 stays in content
Content here...
# File: Untitled_19734db46ba.3e207d2c9b0da0e7.md
# Result: Title stays empty, H1 preserved
```

## Backup Feature

The script now includes an automatic backup feature for the `KeepVault/` directory to provide a safety net against accidental data loss or synchronization issues.

**How Backups are Triggered:**

Backups are created automatically based on the following conditions, whichever comes first:
*   **Time-based:** A backup is made if 7 days have passed since the last backup.
*   **Count-based:** A backup is made if 10 sync operations have been performed since the last backup.

**Backup Storage and Format:**

*   **Location:** Backups are stored in a new folder named `backups/` at the root of the repository.
*   **Format:** Each backup is a timestamped `.tar.gz` archive of the entire `KeepVault/` directory (e.g., `backup_YYYYMMDD_HHMMSS.tar.gz`).

**Rolling Window and Retention:**

*   A maximum of 5 backups are kept.
*   When a new backup is created and this limit is exceeded, the oldest backup archive is automatically deleted.

**Configuration:**

*   The core backup settings (backup interval, sync count trigger, maximum number of backups to keep) are currently defined as constants at the beginning of the `sync.py` script. Advanced users can modify these constants directly in the script if needed.

**State Tracking:**

*   The script uses a `backup_state.json` file (stored at the root of the repository) to keep track of the timestamp of the last successful backup and the number of sync operations performed since then.

**Important Note for Git Users:**

*   The `backups/` directory and the `backup_state.json` file are automatically included in the `.gitignore` file. This is intentional to prevent committing large backup archives and local state information to your Git repository.

## Synchronization Logic Details

The synchronization process is divided into two main phases: Pull (Keep -> Local) and Push (Local -> Keep).

### Pull Phase (Keep -> Local)

1.  **Fetch from Keep:** The script fetches all notes from the authenticated Google Keep account using the `gkeepapi` library.
2.  **Local Indexing:** It builds an index of existing local Markdown files in the `KeepVault` directory structure, primarily using the `id` in the YAML frontmatter to identify corresponding Keep notes. The `updated_dt` timestamp is parsed from the YAML or derived from the file modification time (using the later of the two) and stored in the index.
3.  **Note Processing and Comparison:** The script iterates through each note fetched from Keep.
    *   **Media Download:** For notes with attachments (images, drawings, audio), it downloads the media files to the `KeepVault/Attachments/` directory. Attachment links in the Markdown are created using the attachment's ID and file extension.
    *   **Markdown Conversion:** The Keep note's content and relevant metadata (title, color, pinned, archived, trashed, labels, timestamps, list items) are converted into a Markdown string with YAML frontmatter.
    *   **Update Check:** It compares the `updated` timestamp of the Keep note (ensured to be UTC) with the `local_updated_dt` derived from the local file.
        *   If the Keep note's timestamp is newer than the local timestamp, or if the `--force-pull-overwrite` flag is used, the local Markdown file is updated or created.
        *   If timestamps are equal or unreliable, a content hash comparison is performed as a fallback to detect if the file content differs, triggering an update if they don't match.
        *   If the local timestamp is newer or equal (and content matches if timestamps were unreliable), the local file is skipped for content update.
    *   **File Placement:** The local file is placed or moved into the `KeepVault/`, `KeepVault/Archived/`, or `KeepVault/Trashed/` subdirectory based on the note's current archived or trashed status in Keep.
4.  **Orphan Cleanup:** After processing all notes from Keep, the script identifies any local Markdown files (by ID in the index) that no longer have a corresponding note in Keep. These "orphaned" local files are deleted, assuming the note was permanently deleted in Keep.
5.  **Orphaned Attachment Cleanup:** Any files in the `KeepVault/Attachments/` directory that were not referenced by any of the pulled notes during the current sync are considered orphaned and are deleted.

### Push Phase (Local -> Keep)

1.  **Local Indexing:** The script builds an index of all Markdown files in the `KeepVault` directory structure, parsing their YAML frontmatter and content. The `local_updated_dt` for each file is determined by taking the **later** of the timestamp found in the YAML `updated` field (if valid) and the file's system modification time (`os.path.getmtime`). Both timestamps are converted to UTC for consistent comparison.
2.  **Remote Notes Index:** It uses the `gkeepapi` object (which holds the state from the initial sync/pull) to create a quick index of remote notes by ID.
3.  **Change Detection:** The script iterates through each local Markdown file in its index.
    *   For each local file with an `id` in its frontmatter, it finds the corresponding remote note in the Keep index.
    *   It calls `check_changes_needed_for_push` to compare the local data (content, title, color, pinned, archived, trashed, labels) with the remote note's data. This function returns whether differences exist (`is_different`) and a list of reasons (`diff_reasons`). `timestamp_local_newer` is included in `diff_reasons` if the `local_updated_dt` is strictly greater than the `remote_updated_dt`.
    *   It determines if "material changes" exist by checking if any reason in `diff_reasons` is present *other than* just `timestamp_local_newer`.
4.  **Action Determination (Push Logic):** Based on whether material changes are detected, the timestamps, and the command-line arguments (`--automatic-sync`, `--force-push`, `--cherry-pick`), the script decides the action for each note:
    *   **Skip (No Changes):** If `is_different` is False (no differences found by `check_changes_needed_for_push`), the note is skipped.
    *   **Skip (No Material Changes):** If `is_different` is True but `material_changes_detected` is False (meaning the only difference is `timestamp_local_newer`), the note is skipped. This prevents pushing solely based on a file system touch.
    *   **Skip (Remote Deleted):** If a local file has an ID but no corresponding note is found in Keep, it assumes the remote note was deleted and skips pushing the local file.
    *   **Skip (Potential Duplicate):** If a local file has no ID but a remote note with a very similar title exists, it skips creating a new note in Keep to avoid duplicates and warns the user.
    *   **Create New Remote:** If a local file has no ID and no potential duplicate remote note is found, it is marked for creation as a new note in Keep.
    *   **Update Remote:** If material changes are detected for a local file with a corresponding remote note, the action depends on the sync mode:
        *   **Automatic Sync (`--automatic-sync`):**
            *   If `--force-push` is used, the local changes are marked for push.
            *   Otherwise, it checks if `local_updated_dt` is valid and is strictly newer than `remote_updated_dt` (or if `remote_updated_dt` is None). If this condition is met, local changes are marked for push.
            *   If the condition is *not* met (remote is newer, timestamps are equal with material diffs, or local timestamp is invalid/missing with material diffs), it logs an "Unresolved conflict" and **exits the script**, requiring manual intervention or different flags.
        *   **Cherry-pick (`--cherry-pick`):** The user is interactively prompted to choose between the local and remote versions. If the user chooses local, the note is marked for remote update. If the user chooses remote, the local file is updated from Keep, and no remote push is marked for this note in this run.
        *   **Default/Interactive:** If `--force-push` is used, local changes are marked for push. Otherwise, it checks if `local_updated_dt` is valid and is newer than or equal to `remote_updated_dt` (or if `remote_updated_dt` is None). If this condition is met, local changes are marked for push. If `remote_updated_dt` is clearly newer than `local_updated_dt`, the push is skipped, and a conflict warning is logged.
5.  **Execute Actions:** The script performs the determined actions:
    *   New notes marked for creation are created in Google Keep using the data from the local file.
    *   Existing remote notes marked for update are modified based on the local file's data (title, content, status, labels, color).
6.  **Final Sync:** After all creation and update actions are staged on the `gkeepapi` object, a final `keep.sync()` is called to commit all changes to Google Keep in a batch. The cached state is saved.
7.  **Update Local IDs (for new notes):** For local files that resulted in new notes being created in Keep, their YAML frontmatter is updated with the new `id` assigned by Keep and the latest timestamps.

### Trash and Delete Behavior

**In Google Keep -> Local:**
*   **Trashing a note in Keep:** On the next pull, the corresponding local file is moved into `KeepVault/Trashed/`. Its content and metadata are updated to match the remote (including when the remote note is empty). The file is not deleted locally.
*   **Permanently deleting a note in Keep:** On the next pull, the corresponding local file is removed as an orphan.

**Local -> Google Keep:**
*   **Trashing from local:** Move the local Markdown file into the `KeepVault/Trashed/` directory. The next push will trash the corresponding note in Google Keep. Subsequent pulls keep the file in `KeepVault/Trashed/`.
*   **Deleting a local file:** If you delete a local `.md` file directly, also delete the corresponding note in Google Keep. The sync does not automatically delete remote notes for locally deleted files.

## Potential Flaws and Limitations (Code Audit Findings)

Based on the current implementation, here are some potential areas for issues or limitations:

*   **Simultaneous Edits leading to Data Loss:** The current timestamp-based conflict resolution (especially without `--cherry-pick`) follows a "last write wins" approach based on the determined `updated_dt`. If the same note is significantly edited in both Google Keep and Obsidian between syncs, the changes from one location might completely overwrite the changes from the other, resulting in data loss for the overwritten version. There is no true three-way merge capability.
*   **Timestamp Precision and Synchronization Issues:** Differences in timestamp precision between the file system, Python's `datetime`, and Google Keep's API could potentially lead to edge cases in comparisons (`>`, `>=`). While using UTC helps, very rapid edits in both locations around the same time might still result in unexpected conflict resolutions or notes being deemed "the same" when they have subtle differences.
*   **Reliance on File Modification Time Heuristic:** While using the file modification time helps when YAML timestamps are not updated (e.g., by Obsidian), it is still a heuristic. Other processes or file operations (like copying or restoring a file without editing its content) could potentially update the modification time and, coupled with a detected material difference (even an old one), trigger an unintended push. The `material_changes_detected` check mitigates this significantly but relies on `check_changes_needed_for_push` accurately identifying all non-timestamp differences.
*   **YAML Parsing Robustness:** While `yaml.safe_load` is used, a severely malformed YAML frontmatter (beyond just an unparsable timestamp) could cause parsing to fail, potentially leading the script to skip the file or process it incorrectly (e.g., treating an existing note as a new one if the ID isn't parsed). The current error handling logs the issue but might not prevent subsequent unexpected behavior for that file.
*   **List Item ID Handling on Push:** When updating a list note based on local Markdown, the script currently clears existing items in the remote Keep note and re-adds them from the parsed local Markdown list. This process likely assigns *new* IDs to the list items in Keep. If Google Keep's internal logic or other applications rely on stable list item IDs, this could potentially cause issues. A more advanced implementation would attempt to match local list items to existing remote items to preserve IDs where possible.
*   **Attachment Links in Markdown:** The script generates Obsidian-style `![[Attachment/filename.ext]]` links. If these links are manually edited in the Markdown file in a way that breaks the expected format (`![[Attachments/ID.ext]]`), the script might not be able to correctly identify the linked attachment during subsequent processing (though the pull phase will likely correct the link format on the next sync).
*   **Handling of Empty Notes:** The script has logic to skip pulling empty notes from Keep. However, a note that becomes empty locally (e.g., by deleting all content and attachments in Obsidian) but still has an ID will be compared. If it's deemed "different" due to becoming empty, the current push logic might attempt to update the remote note to be empty. This might be the desired behavior, but it's a point to be aware of.
*   **Error Handling Granularity:** While there's general error handling, specific edge cases within the API interaction or file operations might not have granular handling, potentially leading to a script exit on unexpected errors. Debug logging helps diagnose these.
*   **Timezone Handling Edge Cases:** Although efforts have been made to handle timezones and compare in UTC, complex daylight saving time transitions or inconsistencies in how different systems record/interpret timestamps could theoretically lead to minor discrepancies affecting the comparison logic.

Understanding these potential issues can help users avoid problematic workflows (like simultaneous edits) and assist in debugging if unexpected sync behavior occurs.

## Troubleshooting

*   **Authentication Errors:** Double-check your email in `.env`, ensure your Master Token or App Password is correct and hasn't expired or been revoked. Try the interactive OAuth flow if using Master Token. Check for keyring backend issues (may require installing `dbus-python` or similar depending on OS/environment).
*   **Sync Errors (`SyncException`):** Could be temporary network issues, Google API changes, or rate limiting. Try again later. Try `--full-sync`. Check the `gkeepapi` library's issue tracker.
*   **Color Warnings (`Invalid local color string`):** Ensure colors in your YAML frontmatter match the `gkeepapi` enum names (e.g., `BLUE`, `GREEN`, `RED`, `YELLOW`, `GRAY`, `BROWN`, `ORANGE`, `PURPLE`, `PINK`, `TEAL`, `WHITE`). The scripts now handle `WHITE` correctly during push.
*   **Unexpected File Updates/Pushes:** Usually due to subtle differences in content (whitespace, line endings) or timestamp mismatches. Ensure your editor isn't introducing hidden characters or inconsistent line endings. Use the `--debug` flag to see the timestamps and diff reasons being compared.
*   **Unexpected File Deletions:** The orphan deletion in the pull phase of `sync.py` removes local files whose IDs aren't found in Keep. Ensure notes weren't accidentally deleted in Keep. You can recover deleted local files from your system's trash if needed.
*   **Filename Issues:** Ensure note titles don't rely solely on characters forbidden in filenames (`\/:*?"<>|`).
*   **Automatic Sync Conflicts:** If automatic sync exits with an "Unresolved conflict," it means material changes were detected, but the timestamp comparison didn't clearly favor the local version. Use `--debug` to see the timestamps. Resolve manually, or use `--force-push` to override.
*   **Notes Not Pushing in Automatic Mode when File Mod Time is Newer:** Verify that the file modification time is genuinely newer than the remote timestamp using file system tools. Check debug logs to confirm the `local_updated_dt` being used includes the newer file time and that the comparison (`>`) is correctly evaluating. Ensure `material_changes_detected` is True for that note.

### New Feature Troubleshooting

*   **Sync Log Issues:** 
    *   If `_Sync_Log.md` is missing locally, it will be recreated on next sync.
    *   If sync log note is accidentally deleted in Keep, a new one will be created.
    *   Sync log errors are logged but don't stop the main sync operation.
*   **Title/H1 Issues:**
    *   **H1 not preserved:** Check if file was processed by old script version - H1s are now always kept in content.
    *   **Untitled notes getting filename as title:** Ensure filename follows exact pattern `Untitled_[ID].[ID].md` to keep title empty.
    *   **Missing `archived`/`trashed`/`pinned` fields:** Run sync once to add these fields to all notes automatically.
*   **Obsidian Configuration:** The vault includes `.obsidian/` folder with settings, plugins, and themes directly in this repository.


## Contributing (Placeholder)

Contributions are welcome! Please feel free to submit issues or pull requests.

## License (Placeholder)

This project is likely under the MIT License (or choose another appropriate open-source license). 