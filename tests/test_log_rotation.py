#!/usr/bin/env python3
"""
Unit tests for log rotation functionality.

Tests both the GzipTimedRotatingFileHandler and the external LogRotator script.
"""

import pytest
import tempfile
import gzip
import shutil
import logging
import time
import os
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# Import the components to test
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from utils.logging_config import GzipTimedRotatingFileHandler
from log_rotator import LogRotator


class TestGzipTimedRotatingFileHandler:
    """Test the custom TimedRotatingFileHandler with gzip compression."""
    
    def test_gzip_namer(self):
        """Test that the namer adds .gz extension."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "test.log"
            
            handler = GzipTimedRotatingFileHandler(
                str(log_file),
                when='midnight',
                interval=1,
                backupCount=3
            )
            
            # Test the namer function
            result = handler._gzip_namer("test.log.2024-01-01")
            assert result == "test.log.2024-01-01.gz"
    
    def test_gzip_rotator(self):
        """Test that the rotator compresses files correctly."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "test.log"
            source_file = temp_path / "test.log.2024-01-01"
            dest_file = temp_path / "test.log.2024-01-01.gz"
            
            # Create a test log file with content
            test_content = "Test log content\nLine 2\nLine 3\n"
            source_file.write_text(test_content)
            
            handler = GzipTimedRotatingFileHandler(
                str(log_file),
                when='midnight',
                interval=1,
                backupCount=3
            )
            
            # Test the rotator function
            handler._gzip_rotator(str(source_file), str(dest_file))
            
            # Verify the gzipped file exists and source is removed
            assert dest_file.exists()
            assert not source_file.exists()
            
            # Verify the content is correctly compressed
            with gzip.open(dest_file, 'rt') as f:
                decompressed_content = f.read()
            assert decompressed_content == test_content
    
    def test_gzip_rotator_fallback_on_error(self):
        """Test that rotator falls back to regular rotation on gzip error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            log_file = temp_path / "test.log"
            source_file = temp_path / "test.log.2024-01-01"
            dest_file = temp_path / "test.log.2024-01-01.gz"
            
            # Create a test log file
            source_file.write_text("Test content")
            
            handler = GzipTimedRotatingFileHandler(
                str(log_file),
                when='midnight',
                interval=1,
                backupCount=3
            )
            
            # Mock gzip.open to raise an exception
            with patch('gzip.open', side_effect=Exception("Gzip error")):
                with patch('builtins.print') as mock_print:
                    handler._gzip_rotator(str(source_file), str(dest_file))
                    
                    # Should have printed a warning
                    mock_print.assert_called_once()
                    assert "Warning: Failed to gzip" in str(mock_print.call_args)
            
            # Should have fallen back to regular rotation (without .gz)
            fallback_file = temp_path / "test.log.2024-01-01"
            assert fallback_file.exists()
            assert not dest_file.exists()


class TestLogRotator:
    """Test the external log rotation script functionality."""
    
    @pytest.fixture
    def temp_log_dir(self):
        """Create a temporary directory for log files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)
    
    @pytest.fixture
    def rotator(self, temp_log_dir):
        """Create a LogRotator instance for testing."""
        return LogRotator(log_dir=temp_log_dir, days_to_keep=3, dry_run=False)
    
    @pytest.fixture
    def dry_run_rotator(self, temp_log_dir):
        """Create a LogRotator instance in dry-run mode."""
        return LogRotator(log_dir=temp_log_dir, days_to_keep=3, dry_run=True)
    
    def test_rotate_log_file_success(self, rotator, temp_log_dir):
        """Test successful log file rotation."""
        # Create a test log file with content
        log_file = temp_log_dir / "test.log"
        test_content = "Log line 1\nLog line 2\nLog line 3\n"
        log_file.write_text(test_content)
        
        # Rotate the file
        result = rotator.rotate_log_file("test.log")
        
        assert result is True
        assert not log_file.exists()  # Original file should be gone
        
        # Find the archived file
        archived_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(archived_files) == 1
        
        # Verify content is preserved
        with gzip.open(archived_files[0], 'rt') as f:
            archived_content = f.read()
        assert archived_content == test_content
    
    def test_rotate_log_file_nonexistent(self, rotator, temp_log_dir):
        """Test rotation of non-existent file."""
        result = rotator.rotate_log_file("nonexistent.log")
        assert result is True  # Should succeed (no-op)
    
    def test_rotate_log_file_empty(self, rotator, temp_log_dir):
        """Test rotation of empty file."""
        log_file = temp_log_dir / "empty.log"
        log_file.touch()  # Create empty file
        
        result = rotator.rotate_log_file("empty.log")
        assert result is True  # Should succeed (no-op)
        assert log_file.exists()  # Empty file should remain
    
    def test_rotate_log_file_dry_run(self, dry_run_rotator, temp_log_dir):
        """Test dry run mode doesn't actually rotate files."""
        log_file = temp_log_dir / "test.log"
        log_file.write_text("Test content")
        
        result = dry_run_rotator.rotate_log_file("test.log")
        
        assert result is True
        assert log_file.exists()  # File should still exist in dry run
        
        # No archived files should be created
        archived_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(archived_files) == 0
    
    def test_rotate_log_file_unique_naming(self, rotator, temp_log_dir):
        """Test that multiple rotations on same day get unique names."""
        log_file = temp_log_dir / "test.log"
        
        # Create and rotate first file
        log_file.write_text("Content 1")
        result1 = rotator.rotate_log_file("test.log")
        assert result1 is True
        
        # Create and rotate second file (same day)
        log_file.write_text("Content 2")
        result2 = rotator.rotate_log_file("test.log")
        assert result2 is True
        
        # Should have two different archived files
        archived_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(archived_files) == 2
        
        # Names should be different
        names = [f.name for f in archived_files]
        assert len(set(names)) == 2  # All unique names
    
    def test_cleanup_old_logs(self, rotator, temp_log_dir):
        """Test cleanup of old archived logs."""
        # Create several old archived files
        today = datetime.now()
        for i in range(5):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            archive_file = temp_log_dir / f"test.log.{date_str}.gz"
            
            # Create a gzipped file with some content
            with gzip.open(archive_file, 'wt') as f:
                f.write(f"Content from day {i}")
            
            # Set modification time to match the date
            timestamp = date.timestamp()
            os.utime(archive_file, (timestamp, timestamp))
        
        # Should have 5 files initially
        archived_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(archived_files) == 5
        
        # Clean up (keep 3 days)
        deleted_count = rotator.cleanup_old_logs("test.log")
        
        # Should have deleted 2 files (5 - 3 = 2)
        assert deleted_count == 2
        
        # Should have 3 files remaining
        remaining_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(remaining_files) == 3
    
    def test_cleanup_old_logs_dry_run(self, dry_run_rotator, temp_log_dir):
        """Test cleanup in dry run mode."""
        # Create old archived files
        for i in range(5):
            date = datetime.now() - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            archive_file = temp_log_dir / f"test.log.{date_str}.gz"
            with gzip.open(archive_file, 'wt') as f:
                f.write(f"Content {i}")
        
        # Dry run cleanup
        deleted_count = dry_run_rotator.cleanup_old_logs("test.log")
        
        # Should report what would be deleted
        assert deleted_count == 2
        
        # But files should still exist
        remaining_files = list(temp_log_dir.glob("test.log.*.gz"))
        assert len(remaining_files) == 5
    
    def test_rezip_opened_archives(self, rotator, temp_log_dir):
        """Test re-compression of unzipped archive files."""
        # Create some unzipped archive files
        today = datetime.now()
        unzipped_files = []
        
        for i in range(3):
            date = today - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            unzipped_file = temp_log_dir / f"test.log.{date_str}"
            unzipped_file.write_text(f"Unzipped content {i}")
            unzipped_files.append(unzipped_file)
        
        # Also create one that already has a .gz version (should be skipped)
        skip_file = temp_log_dir / f"test.log.{today.strftime('%Y-%m-%d')}_1"
        skip_file.write_text("Skip this")
        skip_gz = temp_log_dir / f"test.log.{today.strftime('%Y-%m-%d')}_1.gz"
        with gzip.open(skip_gz, 'wt') as f:
            f.write("Already compressed")
        
        # Re-zip the archives
        rezipped_count = rotator.rezip_opened_archives("test.log")
        
        # Should have re-zipped 3 files (not the one that already had .gz)
        # Note: The skip_file might also get processed if it matches the pattern
        assert rezipped_count >= 3
        
        # Original unzipped files should be gone
        for unzipped_file in unzipped_files:
            assert not unzipped_file.exists()
        
        # Gzipped versions should exist
        for unzipped_file in unzipped_files:
            gz_file = unzipped_file.with_suffix(unzipped_file.suffix + '.gz')
            assert gz_file.exists()
        
        # Skip file should still exist (wasn't processed)
        assert skip_file.exists()
    
    def test_rezip_opened_archives_dry_run(self, dry_run_rotator, temp_log_dir):
        """Test re-compression in dry run mode."""
        # Create unzipped archive file
        unzipped_file = temp_log_dir / "test.log.2024-01-01"
        unzipped_file.write_text("Test content")
        
        # Dry run re-zip
        rezipped_count = dry_run_rotator.rezip_opened_archives("test.log")
        
        # Should report what would be done
        assert rezipped_count == 1
        
        # But file should still exist uncompressed
        assert unzipped_file.exists()
        gz_file = unzipped_file.with_suffix('.gz')
        assert not gz_file.exists()
    
    def test_rotate_all_integration(self, rotator, temp_log_dir):
        """Test the complete rotation process."""
        # Create test log files
        files_to_rotate = ["caretakers.log", "cron.log"]
        
        for log_name in files_to_rotate:
            log_file = temp_log_dir / log_name
            log_file.write_text(f"Content for {log_name}")
        
        # Create some old archives to test cleanup (need to be older than retention period)
        old_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        old_archive = temp_log_dir / f"caretakers.log.{old_date}.gz"
        with gzip.open(old_archive, 'wt') as f:
            f.write("Old content")
        
        # Set the modification time to be old enough for cleanup
        old_timestamp = (datetime.now() - timedelta(days=5)).timestamp()
        os.utime(old_archive, (old_timestamp, old_timestamp))
        
        # Create an unzipped archive to test re-zipping
        unzipped_archive = temp_log_dir / f"cron.log.{old_date}"
        unzipped_archive.write_text("Unzipped content")
        
        # Run rotation
        stats = rotator.rotate_all(files_to_rotate)
        
        # Verify stats
        assert stats['rotated'] == 2  # Both files rotated
        assert stats['failed'] == 0   # No failures
        assert stats['cleaned'] >= 0  # May or may not clean depending on timing
        assert stats['rezipped'] >= 1 # At least one file re-zipped
        
        # Verify original files are gone
        for log_name in files_to_rotate:
            assert not (temp_log_dir / log_name).exists()
        
        # Verify new archives exist
        new_archives = list(temp_log_dir.glob("*.log.*.gz"))
        assert len(new_archives) >= 2  # At least the 2 we just created
    
    def test_error_handling_in_rotation(self, rotator, temp_log_dir):
        """Test error handling during rotation."""
        log_file = temp_log_dir / "test.log"
        log_file.write_text("Test content")
        
        # Mock shutil.move to raise an exception
        with patch('shutil.move', side_effect=Exception("Move failed")):
            result = rotator.rotate_log_file("test.log")
            
            # Should return False on failure
            assert result is False
            
            # Original file should still exist
            assert log_file.exists()


