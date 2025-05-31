#!/usr/bin/env python3
"""
DCA Trading Bot - Discord Notifications Utility

This module provides Discord webhook functionality for the DCA trading bot.
Integrates with the existing notification system to send rich Discord messages
with embeds for trading events.

Features:
- Rich Discord embeds with colors and formatting
- Order placement and fill notifications
- System alerts and errors
- User mentions for critical events
- Rate limiting and error handling
- Integration with existing notification framework
"""

import logging
import time
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from discord_webhook import DiscordWebhook, DiscordEmbed

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import get_config

config = get_config()
logger = logging.getLogger(__name__)


class DiscordNotificationError(Exception):
    """Raised when Discord notification sending fails."""
    pass


class DiscordRateLimiter:
    """Simple rate limiter for Discord notifications."""
    
    def __init__(self, max_messages_per_minute: int = 10):
        self.max_messages_per_minute = max_messages_per_minute
        self.message_timestamps: List[float] = []
    
    def can_send_message(self) -> bool:
        """Check if we can send a message without hitting rate limits."""
        now = time.time()
        # Remove timestamps older than 1 minute
        self.message_timestamps = [ts for ts in self.message_timestamps if now - ts < 60]
        
        # Check if we're under the limit
        return len(self.message_timestamps) < self.max_messages_per_minute
    
    def record_message_sent(self) -> None:
        """Record that a message was sent."""
        self.message_timestamps.append(time.time())


# Global rate limiter instance
_discord_rate_limiter = DiscordRateLimiter()


