import os
import tarfile
from datetime import datetime
import logging
from typing import Optional
import glob

logger = logging.getLogger(__name__)

def create_backup(source_dir: str, backup_dir: str) -> Optional[str]:
    """
    Creates a timestamped .tar.gz archive of the source_dir.

    Args:
        source_dir: Path to the source directory.
        backup_dir: Path to the backup directory.

    Returns:
        Full path to the created backup file if successful, otherwise None.
    """
    if not os.path.isdir(source_dir):
        logger.error(f"Source directory {source_dir} not found.")
        return None

    if not os.path.isdir(backup_dir):
        try:
            os.makedirs(backup_dir)
            logger.info(f"Created backup directory {backup_dir}")
        except OSError as e:
            logger.error(f"Error creating backup directory {backup_dir}: {e}")
            return None

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"backup_{timestamp}.tar.gz"
    backup_filepath = os.path.join(backup_dir, backup_filename)

    logger.info(f"Creating backup of {source_dir} to {backup_filepath}")
    try:
        with tarfile.open(backup_filepath, "w:gz") as tar:
            tar.add(source_dir, arcname=os.path.basename(source_dir))
        logger.info(f"Backup created: {backup_filepath}")
        return backup_filepath
    except FileNotFoundError:
        logger.error(f"Source directory {source_dir} not found during tar creation.")
        return None
    except PermissionError:
        logger.error(f"Permission denied while creating backup {backup_filepath}.")
        return None
    except Exception as e:
        logger.error(f"Error creating backup: {e}")
        if os.path.exists(backup_filepath):
            os.remove(backup_filepath) # Clean up partially created backup
        return None

def manage_backups(backup_dir: str, max_backups: int = 5):
    """
    Manages backups in the backup_dir, keeping only max_backups.

    Args:
        backup_dir: Path to the backup directory.
        max_backups: Maximum number of backups to keep.
    """
    if not os.path.isdir(backup_dir):
        logger.warning(f"Backup directory {backup_dir} not found. Nothing to manage.")
        return

    logger.info(f"Managing backups in {backup_dir}. Max backups to keep: {max_backups}")
    
    backup_files = glob.glob(os.path.join(backup_dir, "backup_*.tar.gz"))

    if not backup_files:
        logger.info("No backup files found.")
        return

    # Parse timestamps and sort backups
    # Expected format: backup_YYYYMMDD_HHMMSS.tar.gz
    parsed_backups = []
    for f_path in backup_files:
        filename = os.path.basename(f_path)
        parts = filename.split('_') # ['backup', 'YYYYMMDD', 'HHMMSS.tar.gz']
        if len(parts) == 3 and parts[0] == 'backup':
            timestamp_str = parts[1] + "_" + parts[2].split('.')[0] # YYYYMMDD_HHMMSS
            try:
                dt_obj = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                parsed_backups.append((dt_obj, f_path))
            except ValueError:
                logger.warning(f"Could not parse timestamp from filename: {filename}")
        else:
            logger.warning(f"Unexpected filename format, skipping: {filename}")
            
    # Sort by timestamp (oldest first)
    parsed_backups.sort(key=lambda x: x[0])

    num_backups_to_delete = len(parsed_backups) - max_backups
    if num_backups_to_delete > 0:
        logger.info(f"Found {len(parsed_backups)} backups. Deleting {num_backups_to_delete} oldest backups.")
        for i in range(num_backups_to_delete):
            backup_to_delete_path = parsed_backups[i][1]
            try:
                os.remove(backup_to_delete_path)
                logger.info(f"Deleted old backup: {backup_to_delete_path}")
            except OSError as e:
                logger.error(f"Error deleting backup {backup_to_delete_path}: {e}")
    else:
        logger.info(f"Found {len(parsed_backups)} backups. No old backups to delete.")
