#!/usr/bin/env python3
"""
Unit tests for the watchdog script.

Tests cover:
- PID file reading and validation
- Process monitoring and verification
- Email alert functionality
- Main app startup logic
- Error handling and edge cases
"""

import unittest
from unittest.mock import patch, mock_open, MagicMock, call
import os
import sys
from pathlib import Path
import psutil
import smtplib
import email.message

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / 'scripts'))

# Import the watchdog module
import watchdog


class TestWatchdog(unittest.TestCase):
    """Test cases for watchdog script functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.test_pid = 12345
        self.test_pid_file = Path('/tmp/test_main_app.pid')
        
        # Mock the PID file path
        self.original_pid_file = watchdog.PID_FILE_PATH
        watchdog.PID_FILE_PATH = self.test_pid_file
    
    def tearDown(self):
        """Clean up after tests."""
        # Restore original PID file path
        watchdog.PID_FILE_PATH = self.original_pid_file
    
    def test_read_pid_file_success(self):
        """Test successful PID file reading."""
        with patch('builtins.open', mock_open(read_data='12345')):
            with patch('pathlib.Path.exists', return_value=True):
                pid = watchdog.read_pid_file()
                self.assertEqual(pid, 12345)
    
    def test_read_pid_file_not_exists(self):
        """Test PID file reading when file doesn't exist."""
        with patch('pathlib.Path.exists', return_value=False):
            pid = watchdog.read_pid_file()
            self.assertIsNone(pid)
    
    def test_read_pid_file_empty(self):
        """Test PID file reading when file is empty."""
        with patch('builtins.open', mock_open(read_data='')):
            with patch('pathlib.Path.exists', return_value=True):
                pid = watchdog.read_pid_file()
                self.assertIsNone(pid)
    
    def test_read_pid_file_invalid_content(self):
        """Test PID file reading with invalid content."""
        with patch('builtins.open', mock_open(read_data='not_a_number')):
            with patch('pathlib.Path.exists', return_value=True):
                pid = watchdog.read_pid_file()
                self.assertIsNone(pid)
    
    def test_read_pid_file_io_error(self):
        """Test PID file reading with IO error."""
        with patch('builtins.open', side_effect=IOError("Permission denied")):
            with patch('pathlib.Path.exists', return_value=True):
                pid = watchdog.read_pid_file()
                self.assertIsNone(pid)
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_success(self, mock_process_class, mock_pid_exists):
        """Test successful process verification."""
        # Setup mocks
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = ['python', '/path/to/main_app.py']
        mock_process_class.return_value = mock_process
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertTrue(result)
        mock_pid_exists.assert_called_once_with(self.test_pid)
        mock_process_class.assert_called_once_with(self.test_pid)
        mock_process.is_running.assert_called_once()
        mock_process.cmdline.assert_called_once()
    
    @patch('psutil.pid_exists')
    def test_is_process_running_not_exists(self, mock_pid_exists):
        """Test process verification when PID doesn't exist."""
        mock_pid_exists.return_value = False
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertFalse(result)
        mock_pid_exists.assert_called_once_with(self.test_pid)
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_not_running(self, mock_process_class, mock_pid_exists):
        """Test process verification when process is not running."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = False
        mock_process_class.return_value = mock_process
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertFalse(result)
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_wrong_command(self, mock_process_class, mock_pid_exists):
        """Test process verification when command line doesn't match."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = ['python', '/path/to/other_script.py']
        mock_process_class.return_value = mock_process
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertFalse(result)
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_no_cmdline(self, mock_process_class, mock_pid_exists):
        """Test process verification when command line is empty."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = []
        mock_process_class.return_value = mock_process
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertFalse(result)
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_access_denied(self, mock_process_class, mock_pid_exists):
        """Test process verification with access denied error."""
        mock_pid_exists.return_value = True
        mock_process_class.side_effect = psutil.AccessDenied()
        
        result = watchdog.is_process_running(self.test_pid)
        
        self.assertFalse(result)
    
    @patch('watchdog.read_pid_file')
    @patch('watchdog.is_process_running')
    def test_is_main_app_running_success(self, mock_is_running, mock_read_pid):
        """Test main app running check when app is running."""
        mock_read_pid.return_value = self.test_pid
        mock_is_running.return_value = True
        
        is_running, pid = watchdog.is_main_app_running()
        
        self.assertTrue(is_running)
        self.assertEqual(pid, self.test_pid)
        mock_read_pid.assert_called_once()
        mock_is_running.assert_called_once_with(self.test_pid)
    
    @patch('watchdog.read_pid_file')
    def test_is_main_app_running_no_pid_file(self, mock_read_pid):
        """Test main app running check when no PID file exists."""
        mock_read_pid.return_value = None
        
        is_running, pid = watchdog.is_main_app_running()
        
        self.assertFalse(is_running)
        self.assertIsNone(pid)
        mock_read_pid.assert_called_once()
    
    @patch('watchdog.read_pid_file')
    @patch('watchdog.is_process_running')
    def test_is_main_app_running_stale_pid(self, mock_is_running, mock_read_pid):
        """Test main app running check with stale PID."""
        mock_read_pid.return_value = self.test_pid
        mock_is_running.return_value = False
        
        with patch('pathlib.Path.unlink') as mock_unlink:
            is_running, pid = watchdog.is_main_app_running()
        
        self.assertFalse(is_running)
        self.assertIsNone(pid)
        mock_unlink.assert_called_once_with(missing_ok=True)
    
    @patch('subprocess.Popen')
    @patch('time.sleep')
    def test_start_main_app_success(self, mock_sleep, mock_popen):
        """Test successful main app startup."""
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Process still running
        mock_process.pid = self.test_pid
        mock_popen.return_value = mock_process
        
        result = watchdog.start_main_app()
        
        self.assertTrue(result)
        mock_popen.assert_called_once()
        mock_sleep.assert_called_once_with(2)
        mock_process.poll.assert_called_once()
    
    @patch('subprocess.Popen')
    @patch('time.sleep')
    def test_start_main_app_immediate_exit(self, mock_sleep, mock_popen):
        """Test main app startup when process exits immediately."""
        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Process exited with code 1
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b'stdout', b'stderr')
        mock_popen.return_value = mock_process
        
        result = watchdog.start_main_app()
        
        self.assertFalse(result)
        mock_process.communicate.assert_called_once()
    
    @patch('subprocess.Popen')
    def test_start_main_app_exception(self, mock_popen):
        """Test main app startup with exception."""
        mock_popen.side_effect = Exception("Failed to start process")
        
        result = watchdog.start_main_app()
        
        self.assertFalse(result)
    
    @patch.dict(os.environ, {
        'SMTP_SERVER': 'smtp.example.com',
        'SMTP_PORT': '587',
        'SMTP_USERNAME': 'user@example.com',
        'SMTP_PASSWORD': 'password',
        'ALERT_EMAIL_FROM': 'bot@example.com',
        'ALERT_EMAIL_TO': 'admin@example.com'
    })
    @patch('smtplib.SMTP')
    def test_send_email_alert_success(self, mock_smtp_class):
        """Test successful email alert sending."""
        mock_smtp = MagicMock()
        mock_smtp_class.return_value.__enter__.return_value = mock_smtp
        
        result = watchdog.send_email_alert("Test Subject", "Test Body")
        
        self.assertTrue(result)
        mock_smtp_class.assert_called_once_with('smtp.example.com', 587)
        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with('user@example.com', 'password')
        mock_smtp.send_message.assert_called_once()
    
    def test_send_email_alert_not_configured(self):
        """Test email alert when SMTP is not configured."""
        with patch.dict(os.environ, {}, clear=True):
            result = watchdog.send_email_alert("Test Subject", "Test Body")
            self.assertFalse(result)
    
    @patch.dict(os.environ, {
        'SMTP_SERVER': 'smtp.example.com',
        'SMTP_USERNAME': 'user@example.com',
        'SMTP_PASSWORD': 'password',
        'ALERT_EMAIL_FROM': 'bot@example.com',
        'ALERT_EMAIL_TO': 'admin@example.com'
    })
    @patch('smtplib.SMTP')
    def test_send_email_alert_smtp_error(self, mock_smtp_class):
        """Test email alert with SMTP error."""
        mock_smtp_class.side_effect = smtplib.SMTPException("SMTP Error")
        
        result = watchdog.send_email_alert("Test Subject", "Test Body")
        
        self.assertFalse(result)
    
    def test_cleanup_stale_resources(self):
        """Test cleanup of stale resources."""
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.unlink') as mock_unlink:
                watchdog.cleanup_stale_resources()
                mock_unlink.assert_called_once()
    
    def test_cleanup_stale_resources_no_file(self):
        """Test cleanup when no stale resources exist."""
        with patch('pathlib.Path.exists', return_value=False):
            with patch('pathlib.Path.unlink') as mock_unlink:
                watchdog.cleanup_stale_resources()
                mock_unlink.assert_not_called()
    
    def test_cleanup_stale_resources_error(self):
        """Test cleanup with error."""
        with patch('pathlib.Path.exists', return_value=True):
            with patch('pathlib.Path.unlink', side_effect=OSError("Permission denied")):
                # Should not raise exception
                watchdog.cleanup_stale_resources()
    
    @patch('watchdog.is_main_app_running')
    @patch('watchdog.logger')
    def test_main_app_running(self, mock_logger, mock_is_running):
        """Test main function when app is already running."""
        mock_is_running.return_value = (True, self.test_pid)
        
        watchdog.main()
        
        mock_is_running.assert_called_once()
        # Check that appropriate log messages were called
        mock_logger.info.assert_any_call(f"✅ main_app.py is running (PID: {self.test_pid})")
        mock_logger.info.assert_any_call("🔍 No action needed - application is healthy")
    
    @patch('watchdog.is_main_app_running')
    @patch('watchdog.cleanup_stale_resources')
    @patch('watchdog.start_main_app')
    @patch('watchdog.send_email_alert')
    @patch('watchdog.logger')
    def test_main_app_not_running_restart_success(self, mock_logger, mock_email, 
                                                  mock_start, mock_cleanup, mock_is_running):
        """Test main function when app is not running and restart succeeds."""
        mock_is_running.return_value = (False, None)
        mock_start.return_value = True
        
        watchdog.main()
        
        mock_is_running.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_start.assert_called_once()
        mock_email.assert_called_once_with(
            "Main App Restarted",
            "The DCA Trading Bot main application was not running and has been successfully restarted."
        )
        mock_logger.info.assert_any_call("✅ Successfully restarted main_app.py")
    
    @patch('watchdog.is_main_app_running')
    @patch('watchdog.cleanup_stale_resources')
    @patch('watchdog.start_main_app')
    @patch('watchdog.send_email_alert')
    @patch('watchdog.logger')
    @patch('sys.exit')
    def test_main_app_not_running_restart_failure(self, mock_exit, mock_logger, mock_email, 
                                                  mock_start, mock_cleanup, mock_is_running):
        """Test main function when app is not running and restart fails."""
        mock_is_running.return_value = (False, None)
        mock_start.return_value = False
        
        watchdog.main()
        
        mock_is_running.assert_called_once()
        mock_cleanup.assert_called_once()
        mock_start.assert_called_once()
        mock_email.assert_called_once_with(
            "CRITICAL: Failed to Restart Main App",
            "The DCA Trading Bot main application was not running and failed to restart. Manual intervention required."
        )
        mock_logger.error.assert_any_call("❌ Failed to restart main_app.py")
        mock_exit.assert_called_once_with(1)
    
    @patch('watchdog.is_main_app_running')
    @patch('watchdog.send_email_alert')
    @patch('watchdog.logger')
    @patch('sys.exit')
    def test_main_exception_handling(self, mock_exit, mock_logger, mock_email, mock_is_running):
        """Test main function exception handling."""
        mock_is_running.side_effect = Exception("Unexpected error")
        
        watchdog.main()
        
        mock_email.assert_called_once()
        # Check that the email contains the error message
        args, kwargs = mock_email.call_args
        self.assertIn("Unexpected error", args[1])
        mock_exit.assert_called_once_with(1)


if __name__ == '__main__':
    unittest.main() 