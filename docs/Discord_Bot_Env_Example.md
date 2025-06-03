# Discord Bot Environment Variables Example

Add these variables to your `.env` file to enable the Discord bot:

```bash
# =============================================================================
# DISCORD BOT CONFIGURATION
# =============================================================================

# Discord Bot Token (get from Discord Developer Portal)
DISCORD_BOT_TOKEN=your_bot_token_here

# Discord Channel ID where bot should respond (right-click channel → Copy ID)
DISCORD_CHANNEL_ID=123456789012345678

# Discord User IDs allowed to use commands (comma-separated)
# Get your user ID by right-clicking your username → Copy ID
DISCORD_ADMIN_USER_IDS=987654321098765432,111222333444555666

# Enable/disable the Discord bot
DISCORD_BOT_ENABLED=true
```

## How to Get These Values:

### 1. DISCORD_BOT_TOKEN:
1. Go to https://discord.com/developers/applications
2. Create new application or select existing one
3. Go to "Bot" section
4. Copy the token

### 2. DISCORD_CHANNEL_ID:
1. Enable Developer Mode in Discord (User Settings → Advanced → Developer Mode)
2. Right-click the channel where you want bot to respond
3. Click "Copy ID"

### 3. DISCORD_ADMIN_USER_IDS:
1. Right-click your username in Discord
2. Click "Copy ID"
3. For multiple users, separate with commas (no spaces)

## Testing Your Configuration:

Run this command to test your setup:

```bash
python scripts/discord_bot.py
```

Expected output if configured correctly:
```
2024-01-01 12:00:00 - discord_bot - INFO - 🚀 Starting DCA Trading Bot Discord Bot...
2024-01-01 12:00:00 - discord_bot - INFO - 📱 Bot will respond to commands in channel ID: 123456789
2024-01-01 12:00:01 - discord_bot - INFO - ✅ Discord bot logged in as YourBotName#1234
```

If you see errors about missing configuration, double-check your `.env` file values. 