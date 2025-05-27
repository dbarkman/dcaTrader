#!/usr/bin/env python3
"""
DCA Trading Bot - Log Rotation Script

This script handles daily rotation of logs that are not managed by Python's
TimedRotatingFileHandler. Specifically designed for:
- caretakers.log (written by multiple short-lived cron scripts)
- cron.log (managed by shell redirection)

Features:
- Daily rotation with timestamp naming
- Gzip compression of archived logs
- Configurable retention period (default: 7 days)
- Re-compression of any unzipped archives
- Atomic operations to prevent data loss
- Comprehensive error handling and logging

Usage:
    python scripts/log_rotator.py [--dry-run] [--verbose] [--config CONFIG_FILE]

Cron Example:
    0 0 * * * /path/to/venv/bin/python /path/to/project/scripts/log_rotator.py >> /path/to/project/logs/log_rotator.log 2>&1
"""

import os
import sys
import glob
import gzip
import shutil
import argparse
import datetime
import logging
from pathlib import Path
from typing import List, Optional

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

try:
    from config import get_config
    config = get_config()
    LOG_DIR = config.log_dir
except ImportError:
    # Fallback if config is not available
    LOG_DIR = Path(__file__).parent.parent / 'logs'

# Configuration
DEFAULT_FILES_TO_ROTATE = ["caretakers.log", "cron.log"]
DEFAULT_DAYS_TO_KEEP = 7
DEFAULT_LOG_DIR = LOG_DIR

# Setup basic logging for this script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('log_rotator')


