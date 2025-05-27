#!/usr/bin/env python3
"""
DCA Trading Bot - App Control Script

This script provides elegant control over the main trading application while
working seamlessly with the watchdog system.

Commands:
    stop        - Stop the main app and enable maintenance mode
    start       - Start the main app and disable maintenance mode
    restart     - Stop then start (useful for applying asset changes)
    status      - Show current status of app and maintenance mode
    maintenance - Toggle maintenance mode (on/off)

Usage:
    python scripts/app_control.py stop
    python scripts/app_control.py start
    python scripts/app_control.py restart
    python scripts/app_control.py status
    python scripts/app_control.py maintenance on
    python scripts/app_control.py maintenance off

Features:
- Graceful shutdown with SIGTERM → SIGKILL fallback
- Maintenance mode prevents watchdog interference
- Comprehensive status reporting
- Safe timeout handling
- Detailed logging
"""

import argparse
import sys
import os
import signal
import time
import subprocess
from pathlib import Path
from typing import Optional, Tuple
import psutil
import logging

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Create isolated logger for app_control (don't use basicConfig)
logger = logging.getLogger('app_control')
logger.setLevel(logging.INFO)

# Only add handlers if they don't already exist
if not logger.handlers:
    # File handler
    file_handler = logging.FileHandler('logs/caretakers.log')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

# Prevent propagation to root logger
logger.propagate = False

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
MAIN_APP_PATH = PROJECT_ROOT / 'src' / 'main_app.py'
PID_FILE_PATH = PROJECT_ROOT / 'main_app.pid'
MAINTENANCE_FILE_PATH = PROJECT_ROOT / '.maintenance'
PYTHON_INTERPRETER = sys.executable

# Timeouts
GRACEFUL_SHUTDOWN_TIMEOUT = 10  # seconds
STARTUP_VERIFICATION_TIMEOUT = 5  # seconds


def read_pid_file() -> Optional[int]:
    """
    Read PID from the PID file.
    
    Returns:
        int: PID if file exists and contains valid PID, None otherwise
    """
    try:
        if not PID_FILE_PATH.exists():
            return None
        
        with open(PID_FILE_PATH, 'r') as f:
            pid_str = f.read().strip()
        
        if not pid_str:
            return None
        
        return int(pid_str)
        
    except (ValueError, IOError):
        return None


def is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is running and is main_app.py.
    
    Args:
        pid: Process ID to check
    
    Returns:
        bool: True if process is running and is main_app.py, False otherwise
    """
    try:
        if not psutil.pid_exists(pid):
            return False
        
        process = psutil.Process(pid)
        
        if not process.is_running():
            return False
        
        # Check command line to verify it's main_app.py
        cmdline = process.cmdline()
        if not cmdline:
            return False
        
        cmdline_str = ' '.join(cmdline)
        return 'main_app.py' in cmdline_str
        
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False


def get_app_status() -> Tuple[bool, Optional[int], Optional[str]]:
    """
    Get the current status of the main app.
    
    Returns:
        Tuple[bool, Optional[int], Optional[str]]: (is_running, pid, uptime)
    """
    pid = read_pid_file()
    if pid is None:
        return False, None, None
    
    if not is_process_running(pid):
        # Clean up stale PID file
        try:
            PID_FILE_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        return False, None, None
    
    # Get uptime
    try:
        process = psutil.Process(pid)
        create_time = process.create_time()
        uptime_seconds = time.time() - create_time
        
        # Format uptime
        if uptime_seconds < 60:
            uptime = f"{uptime_seconds:.0f}s"
        elif uptime_seconds < 3600:
            uptime = f"{uptime_seconds/60:.1f}m"
        else:
            uptime = f"{uptime_seconds/3600:.1f}h"
            
        return True, pid, uptime
        
    except Exception:
        return True, pid, "unknown"


def is_maintenance_mode() -> bool:
    """
    Check if maintenance mode is enabled.
    
    Returns:
        bool: True if maintenance mode is enabled
    """
    return MAINTENANCE_FILE_PATH.exists()


def enable_maintenance_mode() -> bool:
    """
    Enable maintenance mode by creating the maintenance file.
    
    Returns:
        bool: True if successful
    """
    try:
        with open(MAINTENANCE_FILE_PATH, 'w') as f:
            f.write(f"Maintenance mode enabled at {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}\n")
        logger.info("🔧 Maintenance mode enabled")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to enable maintenance mode: {e}")
        return False


def disable_maintenance_mode() -> bool:
    """
    Disable maintenance mode by removing the maintenance file.
    
    Returns:
        bool: True if successful
    """
    try:
        MAINTENANCE_FILE_PATH.unlink(missing_ok=True)
        logger.info("✅ Maintenance mode disabled")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to disable maintenance mode: {e}")
        return False


def stop_main_app(timeout: int = GRACEFUL_SHUTDOWN_TIMEOUT) -> bool:
    """
    Stop the main app gracefully.
    
    Args:
        timeout: Maximum time to wait for graceful shutdown
        
    Returns:
        bool: True if stopped successfully
    """
    is_running, pid, _ = get_app_status()
    
    if not is_running:
        logger.info("ℹ️ Main app is not running")
        return True
    
    logger.info(f"🛑 Stopping main app (PID: {pid})...")
    
    try:
        process = psutil.Process(pid)
        
        # Send SIGTERM for graceful shutdown
        logger.info("📤 Sending SIGTERM for graceful shutdown...")
        process.terminate()
        
        # Wait for graceful shutdown
        try:
            process.wait(timeout=timeout)
            logger.info("✅ Main app stopped gracefully")
            
            # Clean up PID file
            PID_FILE_PATH.unlink(missing_ok=True)
            return True
            
        except psutil.TimeoutExpired:
            logger.warning(f"⏰ Graceful shutdown timed out after {timeout}s, forcing kill...")
            
            # Force kill with SIGKILL
            process.kill()
            process.wait(timeout=5)  # Wait a bit more for force kill
            logger.info("💀 Main app force killed")
            
            # Clean up PID file
            PID_FILE_PATH.unlink(missing_ok=True)
            return True
            
    except psutil.NoSuchProcess:
        logger.info("ℹ️ Process already stopped")
        PID_FILE_PATH.unlink(missing_ok=True)
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to stop main app: {e}")
        return False


def start_main_app() -> bool:
    """
    Start the main app.
    
    Returns:
        bool: True if started successfully
    """
    is_running, pid, _ = get_app_status()
    
    if is_running:
        logger.info(f"ℹ️ Main app is already running (PID: {pid})")
        return True
    
    logger.info("🚀 Starting main app...")
    
    try:
        # Start process in background
        cmd = [PYTHON_INTERPRETER, str(MAIN_APP_PATH)]
        process = subprocess.Popen(
            cmd,
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # Detach from parent
        )
        
        # Give it a moment to start
        time.sleep(2)
        
        # Verify it's still running
        if process.poll() is None:
            logger.info(f"✅ Main app started successfully (PID: {process.pid})")
            
            # Wait a bit more and verify it's stable
            time.sleep(STARTUP_VERIFICATION_TIMEOUT - 2)
            
            is_running, pid, _ = get_app_status()
            if is_running:
                logger.info(f"🎯 Main app is running stably (PID: {pid})")
                return True
            else:
                logger.error("❌ Main app started but stopped unexpectedly")
                return False
        else:
            # Process exited immediately
            stdout, stderr = process.communicate()
            logger.error(f"❌ Main app exited immediately with code {process.returncode}")
            if stdout:
                logger.error(f"STDOUT: {stdout.decode()}")
            if stderr:
                logger.error(f"STDERR: {stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to start main app: {e}")
        return False


def cmd_stop() -> int:
    """Stop command: Stop app and enable maintenance mode."""
    logger.info("="*60)
    logger.info("STOPPING MAIN APP")
    logger.info("="*60)
    
    # Enable maintenance mode first
    if not enable_maintenance_mode():
        return 1
    
    # Stop the app
    if not stop_main_app():
        return 1
    
    logger.info("🎯 Stop completed successfully")
    return 0


def cmd_start() -> int:
    """Start command: Start app and disable maintenance mode."""
    logger.info("="*60)
    logger.info("STARTING MAIN APP")
    logger.info("="*60)
    
    # Start the app
    if not start_main_app():
        return 1
    
    # Disable maintenance mode
    if not disable_maintenance_mode():
        return 1
    
    logger.info("🎯 Start completed successfully")
    return 0


def cmd_restart() -> int:
    """Restart command: Stop then start."""
    logger.info("="*60)
    logger.info("RESTARTING MAIN APP")
    logger.info("="*60)
    
    # Enable maintenance mode
    if not enable_maintenance_mode():
        return 1
    
    # Stop the app
    if not stop_main_app():
        return 1
    
    # Brief pause
    time.sleep(1)
    
    # Start the app
    if not start_main_app():
        return 1
    
    # Disable maintenance mode
    if not disable_maintenance_mode():
        return 1
    
    logger.info("🎯 Restart completed successfully")
    return 0


def cmd_status() -> int:
    """Status command: Show current status."""
    logger.info("="*60)
    logger.info("MAIN APP STATUS")
    logger.info("="*60)
    
    # App status
    is_running, pid, uptime = get_app_status()
    if is_running:
        logger.info(f"📱 Main App: RUNNING (PID: {pid}, Uptime: {uptime})")
    else:
        logger.info("📱 Main App: STOPPED")
    
    # Maintenance mode status
    maintenance = is_maintenance_mode()
    if maintenance:
        logger.info("🔧 Maintenance Mode: ENABLED")
        try:
            with open(MAINTENANCE_FILE_PATH, 'r') as f:
                content = f.read().strip()
                logger.info(f"   {content}")
        except Exception:
            pass
    else:
        logger.info("🔧 Maintenance Mode: DISABLED")
    
    # Watchdog status
    if maintenance:
        logger.info("👁️ Watchdog: PAUSED (will not restart app)")
    else:
        logger.info("👁️ Watchdog: ACTIVE (will restart app if needed)")
    
    # PID file status
    if PID_FILE_PATH.exists():
        logger.info(f"📄 PID File: EXISTS ({PID_FILE_PATH})")
    else:
        logger.info("📄 PID File: NOT FOUND")
    
    # Recent log entries
    log_file = PROJECT_ROOT / 'logs' / 'main_app.log'
    if log_file.exists():
        logger.info("📋 Recent Log Entries:")
        try:
            # Get last 5 lines
            with open(log_file, 'r') as f:
                lines = f.readlines()
                for line in lines[-5:]:
                    logger.info(f"   {line.strip()}")
        except Exception:
            logger.info("   (Unable to read log file)")
    
    return 0


def cmd_maintenance(mode: str) -> int:
    """Maintenance command: Toggle maintenance mode."""
    logger.info("="*60)
    logger.info(f"MAINTENANCE MODE: {mode.upper()}")
    logger.info("="*60)
    
    if mode == "on":
        if enable_maintenance_mode():
            logger.info("🎯 Maintenance mode enabled successfully")
            return 0
        else:
            return 1
    elif mode == "off":
        if disable_maintenance_mode():
            logger.info("🎯 Maintenance mode disabled successfully")
            return 0
        else:
            return 1
    else:
        logger.error(f"❌ Invalid maintenance mode: {mode} (use 'on' or 'off')")
        return 1


def main():
    """Main function to handle command line arguments."""
    parser = argparse.ArgumentParser(
        description="Control the DCA Trading Bot main application",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  stop                    Stop the main app and enable maintenance mode
  start                   Start the main app and disable maintenance mode
  restart                 Stop then start (useful for applying asset changes)
  status                  Show current status of app and maintenance mode
  maintenance on|off      Toggle maintenance mode

Examples:
  python scripts/app_control.py stop
  python scripts/app_control.py start
  python scripts/app_control.py restart
  python scripts/app_control.py status
  python scripts/app_control.py maintenance on
  python scripts/app_control.py maintenance off

Maintenance Mode:
  When enabled, the watchdog will not restart the main app, allowing
  for manual control and maintenance operations.
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Stop command
    subparsers.add_parser('stop', help='Stop the main app and enable maintenance mode')
    
    # Start command
    subparsers.add_parser('start', help='Start the main app and disable maintenance mode')
    
    # Restart command
    subparsers.add_parser('restart', help='Stop then start the main app')
    
    # Status command
    subparsers.add_parser('status', help='Show current status')
    
    # Maintenance command
    maintenance_parser = subparsers.add_parser('maintenance', help='Toggle maintenance mode')
    maintenance_parser.add_argument('mode', choices=['on', 'off'], help='Enable or disable maintenance mode')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Execute command
    try:
        if args.command == 'stop':
            return cmd_stop()
        elif args.command == 'start':
            return cmd_start()
        elif args.command == 'restart':
            return cmd_restart()
        elif args.command == 'status':
            return cmd_status()
        elif args.command == 'maintenance':
            return cmd_maintenance(args.mode)
        else:
            logger.error(f"❌ Unknown command: {args.command}")
            return 1
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Operation cancelled by user")
        return 1
    except Exception as e:
        logger.error(f"❌ Unexpected error: {e}")
        logger.exception("Full traceback:")
        return 1


if __name__ == "__main__":
    sys.exit(main()) 