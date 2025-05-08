# Google Keep <=> Obsidian Synchronization Scripts

## Goal

This project provides a set of Python scripts (`pull.py` and `push.py`) to facilitate a two-way synchronization between Google Keep notes and a local Obsidian vault. It aims to bridge the gap between the quick capture capabilities of Google Keep and the powerful linking and organization features of Obsidian.

Notes are converted to Markdown files with YAML frontmatter preserving key metadata.

## Features

*   **Pull from Keep:**
    *   Downloads notes (including text, lists, titles) from Google Keep.
    *   Downloads media attachments (images, audio, etc.) associated with notes.
    *   Converts notes into Markdown files (`.md`).
    *   Stores Keep metadata (ID, created/updated timestamps, color, pinned status, archived status, trashed status, labels) in YAML frontmatter.
    *   Formats lists with Markdown checkboxes (`- [ ]` or `- [x]`).
    *   Places notes in the appropriate local folder (`KeepVault/`, `KeepVault/Archived/`, `KeepVault/Trashed/`) based on their status in Keep.
    *   Moves local files between these folders if their status changes in Keep.
    *   Creates Obsidian-friendly attachment links (`![[Attachments/file.png]]`).
    *   Handles basic filename sanitization (removes invalid characters, keeps spaces).
    *   Uses Keep's `updated` timestamp to only update local files if the remote note is newer.
    *   Deletes local files ("orphans") corresponding to notes deleted in Keep.
    *   Uses a cache file (`keep_state.json`) for potentially faster subsequent syncs.
*   **Push to Keep:**
    *   Scans local Markdown files in the vault structure (`KeepVault/`, `KeepVault/Archived/`, `KeepVault/Trashed/`).
    *   Parses YAML frontmatter and Markdown content.
    *   Compares local note data with the corresponding Google Keep note.
    *   **Update Detection:**
        *   Prioritizes timestamps: If the local file's `updated` timestamp is newer than Keep's, it proceeds to update.
        *   If timestamps are equal or unreliable (missing), it compares the *actual content* (after cleaning Obsidian-specific formatting like `# H1` and `## Attachments`) to detect changes.
        *   If Keep's timestamp is definitively newer, the push for that note is skipped to avoid overwriting remote changes.
    *   Updates existing Keep notes with changes to title, text content, color, pinned status, archived status, trashed status, and labels.
    *   Creates *new* Keep notes for local Markdown files that don't have a Keep ID in their frontmatter.
        *   Uses the filename (without extension) as the default title if no `title:` is specified in the frontmatter.
    *   Updates the local file's frontmatter with the new Keep ID and timestamps after creating a note.
    *   Handles moving notes between archived/trashed states by updating the note's status in Keep based on the local file's folder location (though pull is the primary driver for folder location).
*   **Authentication:**
    *   Supports Google Master Token (recommended, obtained via an OAuth flow) and App Passwords.
    *   Uses the system keyring (`keyring` library) to securely store/retrieve the Master Token if available.
    *   Uses a `.env` file for storing email and optionally the App Password or Master Token.

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
        *   If not found in keyring, the script will guide you through an OAuth flow: You'll visit a Google URL, authorize access, and paste back a temporary OAuth token (`oauth2rt_...`). The script uses `gpsoauth` to exchange this for a long-lived Master Token.
        *   The script will attempt to save the obtained Master Token to your system keyring for future use. You can also manually add it to the `.env` file.
        *   **Security:** Master Tokens grant broad access. Keep yours secure. Use keyring if possible.
    *   **App Password (Alternative):**
        *   Generate a 16-digit App Password in your Google Account security settings (requires 2-Step Verification).
        *   Add it to your `.env` file as `GOOGLE_KEEP_APP_PASSWORD`.
        *   If not in `.env`, the script will prompt you to enter it securely. It can save it to `.env` if you enter it at the prompt.

## Usage

Run the scripts from your terminal in the project directory.

*   **Pull Notes from Google Keep:**
    ```bash
    python pull.py [email] [--full-sync] [--debug]
    ```
    *   `[email]` (Optional): Your Google email. Overrides `.env` if provided.
    *   `--full-sync`: Ignores the `keep_state.json` cache and performs a fresh download from Keep. Useful if the cache seems corrupt.
    *   `--debug`: Enables verbose logging from the `gkeepapi` library.

*   **Push Local Changes to Google Keep:**
    ```bash
    python push.py [email] [--full-sync] [--dry-run] [--debug]
    ```
    *   `[email]` (Optional): Your Google email. Overrides `.env` if provided.
    *   `--full-sync`: Performs a full Keep sync before comparing notes (less reliant on the potentially stale cache).
    *   `--dry-run`: Scans local files and compares with Keep, reporting what *would* happen, but makes no actual changes to Keep or local files.
    *   `--debug`: Enables verbose logging from the `gkeepapi` library.

## Workflow

1.  **Initial Sync:** Run `python pull.py` to download all your Keep notes into the `KeepVault`.
2.  **Edit in Obsidian:** Open the `KeepVault` directory as an Obsidian vault. Edit notes, create new notes (as `.md` files).
3.  **Push Changes:** Run `python push.py` to upload your local changes (updates, new notes) back to Google Keep.
4.  **Pull Remote Changes:** Run `python pull.py` regularly to fetch any changes made directly in Google Keep (or on other devices) down to your Obsidian vault.
5.  **Clean up Single-Use Tags:** Run `python remove_single_use_tags.py` to remove tags that are only used in a single note.

