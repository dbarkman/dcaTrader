#!/usr/bin/env python3
"""
Test script for Discord notifications

This script tests the Discord notification functionality and demonstrates
how to use the various notification types.
"""

import sys
import os

# Add src to path
sys.path.insert(0, 'src')

from utils.discord_notifications import (
    verify_discord_configuration,
    discord_trading_alert,
    discord_order_placed,
    discord_order_filled,
    discord_order_partial_filled,
    discord_cycle_completed,
    discord_system_error,
    discord_critical_error
)
from config import get_config

def main():
    """Test Discord notifications."""
    print("🧪 Testing Discord Notifications")
    print("=" * 50)
    
    config = get_config()
    
    # Check configuration
    print(f"Discord Webhook URL: {'✅ Configured' if config.discord_webhook_url else '❌ Not Configured'}")
    print(f"Discord User ID: {'✅ Configured' if config.discord_user_id else '❌ Not Configured'}")
    print(f"Discord Notifications Enabled: {config.discord_notifications_enabled}")
    print(f"Discord Trading Alerts Enabled: {config.discord_trading_alerts_enabled}")
    
    if not config.discord_notifications_enabled:
        print("\n❌ Discord notifications not configured!")
        print("\nTo configure Discord notifications, add to your .env file:")
        print("DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK_URL")
        print("DISCORD_USER_ID=123456789012345678  # Optional: your Discord user ID for mentions")
        print("DISCORD_NOTIFICATIONS_ENABLED=true")
        print("DISCORD_TRADING_ALERTS_ENABLED=true  # Optional: defaults to true")
        return False
    
    print("\n🧪 Testing Discord Configuration...")
    
    # Test 1: Configuration verification
    if verify_discord_configuration():
        print("✅ Configuration test passed!")
    else:
        print("❌ Configuration test failed!")
        return False
    
    # Test 2: Trading alerts
    print("\n🧪 Testing Trading Alerts...")
    
    # Order placed alert
    discord_order_placed("BTC/USD", "BUY", "test-order-123", 0.001, 45000.00)
    print("✅ Sent: Buy order placed alert")
    
    # Partial fill (should NOT send Discord notification)
    discord_order_partial_filled("BTC/USD", "BUY", "test-order-123", 44950.00, 0.0005, 0.0005)
    print("✅ Logged: Partial buy fill (no Discord notification)")
    
    # Full buy fill (should send notification WITHOUT user mention)
    discord_order_filled("BTC/USD", "BUY", "test-order-123", 44950.00, 0.001, is_full_fill=True)
    print("✅ Sent: Buy order FULL fill alert (no mention)")
    
    # Sell order placed
    discord_order_placed("BTC/USD", "SELL", "test-sell-456", 0.001, 46000.00)
    print("✅ Sent: Sell order placed alert")
    
    # Full sell fill (should send notification WITH user mention)
    discord_order_filled("BTC/USD", "SELL", "test-sell-456", 46050.00, 0.001, is_full_fill=True)
    print("✅ Sent: Sell order FULL fill alert (WITH user mention)")
    
    # Partial sell fill (should NOT send Discord notification)
    discord_order_partial_filled("ETH/USD", "SELL", "test-sell-789", 2850.00, 0.02, 0.03)
    print("✅ Logged: Partial sell fill (no Discord notification)")
    
    # Cycle completed
    discord_cycle_completed("BTC/USD", 1.10, 2.45)
    print("✅ Sent: Cycle completed alert")
    
    # Custom trading alert
    discord_trading_alert(
        "ETH/USD",
        "SAFETY ORDER TRIGGERED",
        {
            "Safety Order": 2,
            "Trigger Price": 2850.00,
            "Order Size": 0.05,
            "Total Position": 0.15,
            "Average Price": 2920.00
        },
        priority="normal"
    )
    print("✅ Sent: Custom safety order alert")
    
    # Test 3: System alerts
    print("\n🧪 Testing System Alerts...")
    
    # System error
    discord_system_error("Order Manager", "Failed to process order", "Order ID not found in database")
    print("✅ Sent: System error alert")
    
    # Critical error (this will mention the user if configured)
    discord_critical_error("Database", "Connection lost", "MySQL connection timeout after 30 seconds")
    print("✅ Sent: Critical error alert")
    
    print("\n🎉 All Discord notification tests completed!")
    print("\nCheck your Discord channel to see the notifications.")
    print("\nTo integrate with your trading bot, import the functions from:")
    print("  from utils.discord_notifications import discord_order_placed, discord_order_filled, etc.")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1) 