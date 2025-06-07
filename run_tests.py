#!/usr/bin/env python3
"""
Test runner script for the DCA Trading Bot.
Provides convenient commands for running different types of tests.
"""

import sys
import subprocess
import os
import logging
from pathlib import Path

def setup_test_logging():
    """Set up logging to output to logs/test.log file."""
    # Ensure logs directory exists
    logs_dir = Path('logs')
    logs_dir.mkdir(exist_ok=True)
    
    # Configure logging
    log_file = logs_dir / 'test.log'
    
    # Set up logging configuration
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a'),  # Append to test.log
            logging.StreamHandler(sys.stdout)         # Also output to console
        ]
    )
    
    logger = logging.getLogger('run_tests')
    logger.info("="*60)
    logger.info("🧪 Test Runner Started")
    logger.info("="*60)
    
    return logger

def load_test_environment():
    """Load test environment variables from .env.test file."""
    env_test_path = Path('.env.test')
    
    if not env_test_path.exists():
        print("❌ ERROR: .env.test file not found!")
        print("Please create .env.test with test database and Alpaca credentials.")
        print("This ensures tests don't accidentally use production environment.")
        sys.exit(1)
    
    print("🔧 Loading test environment from .env.test...")
    
    # Load environment variables from .env.test
    with open(env_test_path, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                # Remove quotes if present
                value = value.strip('"\'')
                os.environ[key] = value
    
    # Verify critical test environment variables are set
    required_vars = [
        'APCA_API_KEY_ID', 'APCA_API_SECRET_KEY', 'APCA_API_BASE_URL',
        'DB_HOST', 'DB_USER', 'DB_PASSWORD', 'DB_NAME'
    ]
    
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"❌ ERROR: Missing required test environment variables: {missing_vars}")
        sys.exit(1)
    
    # Verify we're using test/paper environment
    if 'paper-api.alpaca.markets' not in os.environ.get('APCA_API_BASE_URL', ''):
        print("❌ ERROR: Test environment must use Alpaca paper trading!")
        print(f"Current APCA_API_BASE_URL: {os.environ.get('APCA_API_BASE_URL')}")
        sys.exit(1)
    
    if 'test' not in os.environ.get('DB_NAME', '').lower():
        print("⚠️ WARNING: Database name should contain 'test' for safety")
        print(f"Current DB_NAME: {os.environ.get('DB_NAME')}")
    
    print(f"✅ Test environment loaded:")
    print(f"   • Alpaca: {os.environ.get('APCA_API_BASE_URL')}")
    print(f"   • Database: {os.environ.get('DB_NAME')} on {os.environ.get('DB_HOST')}")

def run_command(cmd, logger):
    """Run a command and return the exit code."""
    cmd_str = ' '.join(cmd)
    print(f"Running: {cmd_str}")
    logger.info(f"Executing command: {cmd_str}")
    
    result = subprocess.run(cmd, env=os.environ, capture_output=True, text=True)
    
    # Log the output
    if result.stdout:
        logger.info(f"STDOUT:\n{result.stdout}")
    if result.stderr:
        logger.error(f"STDERR:\n{result.stderr}")
    
    logger.info(f"Command completed with exit code: {result.returncode}")
    
    return result.returncode

def main():
    """Main test runner function."""
    if len(sys.argv) < 2:
        print("Usage: python run_tests.py [command]")
        print("\nAvailable commands:")
        print("  all          - Run all tests")
        print("  unit         - Run only unit tests")
        print("  coverage     - Run tests with coverage report")
        print("  html         - Run tests with HTML coverage report")
        print("  integration  - Run integration tests")
        print("  fast         - Run tests without coverage")
        print("  verbose      - Run tests with verbose output")
        return 1

    # Set up test logging
    logger = setup_test_logging()
    
    # Load test environment before running any tests
    load_test_environment()
    
    command = sys.argv[1].lower()
    logger.info(f"Running command: {command}")

    # Base pytest command
    base_cmd = [sys.executable, "-m", "pytest"]
    
    if command == "all":
        return run_command(base_cmd + ["-v"], logger)
    
    elif command == "unit":
        return run_command(base_cmd + ["-v", "-m", "unit"], logger)
    
    elif command == "coverage":
        return run_command(base_cmd + [
            "--cov=src", 
            "--cov-report=term-missing",
            "--cov-report=html",
            "-v"
        ], logger)
    
    elif command == "html":
        exit_code = run_command(base_cmd + [
            "--cov=src", 
            "--cov-report=html",
            "-v"
        ], logger)
        if exit_code == 0:
            print("\nHTML coverage report generated in htmlcov/index.html")
            logger.info("HTML coverage report generated in htmlcov/index.html")
        return exit_code
    
    elif command == "integration":
        return run_command(base_cmd + ["-v", "-m", "integration"], logger)
    
    elif command == "fast":
        return run_command(base_cmd + ["-v", "--tb=short"], logger)
    
    elif command == "verbose":
        return run_command(base_cmd + ["-vv", "--tb=long"], logger)
    
    else:
        print(f"Unknown command: {command}")
        logger.error(f"Unknown command: {command}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    if exit_code == 0:
        logging.getLogger('run_tests').info("🎉 Test runner completed successfully")
    else:
        logging.getLogger('run_tests').error(f"❌ Test runner failed with exit code {exit_code}")
    sys.exit(exit_code) 