class LogRotator:
    """
    Handles rotation, compression, and cleanup of log files.
    """
    
    def __init__(self, log_dir: Path, days_to_keep: int = DEFAULT_DAYS_TO_KEEP, dry_run: bool = False):
        """
        Initialize the log rotator.
        
        Args:
            log_dir: Directory containing log files
            days_to_keep: Number of days of archives to retain
            dry_run: If True, only show what would be done without making changes
        """
        self.log_dir = Path(log_dir)
        self.days_to_keep = days_to_keep
        self.dry_run = dry_run
        
        # Ensure log directory exists
        if not self.dry_run:
            self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def rotate_log_file(self, log_file_name: str) -> bool:
        """
        Rotate a single log file.
        
        Args:
            log_file_name: Name of the log file to rotate (e.g., 'caretakers.log')
            
        Returns:
            True if rotation was successful or not needed, False if failed
        """
        log_file_path = self.log_dir / log_file_name
        
        if not log_file_path.exists():
            logger.debug(f"Log file {log_file_path} does not exist, skipping rotation")
            return True
        
        if log_file_path.stat().st_size == 0:
            logger.debug(f"Log file {log_file_path} is empty, skipping rotation")
            return True
        
        # Generate archive name with timestamp
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d")
        archive_name_base = f"{log_file_name}.{timestamp}"
        
        # Ensure unique archive name if script runs multiple times a day
        counter = 1
        final_archive_name = archive_name_base
        while (self.log_dir / f"{final_archive_name}.gz").exists() or (self.log_dir / final_archive_name).exists():
            final_archive_name = f"{archive_name_base}_{counter}"
            counter += 1
        
        final_archive_path = self.log_dir / final_archive_name
        final_gzip_path = self.log_dir / f"{final_archive_name}.gz"
        
        try:
            if self.dry_run:
                logger.info(f"[DRY RUN] Would rotate {log_file_path} to {final_gzip_path}")
                return True
            
            # Move current log to archive name (atomic operation)
            shutil.move(str(log_file_path), str(final_archive_path))
            logger.info(f"Moved {log_file_path} to {final_archive_path}")
            
            # Gzip the archived log
            with open(final_archive_path, 'rb') as f_in:
                with gzip.open(final_gzip_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # Remove uncompressed archive
            final_archive_path.unlink()
            logger.info(f"Archived and gzipped {log_file_name} to {final_gzip_path}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to rotate {log_file_path}: {e}")
            # Try to restore original file if move succeeded but gzip failed
            if final_archive_path.exists() and not log_file_path.exists():
                try:
                    shutil.move(str(final_archive_path), str(log_file_path))
                    logger.info(f"Restored original file {log_file_path}")
                except Exception as restore_error:
                    logger.error(f"Failed to restore original file: {restore_error}")
            return False
    
    def cleanup_old_logs(self, log_file_base: str) -> int:
        """
        Remove old archived log files beyond the retention period.
        
        Args:
            log_file_base: Base name of the log file (e.g., 'caretakers.log')
            
        Returns:
            Number of files deleted
        """
        # Pattern to match archived logs: logfile.YYYY-MM-DD[_N].gz
        pattern = f"{log_file_base}.????-??-??*.gz"
        archived_logs = list(self.log_dir.glob(pattern))
        
        if not archived_logs:
            logger.debug(f"No archived logs found for {log_file_base}")
            return 0
        
        # Sort by modification time (newest first)
        archived_logs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        files_to_delete = archived_logs[self.days_to_keep:]
        deleted_count = 0
        
        for log_file in files_to_delete:
            try:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would delete old archive: {log_file}")
                else:
                    log_file.unlink()
                    logger.info(f"Deleted old archive: {log_file}")
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {log_file}: {e}")
        
        return deleted_count
    
    def rezip_opened_archives(self, log_file_base: str) -> int:
        """
        Re-compress any unzipped archive files.
        
        Args:
            log_file_base: Base name of the log file (e.g., 'caretakers.log')
            
        Returns:
            Number of files re-compressed
        """
        # Pattern to match unzipped archives: logfile.YYYY-MM-DD[_N] (without .gz)
        patterns = [
            f"{log_file_base}.????-??-??",
            f"{log_file_base}.????-??-??_*"
        ]
        
        unzipped_archives = []
        for pattern in patterns:
            unzipped_archives.extend(self.log_dir.glob(pattern))
        
        # Filter out files that already have a .gz version
        files_to_rezip = []
        for unzipped_file in unzipped_archives:
            gz_version = unzipped_file.with_suffix(unzipped_file.suffix + '.gz')
            if not gz_version.exists():
                files_to_rezip.append(unzipped_file)
        
        rezip_count = 0
        for unzipped_file in files_to_rezip:
            gz_file = unzipped_file.with_suffix(unzipped_file.suffix + '.gz')
            
            try:
                if self.dry_run:
                    logger.info(f"[DRY RUN] Would re-gzip opened archive: {unzipped_file}")
                else:
                    with open(unzipped_file, 'rb') as f_in:
                        with gzip.open(gz_file, 'wb') as f_out:
                            shutil.copyfileobj(f_in, f_out)
                    
                    unzipped_file.unlink()
                    logger.info(f"Re-gzipped opened archive: {unzipped_file}")
                rezip_count += 1
            except Exception as e:
                logger.error(f"Failed to re-gzip {unzipped_file}: {e}")
        
        return rezip_count
    
    def rotate_all(self, files_to_rotate: List[str]) -> dict:
        """
        Rotate all specified log files and perform cleanup.
        
        Args:
            files_to_rotate: List of log file names to rotate
            
        Returns:
            Dictionary with rotation statistics
        """
        stats = {
            'rotated': 0,
            'failed': 0,
            'cleaned': 0,
            'rezipped': 0
        }
        
        logger.info(f"Starting log rotation for {len(files_to_rotate)} files")
        logger.info(f"Log directory: {self.log_dir}")
        logger.info(f"Retention period: {self.days_to_keep} days")
        logger.info(f"Dry run: {self.dry_run}")
        
        for log_file_base in files_to_rotate:
            logger.info(f"Processing {log_file_base}...")
            
            # Rotate the current log file
            if self.rotate_log_file(log_file_base):
                stats['rotated'] += 1
            else:
                stats['failed'] += 1
            
            # Re-zip any opened archives first (before cleanup)
            rezipped = self.rezip_opened_archives(log_file_base)
            stats['rezipped'] += rezipped
            
            # Clean up old archives
            cleaned = self.cleanup_old_logs(log_file_base)
            stats['cleaned'] += cleaned
        
        logger.info(f"Rotation complete. Stats: {stats}")
        return stats


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Rotate and compress log files for DCA Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/log_rotator.py
  python scripts/log_rotator.py --dry-run
  python scripts/log_rotator.py --verbose --days-to-keep 14
  python scripts/log_rotator.py --files caretakers.log cron.log custom.log
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    parser.add_argument(
        '--log-dir',
        type=Path,
        default=DEFAULT_LOG_DIR,
        help=f'Directory containing log files (default: {DEFAULT_LOG_DIR})'
    )
    
    parser.add_argument(
        '--days-to-keep',
        type=int,
        default=DEFAULT_DAYS_TO_KEEP,
        help=f'Number of days of archives to keep (default: {DEFAULT_DAYS_TO_KEEP})'
    )
    
    parser.add_argument(
        '--files',
        nargs='+',
        default=DEFAULT_FILES_TO_ROTATE,
        help=f'Log files to rotate (default: {" ".join(DEFAULT_FILES_TO_ROTATE)})'
    )
    
    return parser.parse_args()


def main():
    """Main function."""
    args = parse_arguments()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logger.setLevel(logging.DEBUG)
    
    # Validate arguments
    if args.days_to_keep < 1:
        logger.error("Days to keep must be at least 1")
        sys.exit(1)
    
    if not args.log_dir.exists() and not args.dry_run:
        logger.error(f"Log directory does not exist: {args.log_dir}")
        sys.exit(1)
    
    # Create rotator and run
    try:
        rotator = LogRotator(
            log_dir=args.log_dir,
            days_to_keep=args.days_to_keep,
            dry_run=args.dry_run
        )
        
        stats = rotator.rotate_all(args.files)
        
        # Exit with error code if any rotations failed
        if stats['failed'] > 0:
            logger.error(f"Some log rotations failed: {stats['failed']} failures")
            sys.exit(1)
        
        logger.info("Log rotation completed successfully")
        
    except KeyboardInterrupt:
        logger.info("Log rotation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error during log rotation: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 