# Discord Bot Setup Guide

This guide will help you set up the DCA Trading Bot Discord bot to receive and respond to commands from Discord.

## 🎯 Features

The Discord bot provides two-way communication with your trading system:

- **!appStatus** - Get system status (main app running, PID, uptime, maintenance mode)
- **!status** - Execute portfolio status report (sends detailed portfolio metrics to Discord)
- **!help** - Show available commands

## 📋 Prerequisites

1. **Discord Account** - You need a Discord account
2. **Discord Server** - You need admin access to a Discord server
3. **Running DCA Trading Bot** - Your main trading bot should be set up

## 🔧 Step 1: Create Discord Application & Bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. Click **"New Application"**
3. Name your application (e.g., "DCA Trading Bot")
4. Go to the **"Bot"** section in the left sidebar
5. Click **"Add Bot"**
6. **Copy the Bot Token** - You'll need this for your `.env` file

## 🔑 Step 2: Configure Bot Permissions

1. In the Bot section, scroll down to **"Privileged Gateway Intents"**
2. Enable **"Message Content Intent"** (required for reading commands)
3. Go to the **"OAuth2 > URL Generator"** section
4. Select scopes:
   - ✅ `bot`
   - ✅ `applications.commands`
5. Select bot permissions:
   - ✅ `Send Messages`
   - ✅ `Read Message History`
   - ✅ `Use Slash Commands`
   - ✅ `Embed Links`
   - ✅ `Read Messages/View Channels`

## 📱 Step 3: Invite Bot to Your Server

1. Copy the generated OAuth2 URL from step 2
2. Open the URL in your browser
3. Select your Discord server
4. Authorize the bot

## 🆔 Step 4: Get Discord IDs

### Get Channel ID:
1. In Discord, go to **User Settings** → **Advanced** → Enable **"Developer Mode"**
2. Right-click the channel where you want the bot to respond
3. Click **"Copy ID"**

### Get Your User ID:
1. Right-click your username in Discord
2. Click **"Copy ID"**

## ⚙️ Step 5: Configure Environment Variables

Add these variables to your `.env` file:

```bash
# Discord Bot Configuration
DISCORD_BOT_TOKEN=your_bot_token_here
DISCORD_CHANNEL_ID=your_channel_id_here
DISCORD_ADMIN_USER_IDS=your_user_id_here,other_user_id_here
DISCORD_BOT_ENABLED=true
```

### Environment Variables Explained:

- **DISCORD_BOT_TOKEN** - The bot token from Step 1
- **DISCORD_CHANNEL_ID** - Channel ID where bot should respond to commands
- **DISCORD_ADMIN_USER_IDS** - Comma-separated list of user IDs allowed to use commands
- **DISCORD_BOT_ENABLED** - Set to `true` to enable the bot

## 📦 Step 6: Install Dependencies

```bash
pip install -r requirements.txt
```

The bot requires `discord.py>=2.3.0` which is included in the updated requirements.

## 🚀 Step 7: Run the Bot

```bash
cd /path/to/dcaTrader
python scripts/discord_bot.py
```

### Expected Output:
```
2024-01-01 12:00:00 - discord_bot - INFO - 🚀 Starting DCA Trading Bot Discord Bot...
2024-01-01 12:00:00 - discord_bot - INFO - 📱 Bot will respond to commands in channel ID: 123456789
2024-01-01 12:00:01 - discord_bot - INFO - ✅ Discord bot logged in as DCATradingBot#1234 (ID: 987654321)
2024-01-01 12:00:01 - discord_bot - INFO - 🎯 Monitoring channel ID: 123456789
2024-01-01 12:00:01 - discord_bot - INFO - 👥 Authorized users: [123456789]
```

## 🧪 Step 8: Test the Bot

In your Discord channel, try these commands:

```
!help
!appStatus
!status
```

### Expected Responses:

**!appStatus** - Shows system status with embed:
- Main App status (Running/Stopped, PID, Uptime)
- Maintenance Mode (Enabled/Disabled)
- Trading Status (Active/Paused/Stopped)

**!status** - Triggers portfolio report:
- "📊 Generating portfolio status report..."
- "✅ Portfolio status report has been sent to Discord!"
- (Portfolio details will appear as a separate Discord webhook message)

## 🔒 Security Features

- **Channel Restriction** - Bot only responds in the configured channel
- **User Authorization** - Only specified user IDs can use commands
- **Command Validation** - Invalid commands are ignored
- **Error Handling** - Graceful error responses

## 🛠️ Running as a Service

To keep the bot running permanently, you can create a systemd service:

```bash
sudo nano /etc/systemd/system/dca-discord-bot.service
```

```ini
[Unit]
Description=DCA Trading Bot Discord Bot
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/dcaTrader
ExecStart=/usr/bin/python3 scripts/discord_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then:
```bash
sudo systemctl daemon-reload
sudo systemctl enable dca-discord-bot
sudo systemctl start dca-discord-bot
sudo systemctl status dca-discord-bot
```

## 📊 Logs

Bot logs are written to:
- **Console** - Real-time output
- **File** - `logs/discord_bot.log`

## ❌ Troubleshooting

### Bot doesn't respond:
1. Check bot is online in Discord server member list
2. Verify channel ID is correct
3. Ensure your user ID is in DISCORD_ADMIN_USER_IDS
4. Check bot has proper permissions in the channel

### "Invalid Discord bot token" error:
1. Verify DISCORD_BOT_TOKEN is correctly copied
2. Check for extra spaces or characters
3. Regenerate token if needed

### Permission errors:
1. Ensure bot has "Send Messages" permission
2. Check channel permissions
3. Verify "Message Content Intent" is enabled

### Bot shows offline:
1. Check internet connection
2. Verify bot token is valid
3. Check Discord API status

## 🔄 Integration with Existing System

The Discord bot integrates seamlessly with your existing infrastructure:

- Uses your existing **config.py** for configuration
- Leverages **app_control.py** for system status
- Executes **status_reporter.py** for portfolio reports
- Writes to your existing **logs/** directory
- No changes to main trading app required

## 🎉 You're Done!

Your Discord bot is now ready to provide remote control and monitoring of your DCA Trading Bot system! 🚀 