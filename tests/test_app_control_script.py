"""
Tests for the app_control.py script.
"""

import pytest
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock, mock_open
import psutil

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from app_control import (
    read_pid_file,
    is_process_running,
    get_app_status,
    is_maintenance_mode,
    enable_maintenance_mode,
    disable_maintenance_mode,
    stop_main_app,
    start_main_app
)


class TestPidFileOperations:
    """Test PID file reading and validation."""
    
    @patch('app_control.PID_FILE_PATH')
    def test_read_pid_file_not_exists(self, mock_pid_path):
        """Test when PID file doesn't exist."""
        mock_pid_path.exists.return_value = False
        
        result = read_pid_file()
        
        assert result is None
    
    @patch('app_control.PID_FILE_PATH')
    @patch('builtins.open', new_callable=mock_open, read_data='12345')
    def test_read_pid_file_valid(self, mock_file, mock_pid_path):
        """Test reading valid PID from file."""
        mock_pid_path.exists.return_value = True
        
        result = read_pid_file()
        
        assert result == 12345
    
    @patch('app_control.PID_FILE_PATH')
    @patch('builtins.open', new_callable=mock_open, read_data='')
    def test_read_pid_file_empty(self, mock_file, mock_pid_path):
        """Test reading empty PID file."""
        mock_pid_path.exists.return_value = True
        
        result = read_pid_file()
        
        assert result is None
    
    @patch('app_control.PID_FILE_PATH')
    @patch('builtins.open', new_callable=mock_open, read_data='not_a_number')
    def test_read_pid_file_invalid(self, mock_file, mock_pid_path):
        """Test reading invalid PID from file."""
        mock_pid_path.exists.return_value = True
        
        result = read_pid_file()
        
        assert result is None
    
    @patch('app_control.PID_FILE_PATH')
    def test_read_pid_file_io_error(self, mock_pid_path):
        """Test handling IO error when reading PID file."""
        mock_pid_path.exists.return_value = True
        
        with patch('builtins.open', side_effect=IOError("Permission denied")):
            result = read_pid_file()
            
        assert result is None


