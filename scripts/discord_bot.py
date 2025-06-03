#!/usr/bin/env python3
"""
DCA Trading Bot - Discord Bot

A Discord bot that responds to commands and provides system status and control.

Commands:
    !appStatus - Get main app status (running, PID, uptime, maintenance mode)
    !status    - Send portfolio status report to Discord (executes status_reporter.py)

Setup:
    1. Create a Discord Application/Bot at https://discord.com/developers/applications
    2. Copy the bot token to your .env file as DISCORD_BOT_TOKEN
    3. Get your Discord channel ID and add it as DISCORD_CHANNEL_ID
    4. Add your Discord user ID to DISCORD_ADMIN_USER_IDS (comma-separated)
    5. Set DISCORD_BOT_ENABLED=true

Environment Variables:
    DISCORD_BOT_TOKEN - Your Discord bot token
    DISCORD_CHANNEL_ID - Channel ID where bot should respond
    DISCORD_ADMIN_USER_IDS - Comma-separated list of user IDs allowed to use commands
    DISCORD_BOT_ENABLED - Set to true to enable the bot

Usage:
    python scripts/discord_bot.py
"""

import sys
import os
import logging
import asyncio
import subprocess
from pathlib import Path
from typing import Optional, Tuple

import discord
from discord.ext import commands

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from config import get_config

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/discord_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('discord_bot')

# Disable discord.py debug logging
discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.WARNING)

config = get_config()

# Bot configuration
COMMAND_PREFIX = '!'
PROJECT_ROOT = Path(__file__).parent.parent


class DCATradingBot(commands.Bot):
    """Discord bot for DCA Trading Bot system control."""
    
    def __init__(self):
        # Define intents
        intents = discord.Intents.default()
        intents.message_content = True  # Required for reading message content
        
        super().__init__(
            command_prefix=COMMAND_PREFIX,
            intents=intents,
            help_command=None  # Disable default help command
        )
    
    async def on_ready(self):
        """Called when the bot is ready."""
        logger.info(f'✅ Discord bot logged in as {self.user} (ID: {self.user.id})')
        logger.info(f'🎯 Monitoring channel ID: {config.discord_channel_id}')
        logger.info(f'👥 Authorized users: {config.discord_admin_user_ids}')
    
    async def on_command_error(self, ctx, error):
        """Handle command errors."""
        if isinstance(error, commands.CommandNotFound):
            return  # Ignore unknown commands
        elif isinstance(error, commands.CheckFailure):
            await ctx.send("❌ You don't have permission to use this command.")
        else:
            logger.error(f"Command error: {error}")
            await ctx.send(f"❌ An error occurred: {error}")


def is_authorized_user():
    """Check if user is authorized to use bot commands."""
    async def predicate(ctx):
        # Check if command is in the correct channel
        if config.discord_channel_id and ctx.channel.id != config.discord_channel_id:
            return False
        
        # Check if user is authorized
        if config.discord_admin_user_ids and ctx.author.id not in config.discord_admin_user_ids:
            return False
        
        return True
    
    return commands.check(predicate)


def get_app_status_info() -> Tuple[bool, Optional[int], Optional[str], bool]:
    """
    Get comprehensive app status information.
    
    Returns:
        Tuple[bool, Optional[int], Optional[str], bool]: (is_running, pid, uptime, maintenance_mode)
    """
    # Import app_control functions
    sys.path.insert(0, str(PROJECT_ROOT / 'scripts'))
    from app_control import get_app_status, is_maintenance_mode
    
    is_running, pid, uptime = get_app_status()
    maintenance_mode = is_maintenance_mode()
    
    return is_running, pid, uptime, maintenance_mode


# Initialize bot
bot = DCATradingBot()


