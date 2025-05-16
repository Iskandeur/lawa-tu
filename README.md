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
        *   **Conflict Handling & Update Detection:**
            *   Offers `--cherry-pick` mode to interactively decide between local and remote versions for conflicting notes.
            *   If not cherry-picking, prioritizes timestamps: If the local file's `updated` timestamp is newer than Keep\'s, it proceeds to update.
            *   If timestamps are equal or unreliable, it compares the *actual content* to detect changes.
            *   If Keep's timestamp is definitively newer (and not using `--force-push`), the push for that note is skipped.
            *   `--force-push` overrides timestamp checks and pushes local changes (unless cherry-pick chooses remote).
        *   Updates existing Keep notes with changes to title, text content, color, pinned status, archived status, trashed status, and labels.
        *   Creates *new* Keep notes for local Markdown files that don't have a Keep ID in their frontmatter.
            *   Uses the filename (without extension) as the default title if no `title:` is specified in the frontmatter, or H1 if present and YAML title is empty.
        *   Updates the local file\'s frontmatter with the new Keep ID and timestamps after creating a note in Keep.
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
        *   If not found in keyring, the script will guide you through an OAuth flow: You\'ll visit a Google URL, authorize access, and paste back a temporary OAuth token (`oauth2rt_...`). The script uses `gpsoauth` to exchange this for a long-lived Master Token.
        *   The script will attempt to save the obtained Master Token to your system keyring for future use. You can also manually add it to the `.env` file.
        *   **Security:** Master Tokens grant broad access. Keep yours secure. Use keyring if possible.
    *   **App Password (Alternative):**
        *   Generate a 16-digit App Password in your Google Account security settings (requires 2-Step Verification).
        *   Add it to your `.env` file as `GOOGLE_KEEP_APP_PASSWORD`.
        *   If not in `.env`, the script will prompt you to enter it securely. It can save it to `.env` if you enter it at the prompt.

## Usage

Run the scripts from your terminal in the project directory.

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

    **Pull Specific Options (used if pull is not skipped):**
    *   `--skip-markdown-conversion`: PULL: Only download notes to JSON, skip local Markdown processing.
    *   `--force-pull-overwrite`: PULL: Force overwrite local files even if remote timestamp isn\'t newer.
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
4.  **Clean up Single-Use Tags:** Run `python remove_single_use_tags.py` to remove tags that are only used in a single note.

*Repeat steps 2-4 as needed.*

## File Structure

*   `KeepVault/`: Default directory for active Markdown notes.
*   `KeepVault/Archived/`: Local Markdown notes corresponding to archived notes in Keep.
*   `KeepVault/Trashed/`: Local Markdown notes corresponding to trashed notes in Keep.
*   `KeepVault/Attachments/`: Downloaded media files (images, audio, etc.).
*   `sync.py`: Main script for two-way synchronization.
*   `remove_single_use_tags.py`: Script to clean up tags that are only used in one note.
*   `keep_state.json`: Cache file storing state from Google Keep to speed up syncs. Can be deleted to force a full refresh (`--full-sync`).
*   `keep_notes_pulled.json`: (Optional, if `--debug-json-output` is used) Raw JSON dump of notes downloaded during the pull phase.
*   `.env`: Stores configuration (email, optional credentials). **Add this to `.gitignore` if using version control.**
*   `README.md`: This file.
*   `requirements.txt`: Python dependencies.

## Synchronization Logic Details

*   **Note Identification:** Notes are linked between Keep and local files using the Google Keep Note ID stored in the `id:` field of the YAML frontmatter.
*   **Pull Phase (Keep -> Local):**
    *   `sync.py` (pull part) compares the `updated` timestamp from Keep with the `updated` timestamp in the local file's frontmatter. If the Keep timestamp is newer, or if `--force-pull-overwrite` is used, the local file is overwritten.
    *   If timestamps are unreliable, a content hash comparison is attempted.
    *   Finds notes in Keep that don\'t have corresponding local files (based on ID) and creates new `.md` files.
    *   If it finds local `.md` files whose IDs no longer exist in Keep, it assumes the notes were deleted in Keep and deletes the corresponding local files ("orphans").
    *   Moves local files to/from `Archived`/`Trashed` subfolders to match the status in Keep.