class TestProcessValidation:
    """Test process running validation."""
    
    @patch('psutil.pid_exists')
    def test_is_process_running_not_exists(self, mock_pid_exists):
        """Test when process doesn't exist."""
        mock_pid_exists.return_value = False
        
        result = is_process_running(12345)
        
        assert result is False
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_not_running(self, mock_process_class, mock_pid_exists):
        """Test when process exists but not running."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = False
        mock_process_class.return_value = mock_process
        
        result = is_process_running(12345)
        
        assert result is False
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_no_cmdline(self, mock_process_class, mock_pid_exists):
        """Test when process has no command line."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = []
        mock_process_class.return_value = mock_process
        
        result = is_process_running(12345)
        
        assert result is False
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_wrong_command(self, mock_process_class, mock_pid_exists):
        """Test when process is running different command."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = ['python', 'other_script.py']
        mock_process_class.return_value = mock_process
        
        result = is_process_running(12345)
        
        assert result is False
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_correct_command(self, mock_process_class, mock_pid_exists):
        """Test when process is running main_app.py."""
        mock_pid_exists.return_value = True
        mock_process = MagicMock()
        mock_process.is_running.return_value = True
        mock_process.cmdline.return_value = ['python', '/path/to/main_app.py']
        mock_process_class.return_value = mock_process
        
        result = is_process_running(12345)
        
        assert result is True
    
    @patch('psutil.pid_exists')
    @patch('psutil.Process')
    def test_is_process_running_exception(self, mock_process_class, mock_pid_exists):
        """Test handling exceptions during process check."""
        mock_pid_exists.return_value = True
        mock_process_class.side_effect = psutil.NoSuchProcess(12345)
        
        result = is_process_running(12345)
        
        assert result is False


class TestAppStatus:
    """Test app status checking."""
    
    @patch('app_control.read_pid_file')
    def test_get_app_status_no_pid(self, mock_read_pid):
        """Test when no PID file exists."""
        mock_read_pid.return_value = None
        
        is_running, pid, uptime = get_app_status()
        
        assert is_running is False
        assert pid is None
        assert uptime is None
    
    @patch('app_control.read_pid_file')
    @patch('app_control.is_process_running')
    @patch('app_control.PID_FILE_PATH')
    def test_get_app_status_stale_pid(self, mock_pid_path, mock_is_running, mock_read_pid):
        """Test when PID file contains stale PID."""
        mock_read_pid.return_value = 12345
        mock_is_running.return_value = False
        mock_pid_path.unlink = MagicMock()
        
        is_running, pid, uptime = get_app_status()
        
        assert is_running is False
        assert pid is None
        assert uptime is None
        mock_pid_path.unlink.assert_called_once_with(missing_ok=True)
    
    @patch('app_control.read_pid_file')
    @patch('app_control.is_process_running')
    @patch('psutil.Process')
    @patch('time.time')
    def test_get_app_status_running_with_uptime(self, mock_time, mock_process_class, mock_is_running, mock_read_pid):
        """Test when app is running with uptime calculation."""
        mock_read_pid.return_value = 12345
        mock_is_running.return_value = True
        mock_time.return_value = 1000.0
        
        mock_process = MagicMock()
        mock_process.create_time.return_value = 940.0  # 60 seconds ago
        mock_process_class.return_value = mock_process
        
        is_running, pid, uptime = get_app_status()
        
        assert is_running is True
        assert pid == 12345
        assert uptime == "1.0m"
    
    @patch('app_control.read_pid_file')
    @patch('app_control.is_process_running')
    @patch('psutil.Process')
    @patch('time.time')
    def test_get_app_status_uptime_formats(self, mock_time, mock_process_class, mock_is_running, mock_read_pid):
        """Test different uptime formats."""
        mock_read_pid.return_value = 12345
        mock_is_running.return_value = True
        mock_process = MagicMock()
        mock_process_class.return_value = mock_process
        
        # Test seconds
        mock_time.return_value = 1030.0
        mock_process.create_time.return_value = 1000.0
        is_running, pid, uptime = get_app_status()
        assert uptime == "30s"
        
        # Test hours
        mock_time.return_value = 7200.0
        mock_process.create_time.return_value = 0.0
        is_running, pid, uptime = get_app_status()
        assert uptime == "2.0h"


class TestMaintenanceMode:
    """Test maintenance mode operations."""
    
    @patch('app_control.MAINTENANCE_FILE_PATH')
    def test_is_maintenance_mode_enabled(self, mock_maintenance_path):
        """Test when maintenance mode is enabled."""
        mock_maintenance_path.exists.return_value = True
        
        result = is_maintenance_mode()
        
        assert result is True
    
    @patch('app_control.MAINTENANCE_FILE_PATH')
    def test_is_maintenance_mode_disabled(self, mock_maintenance_path):
        """Test when maintenance mode is disabled."""
        mock_maintenance_path.exists.return_value = False
        
        result = is_maintenance_mode()
        
        assert result is False
    
    @patch('app_control.logger')
    @patch('builtins.open', new_callable=mock_open)
    @patch('time.strftime')
    def test_enable_maintenance_mode_success(self, mock_strftime, mock_file, mock_logger):
        """Test successful maintenance mode enable."""
        mock_strftime.return_value = "2023-01-01 12:00:00 UTC"
        
        result = enable_maintenance_mode()
        
        assert result is True
        mock_file.assert_called_once()
        mock_logger.info.assert_called_with("🔧 Maintenance mode enabled")
    
    @patch('app_control.logger')
    @patch('builtins.open', side_effect=IOError("Permission denied"))
    def test_enable_maintenance_mode_failure(self, mock_file, mock_logger):
        """Test failed maintenance mode enable."""
        result = enable_maintenance_mode()
        
        assert result is False
        mock_logger.error.assert_called_once()
    
    @patch('app_control.logger')
    @patch('app_control.MAINTENANCE_FILE_PATH')
    def test_disable_maintenance_mode_success(self, mock_maintenance_path, mock_logger):
        """Test successful maintenance mode disable."""
        mock_maintenance_path.unlink = MagicMock()
        
        result = disable_maintenance_mode()
        
        assert result is True
        mock_maintenance_path.unlink.assert_called_once_with(missing_ok=True)
        mock_logger.info.assert_called_with("✅ Maintenance mode disabled")
    
    @patch('app_control.logger')
    @patch('app_control.MAINTENANCE_FILE_PATH')
    def test_disable_maintenance_mode_failure(self, mock_maintenance_path, mock_logger):
        """Test failed maintenance mode disable."""
        mock_maintenance_path.unlink.side_effect = IOError("Permission denied")
        
        result = disable_maintenance_mode()
        
        assert result is False
        mock_logger.error.assert_called_once()


class TestStopMainApp:
    """Test stopping the main app."""
    
    @patch('app_control.get_app_status')
    @patch('app_control.logger')
    def test_stop_main_app_not_running(self, mock_logger, mock_get_status):
        """Test stopping when app is not running."""
        mock_get_status.return_value = (False, None, None)
        
        result = stop_main_app()
        
        assert result is True
        mock_logger.info.assert_called_with("ℹ️ Main app is not running")
    
    @patch('app_control.get_app_status')
    @patch('app_control.PID_FILE_PATH')
    @patch('psutil.Process')
    @patch('app_control.logger')
    def test_stop_main_app_graceful_shutdown(self, mock_logger, mock_process_class, mock_pid_path, mock_get_status):
        """Test successful graceful shutdown."""
        mock_get_status.return_value = (True, 12345, "1.0m")
        mock_process = MagicMock()
        mock_process.wait.return_value = None  # Successful wait
        mock_process_class.return_value = mock_process
        mock_pid_path.unlink = MagicMock()
        
        result = stop_main_app(timeout=1)
        
        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.wait.assert_called_once_with(timeout=1)
        mock_pid_path.unlink.assert_called_once_with(missing_ok=True)
    
    @patch('app_control.get_app_status')
    @patch('app_control.PID_FILE_PATH')
    @patch('psutil.Process')
    @patch('app_control.logger')
    def test_stop_main_app_force_kill(self, mock_logger, mock_process_class, mock_pid_path, mock_get_status):
        """Test force kill after timeout."""
        mock_get_status.return_value = (True, 12345, "1.0m")
        mock_process = MagicMock()
        mock_process.wait.side_effect = [psutil.TimeoutExpired(12345, 1), None]  # Timeout then success
        mock_process_class.return_value = mock_process
        mock_pid_path.unlink = MagicMock()
        
        result = stop_main_app(timeout=1)
        
        assert result is True
        mock_process.terminate.assert_called_once()
        mock_process.kill.assert_called_once()
        assert mock_process.wait.call_count == 2
        mock_pid_path.unlink.assert_called_once_with(missing_ok=True)
    
    @patch('app_control.get_app_status')
    @patch('app_control.PID_FILE_PATH')
    @patch('psutil.Process')
    @patch('app_control.logger')
    def test_stop_main_app_process_not_found(self, mock_logger, mock_process_class, mock_pid_path, mock_get_status):
        """Test when process disappears during stop."""
        mock_get_status.return_value = (True, 12345, "1.0m")
        mock_process_class.side_effect = psutil.NoSuchProcess(12345)
        mock_pid_path.unlink = MagicMock()
        
        result = stop_main_app()
        
        assert result is True
        mock_pid_path.unlink.assert_called_once_with(missing_ok=True)


class TestStartMainApp:
    """Test starting the main app."""
    
    @patch('app_control.get_app_status')
    @patch('app_control.logger')
    def test_start_main_app_already_running(self, mock_logger, mock_get_status):
        """Test starting when app is already running."""
        mock_get_status.return_value = (True, 12345, "1.0m")
        
        result = start_main_app()
        
        assert result is True
        mock_logger.info.assert_called_with("ℹ️ Main app is already running (PID: 12345)")
    
    @patch('app_control.get_app_status')
    @patch('subprocess.Popen')
    @patch('time.sleep')
    @patch('app_control.logger')
    def test_start_main_app_success(self, mock_logger, mock_sleep, mock_popen, mock_get_status):
        """Test successful app start."""
        # First call: not running, second call: running
        mock_get_status.side_effect = [(False, None, None), (True, 12345, "5s")]
        
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        result = start_main_app()
        
        assert result is True
        mock_popen.assert_called_once()
        assert mock_sleep.call_count == 2  # Initial sleep + verification sleep
    
    @patch('app_control.get_app_status')
    @patch('subprocess.Popen')
    @patch('time.sleep')
    @patch('app_control.logger')
    def test_start_main_app_immediate_exit(self, mock_logger, mock_sleep, mock_popen, mock_get_status):
        """Test when app exits immediately."""
        mock_get_status.return_value = (False, None, None)
        
        mock_process = MagicMock()
        mock_process.poll.return_value = 1  # Exited with code 1
        mock_process.returncode = 1
        mock_process.communicate.return_value = (b"stdout", b"stderr")
        mock_popen.return_value = mock_process
        
        result = start_main_app()
        
        assert result is False
        mock_logger.error.assert_any_call("❌ Main app exited immediately with code 1")
    
    @patch('app_control.get_app_status')
    @patch('subprocess.Popen')
    @patch('time.sleep')
    @patch('app_control.logger')
    def test_start_main_app_unstable(self, mock_logger, mock_sleep, mock_popen, mock_get_status):
        """Test when app starts but becomes unstable."""
        # First call: not running, second call: not running, third call: not running
        mock_get_status.side_effect = [(False, None, None), (False, None, None)]
        
        mock_process = MagicMock()
        mock_process.poll.return_value = None  # Still running initially
        mock_process.pid = 12345
        mock_popen.return_value = mock_process
        
        result = start_main_app()
        
        assert result is False
        mock_logger.error.assert_called_with("❌ Main app started but stopped unexpectedly")


class TestIntegration:
    """Integration tests for command combinations."""
    
    @patch('app_control.enable_maintenance_mode')
    @patch('app_control.stop_main_app')
    @patch('app_control.logger')
    def test_cmd_stop_integration(self, mock_logger, mock_stop, mock_enable_maintenance):
        """Test stop command integration."""
        from app_control import cmd_stop
        
        mock_enable_maintenance.return_value = True
        mock_stop.return_value = True
        
        result = cmd_stop()
        
        assert result == 0
        mock_enable_maintenance.assert_called_once()
        mock_stop.assert_called_once()
    
    @patch('app_control.start_main_app')
    @patch('app_control.disable_maintenance_mode')
    @patch('app_control.logger')
    def test_cmd_start_integration(self, mock_logger, mock_disable_maintenance, mock_start):
        """Test start command integration."""
        from app_control import cmd_start
        
        mock_start.return_value = True
        mock_disable_maintenance.return_value = True
        
        result = cmd_start()
        
        assert result == 0
        mock_start.assert_called_once()
        mock_disable_maintenance.assert_called_once()
    
    @patch('app_control.enable_maintenance_mode')
    @patch('app_control.stop_main_app')
    @patch('app_control.start_main_app')
    @patch('app_control.disable_maintenance_mode')
    @patch('time.sleep')
    @patch('app_control.logger')
    def test_cmd_restart_integration(self, mock_logger, mock_sleep, mock_disable_maintenance, 
                                   mock_start, mock_stop, mock_enable_maintenance):
        """Test restart command integration."""
        from app_control import cmd_restart
        
        mock_enable_maintenance.return_value = True
        mock_stop.return_value = True
        mock_start.return_value = True
        mock_disable_maintenance.return_value = True
        
        result = cmd_restart()
        
        assert result == 0
        mock_enable_maintenance.assert_called_once()
        mock_stop.assert_called_once()
        mock_start.assert_called_once()
        mock_disable_maintenance.assert_called_once()
        mock_sleep.assert_called_once_with(1) 