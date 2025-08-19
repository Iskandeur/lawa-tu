# Obsidian Config Sync Setup Guide

This guide helps you set up the optional Obsidian configuration synchronization feature.

## Quick Setup

### Option 1: HTTPS (Recommended for beginners)

1. Create a GitHub repository for your Obsidian configs
2. Set your `config.json`:
   ```json
   {
     "sync_obsidian_config": true,
     "obsidian_git_repo": "https://github.com/yourusername/your-obsidian-config-repo.git"
   }
   ```
3. Run sync - it will automatically use HTTPS authentication

### Option 2: SSH (For advanced users)

1. Set up SSH keys with GitHub:
   ```bash
   ssh-keygen -t ed25519 -C "your_email@example.com"
   # Add the public key to your GitHub account
   ssh -T git@github.com  # Test connection
   ```
2. Set your `config.json`:
   ```json
   {
     "sync_obsidian_config": true,
     "obsidian_git_repo": "git@github.com:yourusername/your-obsidian-config-repo.git"
   }
   ```

### Option 3: Disable (Default)

```json
{
  "sync_obsidian_config": false
}
```

## How It Works

- Syncs your `.obsidian` folder (themes, plugins, settings) to a Git repository
- Creates timestamped snapshots in `obsidian-config/` directory
- Automatically tries HTTPS fallback if SSH fails
- Gracefully handles authentication failures without breaking main sync

## Troubleshooting

### "Permission denied (publickey)" Error

This happens with SSH URLs when keys aren't set up. The script will:
1. Try SSH first
2. Automatically fallback to HTTPS
3. Update config.json with working URL
4. Show helpful setup instructions

### Repository Not Found

- Check the repository exists and is accessible
- Verify the URL is correct
- Make sure you have read/write permissions

### Want to Disable?

Set `"sync_obsidian_config": false` in `config.json`

## What Gets Synced

✅ **Included:**
- Plugin configurations
- Theme files
- Hotkeys and shortcuts
- Appearance settings
- Core plugin settings

❌ **Excluded:**
- Workspace layouts (`workspace.json`)
- App state (`app.json`)  
- Graph view state
- Other volatile files

## File Structure

After setup, you'll see:
- `lipu-lawa-tu/` - Local Git repository
- `lipu-lawa-tu/obsidian-config/` - Snapshots directory
- `lipu-lawa-tu/obsidian-config/LATEST` - Points to current version
- `lipu-lawa-tu/obsidian-config/{version}/` - Individual snapshots