*   **Push Phase (Local -> Keep):**
    *   `sync.py` (push part) compares local data with Keep.
    *   If `--cherry-pick` is used, conflicts are presented to the user.
    *   Otherwise, it primarily uses timestamps: if local is newer, it pushes. If remote is newer (and no `--force-push`), it skips.
    *   If timestamps are inconclusive, content hashes and metadata differences drive the push.
    *   A local `.md` file without an `id:` in the frontmatter is treated as a new note. `sync.py` creates it in Keep and writes the new ID back to the local file's frontmatter.
    *   Updates the note status in Keep if a local file is moved into/out of the `Archived`/`Trashed` folders (by modifying the `archived`/`trashed` attributes before syncing, though pull is the primary driver for folder location based on Keep's state).
*   **Deleted Notes (Local -> Keep):** Deleting a local `.md` file currently does *not* delete the note in Keep. The next pull phase will redownload it. To delete, trash the note locally (move the file to `KeepVault/Trashed/`) and let the push phase update Keep, or delete/trash it directly in Keep for the pull phase to sync.

## Limitations

*   **No Attachment Upload:** The scripts **do not** upload local files added to the `Attachments` folder or linked in Markdown back to Google Keep. Attachment sync is pull-only.
*   **List Formatting:** While basic checked/unchecked list items are synced, indentation and nesting levels might be lost or flattened during the conversion.
*   **Complex Formatting:** Rich text formatting applied within Keep (beyond basic bold/italic if Keep uses Markdown internally) might be lost. Drawings are downloaded as images but cannot be edited and re-uploaded.
*   **Reminders/Collaboration:** Keep reminders and note collaborators are not synced.
*   **Real-time Sync:** This is a manual, script-based sync, not a real-time background process. You need to run `sync.py` explicitly.
*   **Conflict Handling:**
    *   The `--cherry-pick` option for the push phase allows manual conflict resolution.
    *   Without cherry-picking, conflicts are primarily handled by timestamp comparison during push ("last write wins" based on which system has the newer timestamp, or push is skipped if remote is newer). The pull phase generally overwrites local if remote is newer.
    *   There's no three-way merging of simultaneous edits. Be mindful of editing the same note in both locations without syncing frequently.

## Troubleshooting

*   **Authentication Errors:** Double-check your email in `.env`, ensure your Master Token or App Password is correct and hasn't expired or been revoked. Try the interactive OAuth flow if using Master Token. Check for keyring backend issues (may require installing `dbus-python` or similar depending on OS/environment).
*   **Sync Errors (`SyncException`):** Could be temporary network issues, Google API changes, or rate limiting. Try again later. Try `--full-sync`. Check the `gkeepapi` library's issue tracker.
*   **Color Warnings (`Invalid local color string`):** Ensure colors in your YAML frontmatter match the `gkeepapi` enum names (e.g., `BLUE`, `GREEN`, `RED`, `YELLOW`, `GRAY`, `BROWN`, `ORANGE`, `PURPLE`, `PINK`, `TEAL`, `WHITE`). The scripts now handle `WHITE` correctly during push.
*   **Unexpected File Updates/Pushes:** Usually due to subtle differences in content (whitespace, line endings) or timestamp mismatches. Recent updates aim to fix this, but ensure your files are clean.
*   **Unexpected File Deletions:** The orphan deletion in the pull phase of `sync.py` removes local files whose IDs aren\'t found in Keep. Ensure notes weren\'t accidentally deleted in Keep. You can recover deleted local files from your system\'s trash if needed.
*   **Filename Issues:** Ensure note titles don\'t rely solely on characters forbidden in filenames (`\\/:*?\"<>|`).

## Contributing (Placeholder)

Contributions are welcome! Please feel free to submit issues or pull requests.

## License (Placeholder)

This project is likely under the MIT License (or choose another appropriate open-source license). 