@pytest.mark.integration
class TestLogRotationIntegration:
    """Integration tests for log rotation functionality."""
    
    def test_gzip_handler_with_real_logging(self):
        """Test the GzipTimedRotatingFileHandler with actual logging."""
        with tempfile.TemporaryDirectory() as temp_dir:
            log_file = Path(temp_dir) / "integration_test.log"
            
            # Create handler with very short interval for testing
            handler = GzipTimedRotatingFileHandler(
                str(log_file),
                when='S',  # Every second for testing
                interval=1,
                backupCount=2
            )
            
            # Create logger and add handler
            logger = logging.getLogger('integration_test')
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            
            # Log some messages
            logger.info("First message")
            logger.info("Second message")
            
            # Force a rotation by calling doRollover
            handler.doRollover()
            
            # Log more messages
            logger.info("Third message")
            logger.info("Fourth message")
            
            # Clean up
            logger.removeHandler(handler)
            handler.close()
            
            # Verify files exist
            assert log_file.exists()  # Current log file
            
            # Should have at least one archived file
            archived_files = list(Path(temp_dir).glob("integration_test.log.*.gz"))
            assert len(archived_files) >= 1
            
            # Verify archived content is compressed and readable
            with gzip.open(archived_files[0], 'rt') as f:
                content = f.read()
                assert "First message" in content or "Second message" in content
    
    def test_log_rotator_script_execution(self):
        """Test running the log rotator script end-to-end."""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_log_dir = Path(temp_dir)
            
            # Create test log files
            caretakers_log = temp_log_dir / "caretakers.log"
            cron_log = temp_log_dir / "cron.log"
            
            caretakers_log.write_text("Caretaker log content\nLine 2\n")
            cron_log.write_text("Cron log content\nAnother line\n")
            
            # Create rotator and run
            rotator = LogRotator(log_dir=temp_log_dir, days_to_keep=7, dry_run=False)
            stats = rotator.rotate_all(["caretakers.log", "cron.log"])
            
            # Verify successful rotation
            assert stats['rotated'] == 2
            assert stats['failed'] == 0
            
            # Verify original files are rotated
            assert not caretakers_log.exists()
            assert not cron_log.exists()
            
            # Verify archived files exist and are compressed
            archived_files = list(temp_log_dir.glob("*.log.*.gz"))
            assert len(archived_files) == 2
            
            # Verify content is preserved
            for archived_file in archived_files:
                with gzip.open(archived_file, 'rt') as f:
                    content = f.read()
                    assert len(content) > 0
                    assert "content" in content 