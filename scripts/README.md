# DCA Trading Bot Scripts

This directory contains utility scripts for managing the DCA trading bot.

## Asset Management Scripts

### add_asset.py

Adds new cryptocurrency assets to the `dca_assets` table.

**Usage:**
```bash
# Add a single asset as enabled
python scripts/add_asset.py BTC/USD --enabled

# Add multiple assets as enabled
python scripts/add_asset.py BTC/USD,ETH/USD,SOL/USD --enabled

# Add assets as disabled (default)
python scripts/add_asset.py DOGE/USD,SHIB/USD
```

**Features:**
- Validates asset symbol format (BASE/QUOTE)
- Prevents duplicate entries
- Uses database defaults for configuration values
- Supports batch addition of multiple assets
- Comprehensive error handling and logging

### asset_caretaker.py

Performs maintenance tasks to ensure system consistency.

**Usage:**
```bash
# Run maintenance (creates missing cycles)
python scripts/asset_caretaker.py

# Dry run (show what would be done)
python scripts/asset_caretaker.py --dry-run
```

**Features:**
- Finds enabled assets without cycles
- Creates 'watching' cycles for assets that need them
- Dry-run mode for safe testing
- Detailed logging and reporting
- Can be scheduled via cron for automated maintenance

**Recommended Cron Schedule:**
```bash
# Run every 30 minutes
*/30 * * * * cd /path/to/dcaTrader && python scripts/asset_caretaker.py >> logs/caretaker.log 2>&1
```

## App Control Scripts

### app_control.py

Provides elegant control over the main trading application with maintenance mode support.

**Usage:**
```bash
# Stop the app (enables maintenance mode)
python scripts/app_control.py stop

# Start the app (disables maintenance mode)
python scripts/app_control.py start

# Restart the app (useful for applying asset changes)
python scripts/app_control.py restart

# Check current status
python scripts/app_control.py status

# Toggle maintenance mode
python scripts/app_control.py maintenance on
python scripts/app_control.py maintenance off
```

**Features:**
- Graceful shutdown with SIGTERM → SIGKILL fallback
- Maintenance mode prevents watchdog interference
- Comprehensive status reporting
- Safe timeout handling
- Process validation and uptime tracking

**Maintenance Mode:**
When enabled, the watchdog will not restart the main app, allowing for manual control and maintenance operations. Perfect for:
- Applying configuration changes
- Adding/removing assets
- Debugging issues
- Manual testing

### watchdog.py

Monitors and restarts the main trading application.

**Usage:**
```bash
# Start watchdog
python scripts/watchdog.py

# Run in background
nohup python scripts/watchdog.py &

# Add to crontab for automatic monitoring (every 5 minutes)
*/5 * * * * cd /path/to/dcaTrader && python scripts/watchdog.py >> logs/watchdog.log 2>&1
```

**Features:**
- Detects if main_app.py is running
- Automatically restarts if stopped (unless in maintenance mode)
- Email notifications for failures
- Comprehensive logging
- Resource cleanup
- Respects maintenance mode from app_control.py

## Workflow for Adding New Assets

1. **Add the asset to the database:**
   ```bash
   python scripts/add_asset.py NEWCOIN/USD --enabled
   ```

2. **Ensure cycles are created:**
   ```bash
   python scripts/asset_caretaker.py
   ```

3. **Restart the main app** (to pick up new WebSocket subscriptions):
   ```bash
   python scripts/app_control.py restart
   ```

## Workflow for Maintenance Operations

1. **Stop the app and enable maintenance mode:**
   ```bash
   python scripts/app_control.py stop
   ```

2. **Perform maintenance tasks** (database changes, configuration updates, etc.)

3. **Start the app and disable maintenance mode:**
   ```bash
   python scripts/app_control.py start
   ```

**Alternative:** Use `maintenance` command for temporary maintenance without stopping the app:
```bash
python scripts/app_control.py maintenance on
# Perform maintenance...
python scripts/app_control.py maintenance off
```

## Notes

- All scripts use the same logging configuration as the main application
- Scripts automatically add the `src/` directory to the Python path
- Database configuration is read from environment variables
- All scripts include comprehensive error handling and validation 