*Repeat steps 2-5 as needed.*

## File Structure

*   `KeepVault/`: Default directory for active Markdown notes.
*   `KeepVault/Archived/`: Local Markdown notes corresponding to archived notes in Keep.
*   `KeepVault/Trashed/`: Local Markdown notes corresponding to trashed notes in Keep.
*   `KeepVault/Attachments/`: Downloaded media files (images, audio, etc.).
*   `pull.py`: Script to download notes from Keep.
*   `push.py`: Script to upload local changes to Keep.
*   `remove_single_use_tags.py`: Script to clean up tags that are only used in one note.
*   `keep_state.json`: Cache file storing state from Google Keep to speed up syncs. Can be deleted to force a full refresh (`--full-sync`).
*   `keep_notes.json`: Raw JSON dump of notes downloaded during the last `pull.py` run (for debugging/reference).
*   `.env`: Stores configuration (email, optional credentials). **Add this to `.gitignore` if using version control.**
*   `README.md`: This file.
*   `requirements.txt`: Python dependencies.

## Synchronization Logic Details

*   **Note Identification:** Notes are linked between Keep and local files using the Google Keep Note ID stored in the `id:` field of the YAML frontmatter.
*   **Pull Updates:** `pull.py` compares the `updated` timestamp from Keep with the `updated` timestamp in the local file's frontmatter. If the Keep timestamp is newer, the local file is overwritten.
*   **Push Updates:** `push.py` compares timestamps first. If the local timestamp is newer, it pushes the update. If the remote timestamp is newer, it skips the push (conflict). If timestamps are equal or missing, it compares the *cleaned* text content (excluding H1 title, Attachments section, etc.) and pushes only if the content differs.
*   **New Notes (Local -> Keep):** A local `.md` file without an `id:` in the frontmatter is treated as a new note. `push.py` creates it in Keep and writes the new ID back to the local file's frontmatter.
*   **New Notes (Keep -> Local):** `pull.py` finds notes in Keep that don't have corresponding local files (based on ID) and creates new `.md` files for them.
*   **Deleted Notes (Keep -> Local):** If `pull.py` finds local `.md` files whose IDs no longer exist in Keep, it assumes the notes were deleted in Keep and deletes the corresponding local files ("orphans").
*   **Deleted Notes (Local -> Keep):** Deleting a local `.md` file does *not* currently delete the note in Keep. The next `pull.py` run will redownload it. To delete, trash the note locally (move the file to `KeepVault/Trashed/`) and run `push.py`, or delete/trash it directly in Keep.
*   **Archived/Trashed Status:**
    *   `pull.py`: Moves local files to/from `Archived`/`Trashed` subfolders to match the status in Keep.
    *   `push.py`: Updates the note status in Keep if a local file is moved into/out of the `Archived`/`Trashed` folders (by modifying the `archived`/`trashed` attributes before syncing).

## Limitations

*   **No Attachment Upload:** The scripts **do not** upload local files added to the `Attachments` folder or linked in Markdown back to Google Keep. Attachment sync is pull-only.
*   **List Formatting:** While basic checked/unchecked list items are synced, indentation and nesting levels might be lost or flattened during the conversion.
*   **Complex Formatting:** Rich text formatting applied within Keep (beyond basic bold/italic if Keep uses Markdown internally) might be lost. Drawings are downloaded as images but cannot be edited and re-uploaded.
*   **Reminders/Collaboration:** Keep reminders and note collaborators are not synced.
*   **Real-time Sync:** This is a manual, script-based sync, not a real-time background process. You need to run the scripts explicitly.
*   **Basic Conflict Handling:** Conflicts are primarily handled by timestamp comparison ("last write wins" based on which system has the newer timestamp, or push is skipped). There's no merging of simultaneous edits. Be mindful of editing the same note in both locations without syncing frequently.
*   **Performance:** Syncing a very large number of notes or notes with many large attachments might be slow.

## Troubleshooting

*   **Authentication Errors:** Double-check your email in `.env`, ensure your Master Token or App Password is correct and hasn't expired or been revoked. Try the interactive OAuth flow if using Master Token. Check for keyring backend issues (may require installing `dbus-python` or similar depending on OS/environment).
*   **Sync Errors (`SyncException`):** Could be temporary network issues, Google API changes, or rate limiting. Try again later. Try `--full-sync`. Check the `gkeepapi` library's issue tracker.
*   **Color Warnings (`Invalid local color string`):** Ensure colors in your YAML frontmatter match the `gkeepapi` enum names (e.g., `BLUE`, `GREEN`, `RED`, `YELLOW`, `GRAY`, `BROWN`, `ORANGE`, `PURPLE`, `PINK`, `TEAL`, `WHITE`). The scripts now handle `WHITE` correctly during push.
*   **Unexpected File Updates/Pushes:** Usually due to subtle differences in content (whitespace, line endings) or timestamp mismatches. Recent updates aim to fix this, but ensure your files are clean.
*   **Unexpected File Deletions:** The orphan deletion in `pull.py` removes local files whose IDs aren't found in Keep. Ensure notes weren't accidentally deleted in Keep. You can recover deleted local files from your system's trash if needed.
*   **Filename Issues:** Ensure note titles don't rely solely on characters forbidden in filenames (`\/:*?"<>|`).

## Contributing (Placeholder)

Contributions are welcome! Please feel free to submit issues or pull requests.

## License (Placeholder)

This project is likely under the MIT License (or choose another appropriate open-source license). 