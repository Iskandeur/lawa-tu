# Changelog

All notable changes to the Google Keep <=> Obsidian sync project will be documented in this file.

## [Unreleased] - Recent Updates

### Removed
- **Automatic Remote Cleanup Feature**: Removed the automatic trashing of remote notes when they appear to be "deleted locally"
  - This feature was causing new remote notes (created on other devices) to be incorrectly moved to trash
  - The sync algorithm could not reliably distinguish between genuinely new remote notes and locally deleted notes
  - Users should now manually delete notes from Google Keep if they delete them locally and want them removed remotely

### Added
- **Automatic Sync Log Feature**: Creates and maintains `_Sync_Log.md` with detailed sync operation history
  - Tracks files created, updated, moved, deleted, and errors
  - Available in both local vault and Google Keep (pinned)
  - Updates automatically after each sync operation

- **Archive Connected Notes Script**: Enhanced `tools/archive_connected_notes.py` for knowledge graph management
  - Comprehensive detection of `[[]]` links across all vault files
  - Intelligent link resolution (filename, YAML title, case-insensitive matching)
  - Bidirectional connection tracking (outgoing and incoming links)
  - Safe operation with preview and confirmation
  - Focus on active notes only (excludes already archived/trashed)

- **Enhanced Title/H1 Handling Logic**:
  - H1 headers are now ALWAYS preserved in content (no longer extracted as title)
  - Smart filename-to-title logic with special handling for "Untitled_[ID]" pattern files
  - Consistent title handling between PULL and PUSH operations



- **Enhanced Frontmatter Consistency**:
  - All notes now get `archived`, `trashed`, and `pinned` fields automatically
  - Newly created notes immediately receive complete frontmatter after sync
  - Consistent metadata across all synchronization operations

- **Additional Dependencies**: 
  - Added `matplotlib` and `numpy` to requirements.txt
  - Enhanced backup utilities with `backup_utils.py`

### Changed
- **Title Extraction Logic**: 
  - No longer extracts H1 headers as note titles
  - Prioritizes YAML title > filename > empty (for Untitled pattern)
  - Improved handling of edge cases and special filename patterns

- **Push Operation Enhancements**:
  - Better conflict detection and resolution
  - Improved material change detection (ignores timestamp-only changes)
  - Enhanced cherry-pick functionality

- **Documentation**: 
  - Complete rewrite of README.md to reflect current functionality
  - Added detailed troubleshooting for new features
  - Corrected file paths and command examples

### Fixed
- **Push Operation Infinite Loop**: Resolved an issue where the script would hang indefinitely when updating a list-style note during a push operation. The underlying cause was an infinite loop created by repeatedly accessing a temporary copy of the note's items instead of the original list.
- **H1 Duplication Issue**: Script no longer creates duplicate H1 headers matching YAML titles
- **Frontmatter Completeness**: New notes now get all required fields immediately after creation
- **File Path Corrections**: Updated documentation to reflect actual script locations
- **Archive Connected Notes Bug**: Fixed link detection that was previously missing backlinks
  - Script now processes all files (including archived/trashed) to build complete connection graph
  - Properly resolves links using multiple matching strategies
  - Correctly identifies notes with incoming connections (backlinks)

### Technical Improvements
- Enhanced error handling and logging
- Better timezone handling for sync operations
- Improved backup state tracking
- More robust markdown parsing and generation

## Migration Notes

### For Existing Users
1. **H1 Headers**: If you have notes with duplicate H1/title combinations, use the cleanup script provided
2. **Frontmatter**: Run sync once to add missing `archived`/`trashed`/`pinned` fields to existing notes
3. **Script Paths**: Update any automation to use `tools/tag_cleanup/remove_single_use_tags.py`

### Breaking Changes
- H1 extraction behavior has changed - H1s are now preserved in content
- Some frontmatter fields are now mandatory and added automatically
- File structure has been reorganized with additional utility scripts

---

*Note: Version numbers will be added when formal releases are tagged.* 