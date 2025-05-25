#!/usr/bin/env python3
"""
DCA Trading Bot - Watchdog Script

This script monitors the main WebSocket application (main_app.py) and restarts it if needed.
Designed to be run by cron every few minutes to ensure the trading bot stays operational.

Features:
- PID file-based process monitoring
- Automatic restart with proper environment
- Email alerts for failures and restarts
- Comprehensive logging
- Graceful error handling

Usage:
    python scripts/watchdog.py

Environment Variables (optional):
    SMTP_SERVER - SMTP server for email alerts
    SMTP_PORT - SMTP port (default: 587)
    SMTP_USERNAME - SMTP username
    SMTP_PASSWORD - SMTP password
    ALERT_EMAIL_FROM - From email address
    ALERT_EMAIL_TO - To email address
"""

import subprocess
import os
import sys
import logging
import smtplib
import email.message
import time
import signal
from pathlib import Path
from typing import Optional, Tuple
import psutil

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(project_root / 'logs' / 'watchdog.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
MAIN_APP_PATH = project_root / 'src' / 'main_app.py'
PID_FILE_PATH = project_root / 'main_app.pid'
PYTHON_INTERPRETER = sys.executable  # Use current Python interpreter
LOG_DIR = project_root / 'logs'

# Ensure log directory exists
LOG_DIR.mkdir(exist_ok=True)


def read_pid_file() -> Optional[int]:
    """
    Read PID from the PID file.
    
    Returns:
        int: PID if file exists and contains valid PID, None otherwise
    """
    try:
        if not PID_FILE_PATH.exists():
            logger.debug(f"PID file {PID_FILE_PATH} does not exist")
            return None
        
        with open(PID_FILE_PATH, 'r') as f:
            pid_str = f.read().strip()
        
        if not pid_str:
            logger.warning(f"PID file {PID_FILE_PATH} is empty")
            return None
        
        pid = int(pid_str)
        logger.debug(f"Read PID {pid} from {PID_FILE_PATH}")
        return pid
        
    except (ValueError, IOError) as e:
        logger.warning(f"Error reading PID file {PID_FILE_PATH}: {e}")
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
        # Check if process exists
        if not psutil.pid_exists(pid):
            logger.debug(f"Process {pid} does not exist")
            return False
        
        # Get process info
        process = psutil.Process(pid)
        
        # Check if process is still running
        if not process.is_running():
            logger.debug(f"Process {pid} is not running")
            return False
        
        # Check command line to verify it's main_app.py
        cmdline = process.cmdline()
        if not cmdline:
            logger.debug(f"Process {pid} has no command line")
            return False
        
        # Look for main_app.py in the command line
        cmdline_str = ' '.join(cmdline)
        if 'main_app.py' not in cmdline_str:
            logger.debug(f"Process {pid} is not main_app.py: {cmdline_str}")
            return False
        
        logger.debug(f"Process {pid} is running main_app.py: {cmdline_str}")
        return True
        
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
        logger.debug(f"Error checking process {pid}: {e}")
        return False


def is_main_app_running() -> Tuple[bool, Optional[int]]:
    """
    Check if main_app.py is currently running.
    
    Returns:
        Tuple[bool, Optional[int]]: (is_running, pid)
    """
    # First check PID file
    pid = read_pid_file()
    if pid is None:
        logger.debug("No valid PID found in PID file")
        return False, None
    
    # Check if process is actually running
    if is_process_running(pid):
        logger.debug(f"main_app.py is running with PID {pid}")
        return True, pid
    else:
        logger.debug(f"PID {pid} from file is stale or not main_app.py")
        # Clean up stale PID file
        try:
            PID_FILE_PATH.unlink(missing_ok=True)
            logger.debug(f"Removed stale PID file {PID_FILE_PATH}")
        except Exception as e:
            logger.warning(f"Failed to remove stale PID file: {e}")
        return False, None


def start_main_app() -> bool:
    """
    Start main_app.py in the background.
    
    Returns:
        bool: True if started successfully, False otherwise
    """
    try:
        logger.info("🚀 Starting main_app.py...")
        
        # Construct command
        cmd = [PYTHON_INTERPRETER, str(MAIN_APP_PATH)]
        
        # Start process in background
        process = subprocess.Popen(
            cmd,
            cwd=str(project_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=True  # Detach from parent
        )
        
        # Give it a moment to start
        time.sleep(2)
        
        # Check if process is still running
        if process.poll() is None:
            logger.info(f"✅ Successfully started main_app.py with PID {process.pid}")
            return True
        else:
            # Process exited immediately
            stdout, stderr = process.communicate()
            logger.error(f"❌ main_app.py exited immediately with code {process.returncode}")
            if stdout:
                logger.error(f"STDOUT: {stdout.decode()}")
            if stderr:
                logger.error(f"STDERR: {stderr.decode()}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Failed to start main_app.py: {e}")
        return False


def send_email_alert(subject: str, body: str) -> bool:
    """
    Send email alert using SMTP.
    
    Args:
        subject: Email subject
        body: Email body
    
    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        # Import configuration
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
        from config import get_config
        config = get_config()
        
        # Get SMTP configuration from centralized config
        smtp_server = config.smtp_server
        smtp_port = config.smtp_port
        smtp_username = config.smtp_username
        smtp_password = config.smtp_password
        from_email = config.alert_email_from
        to_email = config.alert_email_to
        
        # Check if email is configured
        if not all([smtp_server, smtp_username, smtp_password, from_email, to_email]):
            logger.debug("Email alerts not configured (missing SMTP environment variables)")
            return False
        
        # Create message
        msg = email.message.EmailMessage()
        msg['Subject'] = f"[DCA Bot] {subject}"
        msg['From'] = from_email
        msg['To'] = to_email
        msg.set_content(f"""
DCA Trading Bot Watchdog Alert

{body}

Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}
Server: {os.uname().nodename if hasattr(os, 'uname') else 'Unknown'}

This is an automated message from the DCA Trading Bot watchdog script.
""")
        
        # Send email
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        
        logger.info(f"📧 Email alert sent: {subject}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to send email alert: {e}")
        return False


def cleanup_stale_resources():
    """
    Clean up any stale resources that might prevent restart.
    """
    try:
        # Remove stale PID file if it exists
        if PID_FILE_PATH.exists():
            PID_FILE_PATH.unlink()
            logger.debug(f"Removed stale PID file {PID_FILE_PATH}")
        
        # Could add other cleanup tasks here (e.g., stale lock files)
        
    except Exception as e:
        logger.warning(f"Error during cleanup: {e}")


def main():
    """
    Main watchdog logic.
    """
    logger.info("=" * 70)
    logger.info("DCA TRADING BOT WATCHDOG STARTED")
    logger.info("=" * 70)
    
    try:
        # Check if main_app.py is running
        is_running, pid = is_main_app_running()
        
        if is_running:
            logger.info(f"✅ main_app.py is running (PID: {pid})")
            logger.info("🔍 No action needed - application is healthy")
        else:
            logger.warning("⚠️ main_app.py is not running")
            
            # Clean up any stale resources
            cleanup_stale_resources()
            
            # Attempt to restart
            logger.info("🔄 Attempting to restart main_app.py...")
            
            if start_main_app():
                logger.info("✅ Successfully restarted main_app.py")
                
                # Send success email alert
                send_email_alert(
                    "Main App Restarted",
                    "The DCA Trading Bot main application was not running and has been successfully restarted."
                )
            else:
                logger.error("❌ Failed to restart main_app.py")
                
                # Send failure email alert
                send_email_alert(
                    "CRITICAL: Failed to Restart Main App",
                    "The DCA Trading Bot main application was not running and failed to restart. Manual intervention required."
                )
                
                # Exit with error code for cron monitoring
                sys.exit(1)
    
    except Exception as e:
        logger.error(f"❌ Watchdog error: {e}")
        
        # Send critical error email
        send_email_alert(
            "CRITICAL: Watchdog Error",
            f"The DCA Trading Bot watchdog script encountered an error: {e}"
        )
        
        sys.exit(1)
    
    finally:
        logger.info("=" * 70)
        logger.info("DCA TRADING BOT WATCHDOG COMPLETED")
        logger.info("=" * 70)


if __name__ == "__main__":
    main() 