@bot.command(name='appStatus')
@is_authorized_user()
async def app_status_command(ctx):
    """Get main app status including PID, uptime, and maintenance mode."""
    try:
        logger.info(f"App status requested by {ctx.author} ({ctx.author.id})")
        
        # Get status information
        is_running, pid, uptime, maintenance_mode = get_app_status_info()
        
        # Create status embed
        embed = discord.Embed(
            title="🤖 DCA Trading Bot Status",
            color=discord.Color.green() if is_running and not maintenance_mode else discord.Color.red()
        )
        
        # App status
        if is_running:
            embed.add_field(
                name="📊 Main App",
                value=f"✅ Running (PID: {pid})\n⏱️ Uptime: {uptime}",
                inline=True
            )
        else:
            embed.add_field(
                name="📊 Main App",
                value="❌ Not Running",
                inline=True
            )
        
        # Maintenance mode
        maintenance_status = "🔧 Enabled" if maintenance_mode else "✅ Disabled"
        embed.add_field(
            name="🛠️ Maintenance Mode",
            value=maintenance_status,
            inline=True
        )
        
        # Trading status
        if maintenance_mode:
            trading_status = "⏸️ Paused (Maintenance)"
        elif is_running:
            trading_status = "✅ Active"
        else:
            trading_status = "❌ Stopped"
        
        embed.add_field(
            name="💹 Trading Status",
            value=trading_status,
            inline=True
        )
        
        # Add timestamp
        embed.timestamp = discord.utils.utcnow()
        
        await ctx.send(embed=embed)
        
    except Exception as e:
        logger.error(f"Error getting app status: {e}")
        await ctx.send(f"❌ Error getting app status: {e}")


@bot.command(name='status')
@is_authorized_user()
async def portfolio_status_command(ctx):
    """Execute status_reporter.py to send portfolio status to Discord."""
    try:
        logger.info(f"Portfolio status requested by {ctx.author} ({ctx.author.id})")
        
        # Send acknowledgment first
        await ctx.send("📊 Generating portfolio status report...")
        
        # Execute status_reporter.py
        status_script = PROJECT_ROOT / 'scripts' / 'status_reporter.py'
        
        result = subprocess.run(
            [sys.executable, str(status_script)],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30  # 30 second timeout
        )
        
        if result.returncode == 0:
            await ctx.send("✅ Portfolio status report has been sent to Discord!")
            logger.info("Status reporter executed successfully")
        else:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            await ctx.send(f"❌ Error generating status report: {error_msg}")
            logger.error(f"Status reporter failed: {error_msg}")
            
    except subprocess.TimeoutExpired:
        await ctx.send("⏱️ Status report timed out after 30 seconds")
        logger.error("Status reporter timed out")
    except Exception as e:
        logger.error(f"Error executing status reporter: {e}")
        await ctx.send(f"❌ Error executing status reporter: {e}")


@bot.command(name='help')
@is_authorized_user()
async def help_command(ctx):
    """Show available commands."""
    embed = discord.Embed(
        title="🤖 DCA Trading Bot Commands",
        description="Available commands for system control:",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="!appStatus",
        value="Get main app status (running, PID, uptime, maintenance mode)",
        inline=False
    )
    
    embed.add_field(
        name="!status",
        value="Send portfolio status report to Discord",
        inline=False
    )
    
    embed.add_field(
        name="!help",
        value="Show this help message",
        inline=False
    )
    
    embed.set_footer(text="Only authorized users can use these commands")
    
    await ctx.send(embed=embed)


async def main():
    """Main function to run the Discord bot."""
    # Validate configuration
    if not config.discord_bot_enabled:
        logger.error("❌ Discord bot is not enabled. Check your configuration:")
        logger.error(f"   - DISCORD_BOT_TOKEN: {'✅ Set' if config.discord_bot_token else '❌ Missing'}")
        logger.error(f"   - DISCORD_CHANNEL_ID: {'✅ Set' if config.discord_channel_id else '❌ Missing'}")
        logger.error(f"   - DISCORD_BOT_ENABLED: {'✅ True' if config._get_bool_env('DISCORD_BOT_ENABLED', False) else '❌ False'}")
        return
    
    if not config.discord_admin_user_ids:
        logger.warning("⚠️ No admin user IDs configured. Bot will accept commands from anyone in the channel.")
    
    logger.info("🚀 Starting DCA Trading Bot Discord Bot...")
    logger.info(f"📱 Bot will respond to commands in channel ID: {config.discord_channel_id}")
    
    try:
        # Start the bot
        await bot.start(config.discord_bot_token)
    except discord.LoginFailure:
        logger.error("❌ Invalid Discord bot token")
    except Exception as e:
        logger.error(f"❌ Error starting Discord bot: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Discord bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}") 