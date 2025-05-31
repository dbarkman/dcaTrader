# DCA Trading Bot - Hourly Status Reporter Setup

## Overview
The `status_reporter.py` script sends hourly Discord notifications with your portfolio performance metrics.

## Cron Setup

To run the status reporter every hour, add this line to your crontab:

```bash
# Edit your crontab
crontab -e

# Add this line to run every hour at the top of the hour
0 * * * * cd /home/david/dcaTrader && python scripts/status_reporter.py >> logs/status_reporter.log 2>&1
```

## Alternative Schedules

```bash
# Every 2 hours
0 */2 * * * cd /home/david/dcaTrader && python scripts/status_reporter.py >> logs/status_reporter.log 2>&1

# Every 4 hours  
0 */4 * * * cd /home/david/dcaTrader && python scripts/status_reporter.py >> logs/status_reporter.log 2>&1

# Daily at 9 AM
0 9 * * * cd /home/david/dcaTrader && python scripts/status_reporter.py >> logs/status_reporter.log 2>&1

# Every 30 minutes (for testing)
*/30 * * * * cd /home/david/dcaTrader && python scripts/status_reporter.py >> logs/status_reporter.log 2>&1
```

## What You'll Get

Each hour, you'll receive a Discord notification with:

- **Total Realized P/L**: Profit/loss from completed trading cycles
- **Total Amount Invested**: Historical + current investment amounts  
- **Currently Invested**: Money tied up in active positions
- **ROI**: Return on investment percentage
- **Active Cycles**: Number of currently active trading cycles
- **Completed Cycles**: Number of completed trading cycles

## Log Files

The status reporter logs to:
- **Console output**: `logs/status_reporter.log` (from cron)
- **Application logs**: Standard application logging

## Testing

Test the script manually:
```bash
cd /home/david/dcaTrader
python scripts/status_reporter.py
```

Check your Discord channel for the status notification!

## Troubleshooting

If notifications stop working:

1. Check if Discord webhook is still valid
2. Verify `.env` configuration:
   ```
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
   DISCORD_NOTIFICATIONS_ENABLED=true
   DISCORD_TRADING_ALERTS_ENABLED=true
   ```
3. Check cron logs: `grep CRON /var/log/syslog`
4. Check status reporter logs: `tail -f logs/status_reporter.log` 