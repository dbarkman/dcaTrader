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

## Other Scripts

### watchdog.py

Monitors and restarts the main trading application.

**Usage:**
```bash
# Start watchdog
python scripts/watchdog.py

# Run in background
nohup python scripts/watchdog.py &
```

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
   pkill -f "python.*main_app.py"
   python src/main_app.py &
   ```

## Notes

- All scripts use the same logging configuration as the main application
- Scripts automatically add the `src/` directory to the Python path
- Database configuration is read from environment variables
- All scripts include comprehensive error handling and validation 