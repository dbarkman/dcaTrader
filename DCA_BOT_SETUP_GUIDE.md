# DCA Trading Bot - Setup Guide

This guide covers setting up and running the DCA Trading Bot for both normal trading operations and backtesting.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Initial Setup](#initial-setup)
3. [Normal DCA Operations](#normal-dca-operations)
4. [Backtesting Operations](#backtesting-operations)
5. [Configuration Reference](#configuration-reference)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### System Requirements
- **Python 3.8+**
- **MySQL 5.7+ or MariaDB 10.3+**
- **Linux/macOS** (recommended) or Windows with WSL
- **Internet connection** for Alpaca API and Discord notifications

### Required Accounts
- **Alpaca Trading Account** (https://alpaca.markets)
  - Paper trading account (recommended for testing)
  - Live trading account (for production)
- **Discord Webhook** (optional, for notifications)
- **Email SMTP** (optional, for alerts)

---

## Initial Setup

### 1. Clone and Install Dependencies

```bash
# Clone the repository
git clone <your-repo-url>
cd dcaTrader

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Database Setup

```bash
# Connect to MySQL/MariaDB
mysql -u root -p

# Create database and user
CREATE DATABASE dcaTraderBot;
CREATE USER 'dca_user'@'localhost' IDENTIFIED BY 'your_secure_password';
GRANT ALL PRIVILEGES ON dcaTraderBot.* TO 'dca_user'@'localhost';
FLUSH PRIVILEGES;
EXIT;

# Import database schema
mysql -u dca_user -p dcaTraderBot < sql/schema.sql
```

### 3. Environment Configuration

```bash
# Copy example environment file
cp env.example .env

# Edit .env with your credentials
nano .env
```

**Required Environment Variables:**
```bash
# Alpaca API Credentials
APCA_API_KEY_ID="your_alpaca_api_key"
APCA_API_SECRET_KEY="your_alpaca_api_secret"
APCA_API_BASE_URL="https://paper-api.alpaca.markets"  # For paper trading

# Database Credentials
DB_HOST="localhost"
DB_USER="dca_user"
DB_PASSWORD="your_secure_password"
DB_NAME="dcaTraderBot"
DB_PORT="3306"

# Optional: Discord Notifications
DISCORD_WEBHOOK_URL="https://discord.com/api/webhooks/your_webhook_url"
DISCORD_USER_ID="your_discord_user_id"  # For mentions
DISCORD_NOTIFICATIONS_ENABLED=true
DISCORD_TRADING_ALERTS_ENABLED=true

# Optional: Email Alerts
SMTP_SERVER="smtp.gmail.com"
SMTP_PORT=587
SMTP_USERNAME="your_email@gmail.com"
SMTP_PASSWORD="your_app_password"
ALERT_EMAIL_FROM="your_email@gmail.com"
ALERT_EMAIL_TO="alerts@yourdomain.com"
```

### 4. Add Trading Assets

```bash
# Add cryptocurrency assets for trading
python scripts/add_asset.py BTC/USD,ETH/USD,SOL/USD --enabled

# Create initial cycles for assets
python scripts/asset_caretaker.py
```

---

## Normal DCA Operations

### Starting the Bot

#### Method 1: Direct Start (Foreground)
```bash
# Activate virtual environment
source venv/bin/activate

# Start the main trading application
python src/main_app.py
```

#### Method 2: Background with App Control (Recommended)
```bash
# Start the bot in the background
python scripts/app_control.py start

# Check status
python scripts/app_control.py status

# Stop the bot
python scripts/app_control.py stop

# Restart the bot
python scripts/app_control.py restart
```

#### Method 3: Production Setup with Watchdog
```bash
# Start the watchdog for automatic monitoring
nohup python scripts/watchdog.py &

# Or add to crontab for scheduled monitoring
crontab -e
# Add this line:
*/5 * * * * cd /path/to/dcaTrader && python scripts/watchdog.py >> logs/watchdog.log 2>&1
```

### Managing Assets

#### Adding New Assets
```bash
# Add new assets
python scripts/add_asset.py AVAX/USD,LINK/USD --enabled

# Create cycles for new assets
python scripts/asset_caretaker.py

# Restart bot to subscribe to new WebSocket feeds
python scripts/app_control.py restart
```

#### Checking Asset Status
```bash
# View active cycles
python reporting/analyze_pl.py

# Check specific cycle details
python reporting/check_cycle.py <cycle_id>
```

### Maintenance Operations

#### Safe Maintenance Mode
```bash
# Enable maintenance mode (prevents watchdog restarts)
python scripts/app_control.py maintenance on

# Perform maintenance operations...

# Disable maintenance mode
python scripts/app_control.py maintenance off
```

#### System Health Monitoring
```bash
# Check overall system status
python scripts/status_reporter.py

# Monitor order consistency
python scripts/consistency_checker.py

# Clean up old orders
python scripts/order_manager.py

# Manage cooldown cycles
python scripts/cooldown_manager.py
```

### Log Monitoring

```bash
# Follow main application logs
tail -f logs/main.log

# Check caretaker logs
tail -f logs/caretakers.log

# View all logs
ls -la logs/
```

---

## Backtesting Operations

### Prerequisites for Backtesting

#### 1. Historical Data Setup
```bash
# Fetch historical 1-minute bars for backtesting
python scripts/fetch_historical_bars.py --symbol BTC/USD --days 30

# Verify data availability
mysql -u dca_user -p dcaTraderBot -e "SELECT COUNT(*) FROM historical_1min_bars WHERE symbol = 'BTC/USD';"
```

#### 2. Test Asset Configuration
```bash
# Add assets for backtesting if not already present
python scripts/add_asset.py BTC/USD --enabled

# Ensure test cycles exist
python scripts/asset_caretaker.py
```

### Running Backtests

#### Basic Backtest
```bash
# Run backtest for BTC/USD for one day
python scripts/run_backtest.py \
    --symbol "BTC/USD" \
    --start-date "2024-01-01" \
    --end-date "2024-01-02"
```

#### Advanced Backtest Options
```bash
# Extended backtest with custom parameters
python scripts/run_backtest.py \
    --symbol "BTC/USD" \
    --start-date "2024-01-01" \
    --end-date "2024-01-31" \
    --starting-cash 10000 \
    --log-level DEBUG \
    --output-file backtest_results.json
```

#### Multi-Asset Backtesting
```bash
# Backtest multiple assets sequentially
for symbol in "BTC/USD" "ETH/USD" "SOL/USD"; do
    echo "Backtesting $symbol..."
    python scripts/run_backtest.py \
        --symbol "$symbol" \
        --start-date "2024-01-01" \
        --end-date "2024-01-07" \
        --starting-cash 10000
    echo "Completed $symbol"
done
```

### Interpreting Backtest Results

The backtesting engine provides comprehensive performance metrics:

- **Total P/L**: Realized + unrealized profit/loss
- **Win Rate**: Percentage of profitable trades
- **Max Drawdown**: Largest peak-to-trough decline
- **Trade Statistics**: Number of trades, safety orders usage
- **Portfolio Value**: Final portfolio value vs. starting cash

### Backtesting Best Practices

1. **Data Quality**: Ensure sufficient historical data
   ```bash
   # Check data coverage
   python scripts/fetch_historical_bars.py --symbol BTC/USD --days 90
   ```

2. **Realistic Parameters**: Use production-like asset configurations

3. **Multiple Timeframes**: Test different market conditions
   ```bash
   # Bull market period
   python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2023-10-01" --end-date "2023-12-31"
   
   # Bear market period
   python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2022-05-01" --end-date "2022-07-31"
   ```

4. **Strategy Optimization**: Test different configurations in `dca_assets` table

---

## Configuration Reference

### Asset Configuration (dca_assets table)

| Parameter | Description | Default | Example |
|-----------|-------------|---------|---------|
| `base_order_amount` | Initial order size | 20.00 | 50.00 |
| `safety_order_amount` | Safety order size | 20.00 | 100.00 |
| `max_safety_orders` | Max safety orders | 5 | 3 |
| `safety_order_deviation` | Price drop % for safety orders | 2.0% | 1.5% |
| `take_profit_percent` | Profit target | 1.5% | 2.0% |
| `ttp_enabled` | Trailing take profit | true | false |
| `ttp_deviation_percent` | TTP deviation | 0.25% | 0.5% |
| `cooldown_period` | Cooldown between cycles (seconds) | 300 | 600 |

### Environment Variables

#### Core Configuration
```bash
# Trading
ORDER_COOLDOWN_SECONDS=5          # Prevent duplicate orders
STALE_ORDER_THRESHOLD_MINUTES=5   # Cancel stale orders
TESTING_MODE=false                # Aggressive pricing for tests
DRY_RUN=false                     # No actual orders placed

# Logging
LOG_LEVEL=INFO                    # DEBUG, INFO, WARNING, ERROR
LOG_DIR=logs                      # Log directory
LOG_MAX_BYTES=10485760           # 10MB log rotation
LOG_BACKUP_COUNT=5               # Keep 5 backup files
```

#### Paper vs. Live Trading
```bash
# Paper Trading (Safe for testing)
APCA_API_BASE_URL="https://paper-api.alpaca.markets"

# Live Trading (Real money - be careful!)
APCA_API_BASE_URL="https://api.alpaca.markets"
```

---

## Troubleshooting

### Common Issues

#### 1. Database Connection Errors
```bash
# Test database connection
python -c "from src.utils.db_utils import get_db_connection; print('DB OK' if get_db_connection() else 'DB FAIL')"

# Check MySQL service
sudo systemctl status mysql  # or mariadb
```

#### 2. Alpaca API Issues
```bash
# Test Alpaca connection
python -c "from src.utils.alpaca_client_rest import get_trading_client; print('Alpaca OK' if get_trading_client() else 'Alpaca FAIL')"

# Check API credentials
echo $APCA_API_KEY_ID
echo $APCA_API_BASE_URL
```

#### 3. Missing Dependencies
```bash
# Reinstall requirements
pip install -r requirements.txt

# Update specific packages
pip install --upgrade alpaca-trade-api discord-webhook
```

#### 4. WebSocket Connection Issues
```bash
# Check network connectivity
ping api.alpaca.markets

# Review main app logs
tail -f logs/main.log | grep -i websocket
```

#### 5. Discord Notifications Not Working
```bash
# Test Discord configuration
python -c "from src.utils.discord_notifications import verify_discord_configuration; verify_discord_configuration()"

# Check webhook URL
curl -X POST "$DISCORD_WEBHOOK_URL" -H "Content-Type: application/json" -d '{"content": "Test message"}'
```

### Log Analysis

#### Finding Issues in Logs
```bash
# Error patterns
grep -i error logs/main.log | tail -10

# Trading activity
grep -i "order\|fill\|profit" logs/main.log | tail -20

# WebSocket issues
grep -i "websocket\|connection" logs/main.log | tail -10
```

#### Log Files Overview
- `logs/main.log` - Main application logs (rotated daily)
- `logs/caretakers.log` - Maintenance script logs
- `logs/watchdog.log` - Watchdog monitoring logs
- `logs/consistency_checker.log` - System consistency checks

### Performance Monitoring

#### System Resources
```bash
# Check Python processes
ps aux | grep python

# Memory usage
free -h

# Disk space
df -h
```

#### Database Performance
```bash
# Check active connections
mysql -u dca_user -p dcaTraderBot -e "SHOW PROCESSLIST;"

# Table sizes
mysql -u dca_user -p dcaTraderBot -e "SELECT table_name, ROUND(((data_length + index_length) / 1024 / 1024), 2) AS 'Size (MB)' FROM information_schema.tables WHERE table_schema = 'dcaTraderBot';"
```

### Getting Help

1. **Check Logs**: Always start with `logs/main.log`
2. **Discord Notifications**: Monitor for system alerts
3. **Email Alerts**: Configure for critical errors
4. **Status Reports**: Use `scripts/status_reporter.py` for health checks
5. **GitHub Issues**: Report bugs with log excerpts and configuration details

---

## Security Best Practices

1. **API Keys**: Never commit API keys to version control
2. **Database**: Use strong passwords and limit user privileges
3. **Network**: Consider firewall rules for database access
4. **Monitoring**: Enable Discord/email alerts for security events
5. **Backups**: Regular database backups for configuration and trade history

---

## Next Steps

After successful setup:

1. **Start Small**: Begin with paper trading and small amounts
2. **Monitor Closely**: Watch logs and notifications for the first few days
3. **Optimize Settings**: Adjust asset configurations based on performance
4. **Scale Gradually**: Add more assets and increase position sizes over time
5. **Regular Maintenance**: Schedule periodic system health checks

For additional help, refer to the scripts documentation in `scripts/README.md` and the analysis tools in the `reporting/` directory. 