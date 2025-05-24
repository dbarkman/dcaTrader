#!/usr/bin/env python3
"""
Test runner script for the DCA Trading Bot.
Provides convenient commands for running different types of tests.
"""

import sys
import subprocess
from pathlib import Path

def run_command(cmd):
    """Run a command and return the exit code."""
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd).returncode

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

    command = sys.argv[1].lower()
    
    # Base pytest command
    base_cmd = [sys.executable, "-m", "pytest", "tests/"]
    
    if command == "all":
        return run_command(base_cmd + ["-v"])
    
    elif command == "unit":
        return run_command(base_cmd + ["-v", "-m", "unit"])
    
    elif command == "coverage":
        return run_command(base_cmd + [
            "--cov=src", 
            "--cov-report=term-missing",
            "--cov-report=html",
            "-v"
        ])
    
    elif command == "html":
        exit_code = run_command(base_cmd + [
            "--cov=src", 
            "--cov-report=html",
            "-v"
        ])
        if exit_code == 0:
            print("\nHTML coverage report generated in htmlcov/index.html")
        return exit_code
    
    elif command == "integration":
        return run_command(base_cmd + ["-v", "-m", "integration"])
    
    elif command == "fast":
        return run_command(base_cmd + ["-v", "--tb=short"])
    
    elif command == "verbose":
        return run_command(base_cmd + ["-vv", "--tb=long"])
    
    else:
        print(f"Unknown command: {command}")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 