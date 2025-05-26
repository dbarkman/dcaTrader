# Phase 13: Watchdog Script - Implementation Summary

## Overview
Phase 13 implements a comprehensive watchdog script that monitors the main WebSocket application (`main_app.py`) and automatically restarts it if needed. This ensures the DCA trading bot stays operational 24/7 with minimal manual intervention.

## Files Created/Modified

### 1. `scripts/watchdog.py` (NEW)
- **Purpose**: Main watchdog script that monitors and restarts `main_app.py`
- **Features**:
  - PID file-based process monitoring using `psutil`
  - Automatic restart with proper environment
  - Email alerts for failures and restarts (optional)
  - Comprehensive logging to `logs/watchdog.log`
  - Graceful error handling
  - Stale resource cleanup

### 2. `src/main_app.py` (MODIFIED)
- **Added**: PID file management functions
  - `create_pid_file()`: Creates PID file on startup
  - `remove_pid_file()`: Removes PID file on clean shutdown
- **Modified**: Main function to create PID file on startup and remove it on shutdown
- **PID File Location**: `main_app.pid` in project root

### 3. `tests/test_watchdog.py` (NEW)
- **Purpose**: Comprehensive unit tests for watchdog functionality
- **Coverage**: 27 test cases covering:
  - PID file reading and validation
  - Process monitoring and verification
  - Email alert functionality
  - Main app startup logic
  - Error handling and edge cases

### 4. `integration_test.py` (MODIFIED)
- **Added**: `test_phase13_watchdog_restarts_app()` function
- **Tests**: Two scenarios:
  1. main_app.py not running → watchdog should start it
  2. main_app.py already running → watchdog should detect it and take no action
- **Verification**: PID file creation, process verification, cleanup

### 5. `scripts/cron_example.txt` (NEW)
- **Purpose**: Example cron configuration for production deployment
- **Contains**: Various cron schedule examples and setup instructions

## Key Features Implemented

### Process Monitoring
- **PID File Based**: Uses `main_app.pid` file for process tracking
- **Process Verification**: Confirms process exists and is actually `main_app.py`
- **Stale Detection**: Automatically detects and cleans up stale PID files
- **Command Line Validation**: Verifies process is running the correct script

### Automatic Restart
- **Background Startup**: Starts `main_app.py` detached from watchdog process
- **Environment Preservation**: Maintains proper working directory and Python path
- **Startup Verification**: Confirms process started successfully before reporting success
- **Error Handling**: Captures and logs startup failures with detailed error messages

### Email Alerting (Optional)
- **SMTP Support**: Configurable email alerts via environment variables
- **Alert Types**:
  - Successful restart notifications
  - Critical failure alerts
  - Watchdog error notifications
- **Configuration**: Uses environment variables for SMTP settings
- **Graceful Degradation**: Works without email configuration

### Logging
- **Comprehensive Logging**: All actions logged to `logs/watchdog.log`
- **Structured Output**: Clear, emoji-enhanced log messages
- **Debug Information**: Detailed process information and error traces
- **Console + File**: Logs to both console and file simultaneously

### Error Handling
- **Graceful Failures**: Handles missing files, permission errors, network issues
- **Resource Cleanup**: Ensures stale resources are cleaned up
- **Exit Codes**: Proper exit codes for cron monitoring
- **Exception Safety**: All operations wrapped in try-catch blocks

## Environment Variables (Optional)
```bash
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your-email@gmail.com
SMTP_PASSWORD=your-app-password
ALERT_EMAIL_FROM=dca-bot@yourdomain.com
ALERT_EMAIL_TO=admin@yourdomain.com
```

## Usage Examples

### Manual Execution
```bash
# Run watchdog once
python scripts/watchdog.py

# Check logs
tail -f logs/watchdog.log
```

### Cron Setup (Production)
```bash
# Edit crontab
crontab -e

# Add line to run every 3 minutes
*/3 * * * * cd /home/david/dcaTrader && python scripts/watchdog.py >> logs/cron.log 2>&1
```

## Testing Results

### Unit Tests
- **Total Tests**: 27 test cases
- **Coverage**: All major functions and error conditions
- **Status**: ✅ All tests passing

### Integration Tests
- **Scenarios Tested**:
  1. App not running → restart successful
  2. App already running → detection successful
- **Verification**: PID file management, process monitoring, cleanup
- **Status**: ✅ Integration test passing

### Manual Testing
- **Restart Scenario**: ✅ Successfully detects missing app and restarts it
- **Detection Scenario**: ✅ Successfully detects running app and takes no action
- **PID Management**: ✅ Creates and cleans up PID files correctly
- **Process Verification**: ✅ Correctly identifies main_app.py processes

## Production Deployment

### Recommended Cron Schedule
```bash
# Every 3 minutes (recommended for production)
*/3 * * * * cd /path/to/dcaTrader && python scripts/watchdog.py
```

### Security Considerations
- Run watchdog as same user as main application
- Ensure proper file permissions on PID file location
- Secure SMTP credentials if using email alerts
- Monitor watchdog logs for security events

### Monitoring
- **Log Files**: Monitor `logs/watchdog.log` for watchdog activity
- **Cron Logs**: Monitor cron execution logs
- **Email Alerts**: Configure email notifications for critical events
- **Process Monitoring**: Use system monitoring tools to track both processes

## Dependencies Added
- **psutil**: For robust process monitoring and management
  ```bash
  pip install psutil
  ```

## Benefits
1. **24/7 Uptime**: Ensures trading bot stays operational
2. **Automatic Recovery**: No manual intervention needed for restarts
3. **Monitoring**: Comprehensive logging and optional email alerts
4. **Reliability**: Robust error handling and edge case management
5. **Production Ready**: Designed for cron-based deployment
6. **Maintainable**: Well-tested with comprehensive unit and integration tests

## Integration with Existing System
- **Seamless Integration**: Works with existing main_app.py without breaking changes
- **Logging Consistency**: Uses same logging format as rest of application
- **Error Handling**: Follows same error handling patterns
- **Testing Framework**: Integrates with existing pytest test suite

Phase 13 successfully implements a production-ready watchdog system that ensures the DCA trading bot maintains high availability and automatically recovers from failures. 