def send_discord_notification(
    content: Optional[str] = None,
    embeds: Optional[List[DiscordEmbed]] = None,
    mention_user: bool = False,
    bypass_rate_limit: bool = False
) -> bool:
    """
    Send a Discord notification via webhook.
    
    Args:
        content: Plain text content (optional if embeds provided)
        embeds: List of Discord embeds for rich formatting
        mention_user: Whether to mention the configured user
        bypass_rate_limit: Skip rate limiting for critical messages
    
    Returns:
        True if notification was sent successfully, False otherwise
    """
    try:
        # Check if Discord notifications are configured
        if not config.discord_notifications_enabled:
            logger.debug("Discord notifications not configured, skipping notification")
            return False
        
        # Check rate limiting (unless bypassed for critical alerts)
        if not bypass_rate_limit and not _discord_rate_limiter.can_send_message():
            logger.warning("Discord rate limit exceeded, skipping notification")
            return False
        
        # Create webhook
        webhook = DiscordWebhook(url=config.discord_webhook_url)
        
        # Add user mention if requested and configured
        if mention_user and config.discord_user_id:
            mention_text = f"<@{config.discord_user_id}>"
            if content:
                content = f"{mention_text} {content}"
            else:
                content = mention_text
        
        # Set content if provided
        if content:
            webhook.set_content(content)
        
        # Add embeds if provided
        if embeds:
            for embed in embeds:
                webhook.add_embed(embed)
        
        # Send the webhook
        response = webhook.execute()
        
        # Check if send was successful
        if response.status_code in [200, 204]:
            # Record successful send
            if not bypass_rate_limit:
                _discord_rate_limiter.record_message_sent()
            
            logger.debug("Discord notification sent successfully")
            return True
        else:
            logger.error(f"Discord webhook failed with status {response.status_code}: {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"Error sending Discord notification: {e}")
        return False


def create_trading_embed(
    asset_symbol: str,
    event_type: str,
    details: Dict[str, Any],
    color: int = 0x00ff00  # Green by default
) -> DiscordEmbed:
    """
    Create a rich Discord embed for trading events.
    
    Args:
        asset_symbol: Trading pair symbol (e.g., 'BTC/USD')
        event_type: Type of trading event
        details: Dictionary of event details
        color: Embed color (hex format)
    
    Returns:
        DiscordEmbed: Formatted trading embed
    """
    # Color mapping for different event types
    color_map = {
        'BUY': 0x00ff00,      # Green for buy orders
        'SELL': 0xff6600,     # Orange for sell orders  
        'FILLED': 0x0099ff,   # Blue for fills
        'COMPLETED': 0x9900ff, # Purple for completed cycles
        'ERROR': 0xff0000,    # Red for errors
        'SYSTEM': 0xffff00    # Yellow for system events
    }
    
    # Determine color based on event type
    for event_key, event_color in color_map.items():
        if event_key.lower() in event_type.lower():
            color = event_color
            break
    
    # Create embed
    embed = DiscordEmbed(
        title=f"🤖 DCA Trading Bot - {event_type}",
        description=f"**Asset:** {asset_symbol}",
        color=color,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    # Add details as fields
    for key, value in details.items():
        # Format field name (capitalize and replace underscores)
        field_name = key.replace('_', ' ').title()
        
        # Format value based on type
        if isinstance(value, (int, float)) and 'price' in key.lower():
            field_value = f"${value:,.2f}" if value >= 1 else f"${value:.6f}"
        elif isinstance(value, (int, float)) and ('quantity' in key.lower() or 'qty' in key.lower()):
            field_value = f"{value:.8f}".rstrip('0').rstrip('.')
        elif isinstance(value, (int, float)) and 'percent' in key.lower():
            field_value = f"{value:.2f}%"
        else:
            field_value = str(value)
        
        embed.add_embed_field(name=field_name, value=field_value, inline=True)
    
    # Add footer with timestamp
    embed.set_footer(
        text=f"DCA Bot • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    
    return embed


def create_system_embed(
    component: str,
    message: str,
    priority: str = "normal",
    error_details: Optional[str] = None
) -> DiscordEmbed:
    """
    Create a Discord embed for system events.
    
    Args:
        component: System component name
        message: Alert message
        priority: Alert priority level
        error_details: Optional error details
    
    Returns:
        DiscordEmbed: Formatted system embed
    """
    # Color based on priority
    priority_colors = {
        'low': 0x808080,      # Gray
        'normal': 0x0099ff,   # Blue
        'high': 0xff9900,     # Orange
        'critical': 0xff0000  # Red
    }
    
    color = priority_colors.get(priority.lower(), 0x0099ff)
    
    # Emoji based on priority
    priority_emojis = {
        'low': 'ℹ️',
        'normal': '🔔',
        'high': '⚠️',
        'critical': '🚨'
    }
    
    emoji = priority_emojis.get(priority.lower(), '🔔')
    
    embed = DiscordEmbed(
        title=f"{emoji} System Alert - {component}",
        description=message,
        color=color,
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    
    embed.add_embed_field(name="Priority", value=priority.upper(), inline=True)
    embed.add_embed_field(name="Component", value=component, inline=True)
    
    # Add trading mode
    trading_mode = "📋 Paper Trading" if config.is_paper_trading else "🔴 LIVE TRADING"
    embed.add_embed_field(name="Trading Mode", value=trading_mode, inline=True)
    
    # Add error details if provided
    if error_details:
        # Truncate long error details
        if len(error_details) > 1000:
            error_details = error_details[:1000] + "..."
        embed.add_embed_field(name="Error Details", value=f"```\n{error_details}\n```", inline=False)
    
    embed.set_footer(
        text=f"DCA Bot • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    
    return embed


# High-level notification functions that integrate with existing system

def discord_trading_alert(
    asset_symbol: str,
    event_type: str,
    details: Dict[str, Any],
    priority: str = "normal"
) -> bool:
    """
    Send a Discord trading alert with rich formatting.
    
    Args:
        asset_symbol: Trading pair symbol (e.g., 'BTC/USD')
        event_type: Type of trading event
        details: Dictionary of event details
        priority: Alert priority level
    
    Returns:
        True if alert was sent successfully, False otherwise
    """
    # Check if Discord trading alerts are enabled
    if not config.discord_trading_alerts_enabled:
        logger.debug(f"Discord trading alerts disabled, skipping {event_type} alert for {asset_symbol}")
        return True  # Return True to indicate "success" (alert was intentionally skipped)
    
    if not config.discord_notifications_enabled:
        logger.debug("Discord notifications not configured, skipping trading alert")
        return False
    
    try:
        # Create trading embed
        embed = create_trading_embed(asset_symbol, event_type, details)
        
        # Determine if we should mention user for high priority events
        mention_user = priority.lower() in ['high', 'critical']
        
        # Send notification
        return send_discord_notification(
            embeds=[embed],
            mention_user=mention_user,
            bypass_rate_limit=(priority.lower() == 'critical')
        )
        
    except Exception as e:
        logger.error(f"Error sending Discord trading alert: {e}")
        return False


def discord_system_alert(
    component: str,
    message: str,
    error_details: Optional[str] = None,
    priority: str = "high"
) -> bool:
    """
    Send a Discord system alert.
    
    Args:
        component: System component name
        message: Alert message
        error_details: Optional error details or stack trace
        priority: Alert priority level
    
    Returns:
        True if alert was sent successfully, False otherwise
    """
    if not config.discord_notifications_enabled:
        logger.debug("Discord notifications not configured, skipping system alert")
        return False
    
    try:
        # Create system embed
        embed = create_system_embed(component, message, priority, error_details)
        
        # Always mention user for system alerts
        mention_user = True
        
        # Critical system alerts bypass rate limiting
        bypass_rate_limit = priority.lower() == 'critical'
        
        # Send notification
        return send_discord_notification(
            embeds=[embed],
            mention_user=mention_user,
            bypass_rate_limit=bypass_rate_limit
        )
        
    except Exception as e:
        logger.error(f"Error sending Discord system alert: {e}")
        return False


# Convenience functions for common trading events

def discord_order_placed(asset_symbol: str, order_type: str, order_id: str, quantity: float, price: float) -> bool:
    """Send Discord alert for order placement."""
    if not config.discord_trading_alerts_enabled:
        logger.debug(f"Discord trading alerts disabled, skipping order placed alert for {asset_symbol}")
        return True
    
    return discord_trading_alert(
        asset_symbol,
        f"{order_type.upper()} ORDER PLACED",
        {
            'Order ID': order_id[:8] + '...' if len(order_id) > 8 else order_id,
            'Order Type': order_type.upper(),
            'Quantity': quantity,
            'Price': price,
            'Total Value': quantity * price
        }
    )


def discord_order_filled(asset_symbol: str, order_type: str, order_id: str, fill_price: float, quantity: float, is_full_fill: bool = True) -> bool:
    """Send Discord alert for order fill (only for full fills)."""
    if not config.discord_trading_alerts_enabled:
        logger.debug(f"Discord trading alerts disabled, skipping order filled alert for {asset_symbol}")
        return True
    
    # Only send notifications for full fills
    if not is_full_fill:
        logger.debug(f"Skipping Discord notification for partial fill of {order_id}")
        return True
    
    # Determine if we should mention user (only for sell orders)
    mention_user = order_type.upper() == 'SELL'
    priority = "normal" if order_type.upper() == 'BUY' else "high"  # Higher priority for sells to ensure mention
    
    embed = create_trading_embed(
        asset_symbol,
        f"{order_type.upper()} ORDER FILLED",
        {
            'Order ID': order_id[:8] + '...' if len(order_id) > 8 else order_id,
            'Order Type': order_type.upper(),
            'Fill Price': fill_price,
            'Quantity': quantity,
            'Total Value': quantity * fill_price,
            'Fill Status': '✅ FULL FILL'
        }
    )
    
    return send_discord_notification(
        embeds=[embed],
        mention_user=mention_user,
        bypass_rate_limit=False
    )


def discord_order_partial_filled(asset_symbol: str, order_type: str, order_id: str, fill_price: float, quantity: float, remaining_quantity: float) -> bool:
    """Log partial fill but don't send Discord notification (per user preference)."""
    logger.info(f"Partial fill for {asset_symbol} {order_type} order {order_id}: {quantity} filled at ${fill_price}, {remaining_quantity} remaining")
    return True  # Always return True since we're intentionally not sending notification


def discord_cycle_completed(asset_symbol: str, profit: float, profit_percent: float) -> bool:
    """Send Discord alert for completed trading cycle."""
    if not config.discord_trading_alerts_enabled:
        logger.debug(f"Discord trading alerts disabled, skipping cycle completed alert for {asset_symbol}")
        return True
    
    return discord_trading_alert(
        asset_symbol,
        "CYCLE COMPLETED",
        {
            'Profit': profit,
            'Profit Percentage': profit_percent,
            'Status': '✅ Profitable' if profit > 0 else '❌ Loss'
        },
        priority="normal"
    )


def discord_system_error(component: str, error_message: str, error_details: Optional[str] = None) -> bool:
    """Send Discord alert for system errors."""
    return discord_system_alert(
        component,
        f"Error: {error_message}",
        error_details,
        priority="high"
    )


def discord_critical_error(component: str, error_message: str, error_details: Optional[str] = None) -> bool:
    """Send Discord alert for critical system errors."""
    return discord_system_alert(
        component,
        f"CRITICAL ERROR: {error_message}",
        error_details,
        priority="critical"
    )


def verify_discord_configuration() -> bool:
    """
    Verify Discord configuration by sending a test message.
    
    Returns:
        True if test message was sent successfully, False otherwise
    """
    if not config.discord_notifications_enabled:
        logger.warning("Discord notifications not configured, cannot send test message")
        return False
    
    try:
        embed = DiscordEmbed(
            title="🧪 Discord Configuration Test",
            description="This is a test message to verify Discord webhook configuration.",
            color=0x00ff00,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        
        embed.add_embed_field(name="Status", value="✅ Configuration Working", inline=True)
        embed.add_embed_field(name="Trading Mode", value="📋 Paper Trading" if config.is_paper_trading else "🔴 LIVE TRADING", inline=True)
        embed.add_embed_field(name="Webhook URL", value="✅ Configured", inline=True)
        
        if config.discord_user_id:
            embed.add_embed_field(name="User Mentions", value="✅ Configured", inline=True)
        else:
            embed.add_embed_field(name="User Mentions", value="❌ Not Configured", inline=True)
        
        embed.set_footer(
            text=f"DCA Bot Test • {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        
        success = send_discord_notification(
            content="🧪 **Discord Configuration Test**",
            embeds=[embed],
            mention_user=bool(config.discord_user_id),
            bypass_rate_limit=True
        )
        
        if success:
            logger.info("Discord test message sent successfully")
        else:
            logger.error("Failed to send Discord test message")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending Discord test message: {e}")
        return False 