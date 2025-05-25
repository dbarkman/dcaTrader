#!/usr/bin/env python3
"""
DCA Trading Bot - Main WebSocket Application

This script manages real-time connections to Alpaca's WebSocket streams for:
- Market data (quotes, trades, bars) via CryptoDataStream
- Trade updates (order fills, cancellations) via TradingStream

The application runs continuously, processing real-time events and will eventually
trigger trading logic based on market conditions and account updates.
"""

import asyncio
import signal
import logging
import os
import sys
from typing import Optional
from decimal import Decimal
from datetime import datetime, timedelta
import decimal
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from alpaca.data.live import CryptoDataStream
from alpaca.trading.stream import TradingStream
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError
import mysql.connector

# Import our configuration and logging
from config import get_config
from utils.logging_config import setup_logging, get_asset_logger, log_asset_lifecycle_event
from utils.notifications import alert_order_placed, alert_order_filled, alert_system_error, alert_critical_error

# Import our database models and utilities
from utils.db_utils import get_db_connection, execute_query
from models.asset_config import get_asset_config, update_asset_config
from models.cycle_data import get_latest_cycle, update_cycle, create_cycle
from utils.alpaca_client_rest import get_trading_client, place_limit_buy_order, get_positions, place_market_sell_order

# Initialize configuration and logging
config = get_config()
setup_logging("main_app", enable_asset_tracking=True)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False
# Global stream references for shutdown
crypto_stream_ref = None
trading_stream_ref = None

# Global tracking for recent orders to prevent duplicates
recent_orders = {}  # symbol -> {'order_id': str, 'timestamp': datetime}

# PID file configuration
PID_FILE_PATH = Path(__file__).parent.parent / 'main_app.pid'


def create_pid_file():
    """
    Create PID file with current process ID.
    """
    try:
        with open(PID_FILE_PATH, 'w') as f:
            f.write(str(os.getpid()))
        logger.info(f"Created PID file: {PID_FILE_PATH} (PID: {os.getpid()})")
    except Exception as e:
        logger.error(f"Failed to create PID file: {e}")


def remove_pid_file():
    """
    Remove PID file on clean shutdown.
    """
    try:
        if PID_FILE_PATH.exists():
            PID_FILE_PATH.unlink()
            logger.info(f"Removed PID file: {PID_FILE_PATH}")
    except Exception as e:
        logger.error(f"Failed to remove PID file: {e}")


def validate_environment() -> bool:
    """
    Validate that required configuration is available.
    
    Returns:
        True if all required configuration is present, False otherwise
    """
    try:
        # Configuration validation is now handled by the config module
        # Just verify we can access the key properties
        _ = config.alpaca_api_key
        _ = config.alpaca_api_secret
        _ = config.db_host
        logger.info("Configuration validation successful")
        return True
    except Exception as e:
        logger.error(f"Configuration validation failed: {e}")
        alert_critical_error("main_app", f"Configuration validation failed: {e}")
        return False


async def on_crypto_quote(quote):
    """
    Handler for cryptocurrency quote updates.
    
    Phase 4: Monitor prices and place base orders when conditions are met.
    Phase 5: Monitor prices and place safety orders when conditions are met.
    Phase 6: Monitor prices and place take-profit orders when conditions are met.
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    logger.info(f"Quote: {quote.symbol} - Bid: ${quote.bid_price} @ {quote.bid_size}, "
               f"Ask: ${quote.ask_price} @ {quote.ask_size}")
    
    # Phase 4: Check if we should place a base order for this asset
    try:
        await asyncio.to_thread(check_and_place_base_order, quote)
    except Exception as e:
        logger.error(f"Error in base order check for {quote.symbol}: {e}")
    
    # Phase 5: Check if we should place a safety order for this asset
    try:
        await asyncio.to_thread(check_and_place_safety_order, quote)
    except Exception as e:
        logger.error(f"Error in safety order check for {quote.symbol}: {e}")
    
    # Phase 6: Check if we should place a take-profit order for this asset
    try:
        await asyncio.to_thread(check_and_place_take_profit_order, quote)
    except Exception as e:
        logger.error(f"Error in take-profit check for {quote.symbol}: {e}")


def check_and_place_base_order(quote):
    """
    Check if conditions are met to place a base order and place it if so.
    
    This function runs in a separate thread to avoid blocking the WebSocket.
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    global recent_orders
    symbol = quote.symbol
    ask_price = quote.ask_price
    bid_price = quote.bid_price
    
    try:
        # Get asset-specific logger for lifecycle tracking
        asset_logger = get_asset_logger(symbol)
        
        # Step 1: Check for recent orders to prevent duplicates
        now = datetime.now()
        recent_order_cooldown = config.order_cooldown_seconds
        
        if symbol in recent_orders:
            time_since_order = now - recent_orders[symbol]['timestamp']
            if time_since_order.total_seconds() < recent_order_cooldown:
                logger.debug(f"Skipping {symbol} - recent order placed {time_since_order.total_seconds():.1f}s ago")
                return
        
        # Step 2: Get asset configuration
        asset_config = get_asset_config(symbol)
        if not asset_config:
            # Asset not configured - skip silently
            return
        
        if not asset_config.is_enabled:
            logger.debug(f"Asset {symbol} is disabled, skipping base order check")
            return
        
        logger.debug(f"Checking base order conditions for {symbol}")
        
        # Step 3: Get latest cycle for this asset
        latest_cycle = get_latest_cycle(asset_config.id)
        if not latest_cycle:
            logger.debug(f"No cycle found for asset {symbol}, skipping base order check")
            return
        
        # Step 4: Check if cycle is in 'watching' status with zero quantity
        if latest_cycle.status != 'watching':
            logger.debug(f"Asset {symbol} cycle status is '{latest_cycle.status}', not 'watching' - skipping")
            return
        
        if latest_cycle.quantity != Decimal('0'):
            logger.debug(f"Asset {symbol} cycle has quantity {latest_cycle.quantity}, not 0 - skipping")
            return
        
        logger.info(f"Base order conditions met for {symbol} - checking Alpaca positions...")
        
        # Step 5: Initialize Alpaca client and check for existing positions
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for {symbol}")
            return
        
        # Step 6: Check for existing positions
        positions = get_positions(client)
        existing_position = None
        
        for position in positions:
            if position.symbol == symbol and float(position.qty) != 0:
                existing_position = position
                break
        
        if existing_position:
            logger.warning(f"Base order for {symbol} skipped, existing position found on Alpaca. "
                          f"Position: {existing_position.qty} @ ${existing_position.avg_cost}")
            # TODO: Send notification in future phases
            return
        
        # Step 7: No existing position - we can place a base order
        logger.info(f"No existing position for {symbol} - proceeding with base order placement")
        
        # Step 8: Calculate order size (convert USD to crypto quantity)
        if not ask_price or ask_price <= 0:
            logger.error(f"Invalid ask price for {symbol}: {ask_price}")
            return
        
        if not bid_price or bid_price <= 0:
            logger.error(f"Invalid bid price for {symbol}: {bid_price}")
            return
        
        base_order_usd = float(asset_config.base_order_amount)
        if not base_order_usd or base_order_usd <= 0:
            logger.error(f"Invalid base order amount for {symbol}: {base_order_usd}")
            return
            
        order_quantity = base_order_usd / ask_price
        
        # Validate calculated values before placing order
        if not order_quantity or order_quantity <= 0:
            logger.error(f"Invalid calculated order quantity for {symbol}: {order_quantity}")
            return
        
        # Enhanced price logging
        spread = ask_price - bid_price
        spread_pct = (spread / bid_price) * 100 if bid_price > 0 else 0
        
        logger.info(f"📊 Market Data for {symbol}:")
        logger.info(f"   Bid: ${bid_price:,.4f} | Ask: ${ask_price:,.4f} | Spread: ${spread:.4f} ({spread_pct:.3f}%)")
        logger.info(f"   Order Amount: ${base_order_usd} ÷ ${ask_price:,.4f} = {order_quantity:.8f} {symbol.split('/')[0]}")
        
        # Step 9: Place the base limit buy order with detailed logging
        
        # For integration testing, use aggressive pricing to ensure fast fills
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            aggressive_price = ask_price * 1.05
            logger.info(f"🚀 TESTING MODE: Using aggressive pricing (5% above ask)")
            logger.info(f"   Ask Price: ${ask_price:,.4f}")
            logger.info(f"   Aggressive Price: ${aggressive_price:,.4f} (+5%)")
            limit_price = aggressive_price
        else:
            # Normal production mode: use ask price
            limit_price = ask_price
        
        logger.info(f"🔄 Placing LIMIT BUY order for {symbol}:")
        logger.info(f"   Type: LIMIT | Side: BUY")
        logger.info(f"   Limit Price: ${limit_price:,.4f} {'(AGGRESSIVE +5%)' if testing_mode else '(current ask)'}")
        logger.info(f"   Quantity: {order_quantity:.8f}")
        logger.info(f"   Total Value: ${base_order_usd}")
        
        order = place_limit_buy_order(
            client=client,
            symbol=symbol,
            qty=order_quantity,
            limit_price=limit_price,
            time_in_force='gtc'  # Use 'gtc' orders for crypto (day is not valid for crypto)
        )
        
        if order:
            # Track this order to prevent duplicates
            recent_orders[symbol] = {
                'order_id': order.id,
                'timestamp': now
            }
            
            logger.info(f"✅ LIMIT BUY order PLACED for {symbol}:")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Quantity: {order_quantity:.8f}")
            logger.info(f"   Limit Price: ${limit_price:,.4f}")
            logger.info(f"   Time in Force: GTC")
            # NOTE: We do NOT update the cycle here - that's TradingStream's job when it fills
        else:
            logger.error(f"❌ Failed to place base order for {symbol}")
            
    except Exception as e:
        logger.error(f"Error in check_and_place_base_order for {symbol}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


def check_and_place_safety_order(quote):
    """
    Check if conditions are met to place a safety order and place it if so.
    
    This function runs in a separate thread to avoid blocking the WebSocket.
    Safety orders are placed when:
    - Cycle status is 'watching' AND quantity > 0 (position exists)
    - Safety orders count < max_safety_orders
    - Current ask price <= trigger price (last_order_fill_price * (1 - safety_order_deviation/100))
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    global recent_orders
    symbol = quote.symbol
    ask_price = quote.ask_price
    bid_price = quote.bid_price
    
    try:
        # Step 1: Check for recent orders to prevent duplicates
        now = datetime.now()
        recent_order_cooldown = int(os.getenv('ORDER_COOLDOWN_SECONDS', '5'))  # Default 5 seconds
        
        if symbol in recent_orders:
            time_since_order = now - recent_orders[symbol]['timestamp']
            if time_since_order.total_seconds() < recent_order_cooldown:
                logger.debug(f"Skipping safety order for {symbol} - recent order placed {time_since_order.total_seconds():.1f}s ago")
                return
        
        # Step 2: Get asset configuration
        asset_config = get_asset_config(symbol)
        if not asset_config:
            # Asset not configured - skip silently
            return
        
        if not asset_config.is_enabled:
            logger.debug(f"Asset {symbol} is disabled, skipping safety order check")
            return
        
        # Step 3: Get latest cycle for this asset
        latest_cycle = get_latest_cycle(asset_config.id)
        if not latest_cycle:
            logger.debug(f"No cycle found for asset {symbol}, skipping safety order check")
            return
        
        # Step 4: Check if cycle is in 'watching' status with quantity > 0 (existing position)
        if latest_cycle.status != 'watching':
            logger.debug(f"Asset {symbol} cycle status is '{latest_cycle.status}', not 'watching' - skipping safety order")
            return
        
        if latest_cycle.quantity <= Decimal('0'):
            logger.debug(f"Asset {symbol} cycle has quantity {latest_cycle.quantity}, not > 0 - skipping safety order")
            return
        
        # Step 5: Check if we can place more safety orders
        if latest_cycle.safety_orders >= asset_config.max_safety_orders:
            logger.debug(f"Asset {symbol} already at max safety orders ({latest_cycle.safety_orders}/{asset_config.max_safety_orders}) - skipping")
            return
        
        # Step 6: Check if we have a last_order_fill_price to calculate trigger from
        if latest_cycle.last_order_fill_price is None:
            logger.debug(f"Asset {symbol} has no last_order_fill_price - cannot calculate safety order trigger")
            return
        
        # Step 7: Calculate trigger price for safety order
        safety_deviation_decimal = asset_config.safety_order_deviation / Decimal('100')  # Convert % to decimal
        trigger_price = latest_cycle.last_order_fill_price * (Decimal('1') - safety_deviation_decimal)
        
        # Convert ask_price to Decimal for consistent calculations
        ask_price_decimal = Decimal(str(ask_price))
        
        logger.debug(f"Safety order conditions for {symbol}:")
        logger.debug(f"   Status: {latest_cycle.status} | Quantity: {latest_cycle.quantity}")
        logger.debug(f"   Safety Orders: {latest_cycle.safety_orders}/{asset_config.max_safety_orders}")
        logger.debug(f"   Last Fill Price: ${latest_cycle.last_order_fill_price}")
        logger.debug(f"   Safety Deviation: {asset_config.safety_order_deviation}%")
        logger.debug(f"   Trigger Price: ${trigger_price:.4f}")
        logger.debug(f"   Current Ask: ${ask_price}")
        
        # Step 8: Check if current ask price has dropped enough to trigger safety order
        if ask_price_decimal > trigger_price:
            logger.debug(f"Ask price ${ask_price} > trigger ${trigger_price:.4f} - no safety order needed")
            return
        
        logger.info(f"🛡️ Safety order conditions met for {symbol}!")
        
        # Step 9: Validate market data
        if not ask_price or ask_price <= 0:
            logger.error(f"Invalid ask price for safety order {symbol}: {ask_price}")
            return
        
        if not bid_price or bid_price <= 0:
            logger.error(f"Invalid bid price for safety order {symbol}: {bid_price}")
            return
        
        # Step 10: Initialize Alpaca client 
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for safety order {symbol}")
            return
        
        # Step 11: Calculate safety order size (convert USD to crypto quantity)
        safety_order_usd = float(asset_config.safety_order_amount)
        if not safety_order_usd or safety_order_usd <= 0:
            logger.error(f"Invalid safety order amount for {symbol}: {safety_order_usd}")
            return
            
        order_quantity = safety_order_usd / ask_price
        
        # Validate calculated values before placing order
        if not order_quantity or order_quantity <= 0:
            logger.error(f"Invalid calculated safety order quantity for {symbol}: {order_quantity}")
            return
        
        # Enhanced logging for safety order
        price_drop = latest_cycle.last_order_fill_price - ask_price_decimal
        price_drop_pct = (price_drop / latest_cycle.last_order_fill_price) * Decimal('100')
        
        logger.info(f"📊 Safety Order Analysis for {symbol}:")
        logger.info(f"   Last Fill: ${latest_cycle.last_order_fill_price:.4f} | Current Ask: ${ask_price:,.4f}")
        logger.info(f"   Price Drop: ${price_drop:.4f} ({price_drop_pct:.2f}%)")
        logger.info(f"   Trigger at: ${trigger_price:.4f} ({asset_config.safety_order_deviation}% drop)")
        logger.info(f"   Safety Orders: {latest_cycle.safety_orders + 1}/{asset_config.max_safety_orders}")
        logger.info(f"   Order Amount: ${safety_order_usd} ÷ ${ask_price:,.4f} = {order_quantity:.8f} {symbol.split('/')[0]}")
        
        # Step 12: Place the safety limit buy order with detailed logging
        
        # For integration testing, use aggressive pricing to ensure fast fills
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            aggressive_price = ask_price * 1.05
            logger.info(f"🚀 TESTING MODE: Using aggressive pricing (5% above ask)")
            logger.info(f"   Ask Price: ${ask_price:,.4f}")
            logger.info(f"   Aggressive Price: ${aggressive_price:,.4f} (+5%)")
            limit_price = aggressive_price
        else:
            # Normal production mode: use ask price
            limit_price = ask_price
        
        logger.info(f"🔄 Placing SAFETY LIMIT BUY order for {symbol}:")
        logger.info(f"   Type: LIMIT | Side: BUY | Order Type: SAFETY #{latest_cycle.safety_orders + 1}")
        logger.info(f"   Limit Price: ${limit_price:,.4f} {'(AGGRESSIVE +5%)' if testing_mode else '(current ask)'}")
        logger.info(f"   Quantity: {order_quantity:.8f}")
        logger.info(f"   Total Value: ${safety_order_usd}")
        
        order = place_limit_buy_order(
            client=client,
            symbol=symbol,
            qty=order_quantity,
            limit_price=limit_price,
            time_in_force='gtc'  # Use 'gtc' orders for crypto
        )
        
        if order:
            # Track this order to prevent duplicates
            recent_orders[symbol] = {
                'order_id': order.id,
                'timestamp': now
            }
            
            logger.info(f"✅ SAFETY LIMIT BUY order PLACED for {symbol}:")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Quantity: {order_quantity:.8f}")
            logger.info(f"   Limit Price: ${limit_price:,.4f}")
            logger.info(f"   Time in Force: GTC")
            logger.info(f"   🛡️ Safety Order #{latest_cycle.safety_orders + 1} triggered by {price_drop_pct:.2f}% price drop")
            # NOTE: We do NOT update the cycle here - that's TradingStream's job when it fills
        else:
            logger.error(f"❌ Failed to place safety order for {symbol}")
            
    except Exception as e:
        logger.error(f"Error in check_and_place_safety_order for {symbol}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


def check_and_place_take_profit_order(quote):
    """
    Check if conditions are met to place a take-profit order and place it if so.
    
    This function runs in a separate thread to avoid blocking the WebSocket.
    Take-profit orders are placed when:
    - Cycle status is 'watching' AND quantity > 0 (position exists)
    - Safety order conditions are NOT met (price hasn't dropped enough)
    - Current bid price >= take-profit trigger price (average_purchase_price * (1 + take_profit_percent/100))
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    global recent_orders
    symbol = quote.symbol
    ask_price = quote.ask_price
    bid_price = quote.bid_price
    
    try:
        # Step 1: Check for recent orders to prevent duplicates
        now = datetime.now()
        recent_order_cooldown = int(os.getenv('ORDER_COOLDOWN_SECONDS', '5'))  # Default 5 seconds
        
        if symbol in recent_orders:
            time_since_order = now - recent_orders[symbol]['timestamp']
            if time_since_order.total_seconds() < recent_order_cooldown:
                logger.debug(f"Skipping take-profit for {symbol} - recent order placed {time_since_order.total_seconds():.1f}s ago")
                return
        
        # Step 2: Get asset configuration
        asset_config = get_asset_config(symbol)
        if not asset_config:
            # Asset not configured - skip silently
            return
        
        if not asset_config.is_enabled:
            logger.debug(f"Asset {symbol} is disabled, skipping take-profit check")
            return
        
        # Step 3: Get latest cycle for this asset
        latest_cycle = get_latest_cycle(asset_config.id)
        if not latest_cycle:
            logger.debug(f"No cycle found for asset {symbol}, skipping take-profit check")
            return
        
        # Step 4: Check if cycle is in 'watching' status with quantity > 0 (existing position)
        if latest_cycle.status != 'watching':
            logger.debug(f"Asset {symbol} cycle status is '{latest_cycle.status}', not 'watching' - skipping take-profit")
            return
        
        if latest_cycle.quantity <= Decimal('0'):
            logger.debug(f"Asset {symbol} cycle has quantity {latest_cycle.quantity}, not > 0 - skipping take-profit")
            return
        
        # Step 5: Check if we have valid average_purchase_price for take-profit calculation
        if latest_cycle.average_purchase_price is None or latest_cycle.average_purchase_price <= Decimal('0'):
            logger.debug(f"Asset {symbol} has invalid average_purchase_price {latest_cycle.average_purchase_price} - cannot calculate take-profit")
            return
        
        # Step 6: Check safety order conditions are NOT met (we don't want to sell if we should be buying more)
        # Only check if we have last_order_fill_price and haven't reached max safety orders
        safety_order_would_trigger = False
        
        if (latest_cycle.last_order_fill_price is not None and 
            latest_cycle.safety_orders < asset_config.max_safety_orders):
            
            safety_deviation_decimal = asset_config.safety_order_deviation / Decimal('100')
            safety_trigger_price = latest_cycle.last_order_fill_price * (Decimal('1') - safety_deviation_decimal)
            ask_price_decimal = Decimal(str(ask_price))
            
            if ask_price_decimal <= safety_trigger_price:
                safety_order_would_trigger = True
                logger.debug(f"Safety order would trigger for {symbol} (ask ${ask_price} <= trigger ${safety_trigger_price:.4f}) - skipping take-profit")
                return
        
        # Step 7: Calculate take-profit trigger price
        take_profit_percent_decimal = asset_config.take_profit_percent / Decimal('100')  # Convert % to decimal
        take_profit_trigger_price = latest_cycle.average_purchase_price * (Decimal('1') + take_profit_percent_decimal)
        
        # Convert bid_price to Decimal for consistent calculations
        bid_price_decimal = Decimal(str(bid_price))
        
        logger.debug(f"Take-profit conditions for {symbol}:")
        logger.debug(f"   Status: {latest_cycle.status} | Quantity: {latest_cycle.quantity}")
        logger.debug(f"   Average Purchase Price: ${latest_cycle.average_purchase_price}")
        logger.debug(f"   Take Profit %: {asset_config.take_profit_percent}%")
        logger.debug(f"   Take Profit Trigger: ${take_profit_trigger_price:.4f}")
        logger.debug(f"   Current Bid: ${bid_price}")
        logger.debug(f"   Safety Order Would Trigger: {safety_order_would_trigger}")
        
        # Step 8: Check if current bid price has risen enough to trigger take-profit
        if bid_price_decimal < take_profit_trigger_price:
            logger.debug(f"Bid price ${bid_price} < take-profit trigger ${take_profit_trigger_price:.4f} - no take-profit needed")
            return
        
        logger.info(f"💰 Take-profit conditions met for {symbol}!")
        
        # Step 9: Validate market data
        if not bid_price or bid_price <= 0:
            logger.error(f"Invalid bid price for take-profit {symbol}: {bid_price}")
            return
        
        # Step 10: Initialize Alpaca client 
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for take-profit {symbol}")
            return
        
        # Step 11: Use the full cycle quantity for take-profit (sell entire position)
        sell_quantity = float(latest_cycle.quantity)
        
        # Validate calculated values before placing order
        if not sell_quantity or sell_quantity <= 0:
            logger.error(f"Invalid sell quantity for take-profit {symbol}: {sell_quantity}")
            return
        
        # Enhanced logging for take-profit order
        price_gain = bid_price_decimal - latest_cycle.average_purchase_price
        price_gain_pct = (price_gain / latest_cycle.average_purchase_price) * Decimal('100')
        estimated_proceeds = bid_price_decimal * latest_cycle.quantity
        estimated_cost = latest_cycle.average_purchase_price * latest_cycle.quantity
        estimated_profit = estimated_proceeds - estimated_cost
        
        logger.info(f"📊 Take-Profit Analysis for {symbol}:")
        logger.info(f"   Avg Purchase: ${latest_cycle.average_purchase_price:.4f} | Current Bid: ${bid_price:,.4f}")
        logger.info(f"   Price Gain: ${price_gain:.4f} ({price_gain_pct:.2f}%)")
        logger.info(f"   Take-Profit Trigger: ${take_profit_trigger_price:.4f} ({asset_config.take_profit_percent}% gain)")
        logger.info(f"   Position: {latest_cycle.quantity} {symbol.split('/')[0]}")
        logger.info(f"   Est. Proceeds: ${estimated_proceeds:.2f} | Est. Cost: ${estimated_cost:.2f}")
        logger.info(f"   Est. Profit: ${estimated_profit:.2f}")
        
        # Step 12: Place the market sell order
        logger.info(f"🔄 Placing MARKET SELL order for {symbol}:")
        logger.info(f"   Type: MARKET | Side: SELL | Order Type: TAKE-PROFIT")
        logger.info(f"   Quantity: {sell_quantity:.8f}")
        logger.info(f"   Current Bid: ${bid_price:,.4f}")
        logger.info(f"   💰 Selling entire position at market price")
        
        order = place_market_sell_order(
            client=client,
            symbol=symbol,
            qty=sell_quantity,
            time_in_force='gtc'  # Crypto market orders require 'gtc'
        )
        
        if order:
            # Track this order to prevent duplicates
            recent_orders[symbol] = {
                'order_id': order.id,
                'timestamp': now
            }
            
            logger.info(f"✅ MARKET SELL order PLACED for {symbol}:")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Quantity: {sell_quantity:.8f}")
            logger.info(f"   Order Type: MARKET")
            logger.info(f"   💰 Take-profit triggered by {price_gain_pct:.2f}% gain")
            # NOTE: We do NOT update the cycle here - that's TradingStream's job when it fills
        else:
            logger.error(f"❌ Failed to place take-profit order for {symbol}")
            
    except Exception as e:
        logger.error(f"Error in check_and_place_take_profit_order for {symbol}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


async def on_crypto_trade(trade):
    """
    Handler for cryptocurrency trade updates.
    
    Args:
        trade: Trade object from Alpaca containing trade data
    """
    logger.info(f"Trade: {trade.symbol} - Price: ${trade.price}, Size: {trade.size}, "
               f"Time: {trade.timestamp}")


async def on_crypto_bar(bar):
    """
    Handler for cryptocurrency bar updates (OHLCV data).
    
    Args:
        bar: Bar object from Alpaca containing OHLCV data
    """
    logger.info(f"Bar: {bar.symbol} - Open: ${bar.open}, High: ${bar.high}, "
               f"Low: ${bar.low}, Close: ${bar.close}, Volume: {bar.volume}")


async def on_trade_update(trade_update):
    """
    Handler for account trade updates (order fills, cancellations, etc.).
    
    Args:
        trade_update: TradeUpdate object from Alpaca
    """
    order = trade_update.order
    event = trade_update.event
    
    logger.info(f"📨 Trade Update: {event.upper()} - {order.symbol}")
    logger.info(f"   Order ID: {order.id}")
    logger.info(f"   Side: {order.side.upper()} | Type: {order.order_type.upper() if hasattr(order, 'order_type') else 'UNKNOWN'}")
    logger.info(f"   Status: {order.status.upper()}")
    
    if hasattr(order, 'qty') and order.qty:
        logger.info(f"   Quantity: {order.qty}")
    
    if hasattr(order, 'limit_price') and order.limit_price:
        # Safely handle limit_price - it might be a string
        try:
            limit_price_float = float(order.limit_price)
            logger.info(f"   Limit Price: ${limit_price_float:,.4f}")
        except (ValueError, TypeError):
            logger.info(f"   Limit Price: {order.limit_price}")
    
    # Enhanced execution details for fills
    if hasattr(trade_update, 'execution_id') and trade_update.execution_id:
        price = getattr(trade_update, 'price', None) 
        qty = getattr(trade_update, 'qty', None)
        
        if price is not None and qty is not None:
            try:
                price_float = float(price)
                qty_float = float(qty)
                total_value = price_float * qty_float
                
                logger.info(f"💰 EXECUTION DETAILS:")
                logger.info(f"   Execution ID: {trade_update.execution_id}")
                logger.info(f"   Fill Price: ${price_float:,.4f}")
                logger.info(f"   Fill Quantity: {qty_float}")
                logger.info(f"   Fill Value: ${total_value:,.2f}")
                
                # Show performance vs limit price if available
                if hasattr(order, 'limit_price') and order.limit_price:
                    try:
                        limit_price_float = float(order.limit_price)
                        price_diff = price_float - limit_price_float
                        if order.side.lower() == 'buy':
                            performance = "BETTER" if price_diff < 0 else "WORSE" if price_diff > 0 else "EXACT"
                            logger.info(f"   vs Limit: {performance} (${price_diff:+.4f})")
                    except (ValueError, TypeError):
                        logger.info(f"   vs Limit: Unable to compare (limit price: {order.limit_price})")
            except (ValueError, TypeError):
                logger.info(f"💰 EXECUTION DETAILS:")
                logger.info(f"   Execution ID: {trade_update.execution_id}")
                logger.info(f"   Fill Price: {price}")
                logger.info(f"   Fill Quantity: {qty}")
                logger.info(f"   Fill Value: Unable to calculate")
        else:
            logger.info(f"   Execution ID: {trade_update.execution_id} (price/qty data pending)")
    
    # Enhanced logic for different event types
    if event == 'partial_fill':
        # NEW: Only log partial fills, no database updates
        logger.info(f"📊 PARTIAL FILL: {order.symbol} order {order.id}")
        if hasattr(order, 'filled_qty') and hasattr(order, 'filled_avg_price'):
            logger.info(f"   Filled Qty: {order.filled_qty}")
            logger.info(f"   Filled Avg Price: ${order.filled_avg_price}")
        logger.info("   ℹ️ No database updates for partial fills - waiting for final fill or cancellation")
        
    elif event == 'fill':
        logger.info(f"🎯 ORDER FILLED SUCCESSFULLY for {order.symbol}!")
        
        # Phase 7: Update dca_cycles table on BUY order fills
        if order.side.lower() == 'buy':
            await update_cycle_on_buy_fill(order, trade_update)
        
        # Phase 8: Process SELL order fills (take-profit completion)
        elif order.side.lower() == 'sell':
            await update_cycle_on_sell_fill(order, trade_update)
    
    # Phase 9: Handle order cancellations, rejections, and expirations
    elif event in ('canceled', 'cancelled', 'rejected', 'expired'):
        logger.info(f"⚠️ ORDER {event.upper()}: {order.symbol} order {order.id}")
        await update_cycle_on_order_cancellation(order, event)


async def update_cycle_on_buy_fill(order, trade_update):
    """
    Update dca_cycles table when a BUY order fills.
    
    This is Phase 7 functionality - updating the database state 
    when base orders or safety orders fill.
    
    Args:
        order: The filled order object
        trade_update: The trade update containing execution details
    """
    try:
        symbol = order.symbol
        order_id = order.id
        
        logger.info(f"🔄 Updating cycle database for {symbol} BUY fill...")
        
        # Step 1: Find the cycle by latest_order_id (Phase 7 requirement)
        cycle_query = """
        SELECT id, asset_id, status, quantity, average_purchase_price, 
               safety_orders, latest_order_id, last_order_fill_price,
               completed_at, created_at, updated_at
        FROM dca_cycles 
        WHERE latest_order_id = %s
        """
        
        cycle_result = execute_query(cycle_query, (str(order_id),), fetch_one=True)
        if not cycle_result:
            logger.error(f"❌ Cannot update cycle: No cycle found with latest_order_id={order_id} for {symbol}")
            return
        
        # Convert to cycle object for easier access
        from models.cycle_data import DcaCycle
        latest_cycle = DcaCycle.from_dict(cycle_result)
        
        # Step 2: Get the asset configuration for validation
        asset_config_query = """
        SELECT asset_symbol, take_profit_percent 
        FROM dca_assets 
        WHERE id = %s
        """
        
        asset_result = execute_query(asset_config_query, (latest_cycle.asset_id,), fetch_one=True)
        if not asset_result:
            logger.error(f"❌ Cannot update cycle: No asset config found for asset_id={latest_cycle.asset_id}")
            return
        
        # Verify symbol matches
        if asset_result['asset_symbol'] != symbol:
            logger.error(f"❌ Symbol mismatch: cycle asset={asset_result['asset_symbol']}, order symbol={symbol}")
            return
        
        # Step 3: Extract fill details using Phase 7 specifications
        filled_qty = None
        avg_fill_price = None
        
        # Use order.filled_qty and order.filled_avg_price as per Phase 7 specs
        if hasattr(order, 'filled_qty') and order.filled_qty:
            try:
                filled_qty = Decimal(str(order.filled_qty))
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.error(f"❌ Cannot parse filled_qty from order: {order.filled_qty}")
                return
        
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            try:
                avg_fill_price = Decimal(str(order.filled_avg_price))
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.error(f"❌ Cannot parse filled_avg_price from order: {order.filled_avg_price}")
                return
        
        # Fallback to trade_update execution details if order fields not available
        if filled_qty is None and hasattr(trade_update, 'qty') and trade_update.qty:
            try:
                filled_qty = Decimal(str(trade_update.qty))
                logger.info(f"Using trade_update qty as fallback: {filled_qty}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.warning(f"Could not parse qty from trade_update: {trade_update.qty}")
        
        if avg_fill_price is None and hasattr(trade_update, 'price') and trade_update.price:
            try:
                avg_fill_price = Decimal(str(trade_update.price))
                logger.info(f"Using trade_update price as fallback: ${avg_fill_price}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.warning(f"Could not parse price from trade_update: {trade_update.price}")
        
        # Final validation
        if filled_qty is None or avg_fill_price is None:
            logger.error(f"❌ Cannot update cycle: Missing fill data (filled_qty={filled_qty}, avg_fill_price={avg_fill_price})")
            return
        
        if filled_qty <= 0 or avg_fill_price <= 0:
            logger.error(f"❌ Invalid fill data: filled_qty={filled_qty}, avg_fill_price={avg_fill_price}")
            return
        
        # Step 4: Get Alpaca TradingClient and fetch current position (NEW ENHANCEMENT)
        client = get_trading_client()
        if not client:
            logger.error(f"❌ Cannot get Alpaca client for position sync")
            return
        
        # Fetch current Alpaca position to sync quantity and average price
        alpaca_position = get_alpaca_position_by_symbol(client, symbol)
        
        # Step 5: Determine if this was a safety order (before position sync)
        current_qty = latest_cycle.quantity
        is_safety_order = current_qty > Decimal('0')  # If we already had quantity, this is a safety order
        
        # Step 6: Prepare updates dictionary with Alpaca position sync (ENHANCED)
        if alpaca_position:
            # Use Alpaca as source of truth for quantity and average price
            alpaca_qty = Decimal(str(alpaca_position.qty))
            alpaca_avg_price = Decimal(str(alpaca_position.avg_entry_price))
            
            logger.info(f"📊 Syncing with Alpaca position: {alpaca_qty} @ ${alpaca_avg_price:.4f}")
            
            updates = {
                'quantity': alpaca_qty,
                'average_purchase_price': alpaca_avg_price,
                'last_order_fill_price': avg_fill_price,
                'status': 'watching',
                'latest_order_id': None  # Clear latest_order_id since order is filled
            }
        else:
            # Fallback: Use event data if Alpaca position not found
            logger.warning(f"⚠️ No Alpaca position found for {symbol}, using event data as fallback")
            
            current_avg_price = latest_cycle.average_purchase_price
            current_total_qty = current_qty + filled_qty
            
            # Calculate new weighted average purchase price (fallback formula)
            if current_total_qty > 0:
                if current_qty == 0:
                    # First purchase (base order) - use fill price as average
                    new_average_purchase_price = avg_fill_price
                else:
                    # Weighted average: ((old_qty * old_price) + (new_qty * new_price)) / total_qty
                    total_cost = (current_avg_price * current_qty) + (avg_fill_price * filled_qty)
                    new_average_purchase_price = total_cost / current_total_qty
            else:
                # Fallback (shouldn't happen with valid data)
                new_average_purchase_price = avg_fill_price
            
            updates = {
                'quantity': current_total_qty,
                'average_purchase_price': new_average_purchase_price,
                'last_order_fill_price': avg_fill_price,
                'status': 'watching',
                'latest_order_id': None  # Clear latest_order_id since order is filled
            }
        
        # Increment safety_orders count if this was a safety order (Phase 7 requirement)
        if is_safety_order:
            updates['safety_orders'] = latest_cycle.safety_orders + 1
        
        # Step 7: Update the cycle in database
        update_success = update_cycle(latest_cycle.id, updates)
        
        if update_success:
            final_safety_orders = latest_cycle.safety_orders + (1 if is_safety_order else 0)
            final_quantity = updates['quantity']
            final_avg_price = updates['average_purchase_price']
            
            logger.info(f"✅ Cycle database updated successfully for {symbol}:")
            logger.info(f"   🔄 Total Quantity: {final_quantity}")
            logger.info(f"   💰 Avg Purchase Price: ${final_avg_price:.4f}")
            logger.info(f"   📊 Last Fill Price: ${avg_fill_price:.4f}")
            logger.info(f"   🛡️ Safety Orders: {final_safety_orders}")
            logger.info(f"   📈 Order Type: {'Safety Order' if is_safety_order else 'Base Order'}")
            logger.info(f"   ⚡ Status: watching (ready for take-profit)")
            logger.info(f"   🔗 Alpaca Sync: {'✅ Position synced' if alpaca_position else '⚠️ Fallback used'}")
            
            # Lifecycle marker: Log cycle start/continuation
            if not is_safety_order:
                logger.info(f"🚀 CYCLE_START: {symbol} - New DCA cycle initiated with base order")
            else:
                logger.info(f"🔄 CYCLE_CONTINUE: {symbol} - Safety order #{final_safety_orders} added to active cycle")
        else:
            logger.error(f"❌ Failed to update cycle database for {symbol}")
            logger.error(f"❌ CYCLE_ERROR: {symbol} - Failed to update cycle after buy fill")
            
    except Exception as e:
        logger.error(f"❌ Error updating cycle on BUY fill for {order.symbol}: {e}")
        logger.exception("Full traceback:")


def get_alpaca_position_by_symbol(client: TradingClient, symbol: str) -> Optional:
    """
    Get a specific position by symbol from Alpaca.
    
    Args:
        client: Initialized TradingClient
        symbol: Asset symbol (e.g., 'BTC/USD')
        
    Returns:
        Position object if found, None if no position or error
    """
    try:
        positions = get_positions(client)
        for position in positions:
            if position.symbol == symbol and float(position.qty) != 0:
                logger.debug(f"Found Alpaca position for {symbol}: {position.qty} @ ${position.avg_entry_price}")
                return position
        
        logger.debug(f"No Alpaca position found for {symbol}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching Alpaca position for {symbol}: {e}")
        return None


async def update_cycle_on_sell_fill(order, trade_update):
    """
    Update dca_cycles table when a SELL order fills.
    
    This is Phase 8 functionality - processing take-profit order fills.
    When a SELL order fills:
    1. Mark current cycle as 'complete' with completed_at timestamp
    2. Update dca_assets.last_sell_price with the fill price
    3. Create new 'cooldown' cycle for the same asset
    
    Args:
        order: The filled order object
        trade_update: The trade update containing execution details
    """
    try:
        symbol = order.symbol
        order_id = order.id
        
        logger.info(f"🔄 Processing take-profit SELL fill for {symbol}...")
        
        # Step 1: Find the cycle by latest_order_id
        cycle_query = """
        SELECT id, asset_id, status, quantity, average_purchase_price, 
               safety_orders, latest_order_id, last_order_fill_price,
               completed_at, created_at, updated_at
        FROM dca_cycles 
        WHERE latest_order_id = %s
        """
        
        cycle_result = execute_query(cycle_query, (str(order_id),), fetch_one=True)
        if not cycle_result:
            logger.error(f"❌ Cannot process SELL fill: No cycle found with latest_order_id={order_id} for {symbol}")
            return
        
        # Convert to cycle object for easier access
        from models.cycle_data import DcaCycle
        current_cycle = DcaCycle.from_dict(cycle_result)
        
        # Step 2: Get the asset configuration 
        asset_config = get_asset_config(symbol)
        if not asset_config:
            logger.error(f"❌ Cannot process SELL fill: No asset config found for {symbol}")
            return
        
        # Step 3: Extract fill price from order
        avg_fill_price = None
        
        # Use order.filled_avg_price as per Phase 8 specs
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            try:
                avg_fill_price = Decimal(str(order.filled_avg_price))
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.error(f"❌ Cannot parse filled_avg_price from order: {order.filled_avg_price}")
                return
        
        # Fallback to trade_update execution details if order fields not available
        if avg_fill_price is None and hasattr(trade_update, 'price') and trade_update.price:
            try:
                avg_fill_price = Decimal(str(trade_update.price))
                logger.info(f"Using trade_update price as fallback: ${avg_fill_price}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.warning(f"Could not parse price from trade_update: {trade_update.price}")
        
        # Final validation
        if avg_fill_price is None:
            logger.error(f"❌ Cannot process SELL fill: Missing fill price data")
            return
        
        if avg_fill_price <= 0:
            logger.error(f"❌ Invalid fill price: {avg_fill_price}")
            return
        
        logger.info(f"💰 Take-profit SELL filled at ${avg_fill_price:.4f}")
        
        # Step 3.5: Verify Alpaca position (optional but good for logging/verification)
        client = get_trading_client()
        if client:
            alpaca_position = get_alpaca_position_by_symbol(client, symbol)
            if alpaca_position:
                logger.info(f"📊 Alpaca position after sell: {alpaca_position.qty} @ ${alpaca_position.avg_entry_price}")
            else:
                logger.info(f"📊 No Alpaca position found for {symbol} (expected after complete sell)")
        
        # Step 4: Update current cycle to 'complete' status
        from datetime import datetime
        from models.cycle_data import update_cycle
        
        updates_current = {
            'status': 'complete',
            'completed_at': datetime.utcnow(),
            'latest_order_id': None
        }
        
        update_success = update_cycle(current_cycle.id, updates_current)
        if not update_success:
            logger.error(f"❌ Failed to mark cycle {current_cycle.id} as complete")
            return
        
        logger.info(f"✅ Cycle {current_cycle.id} marked as complete")
        
        # Calculate profit for lifecycle marker
        profit_amount = avg_fill_price - current_cycle.average_purchase_price
        profit_percent = (profit_amount / current_cycle.average_purchase_price) * 100
        total_profit = profit_amount * current_cycle.quantity
        
        # Lifecycle marker: Log cycle completion
        logger.info(f"✅ CYCLE_COMPLETE: {symbol} - Profit: ${total_profit:.2f} ({profit_percent:.2f}%)")
        
        # Calculate profit for lifecycle marker
        profit_amount = avg_fill_price - current_cycle.average_purchase_price
        profit_percent = (profit_amount / current_cycle.average_purchase_price) * 100
        total_profit = profit_amount * current_cycle.quantity
        
        # Lifecycle marker: Log cycle completion
        logger.info(f"✅ CYCLE_COMPLETE: {symbol} - Profit: ${total_profit:.2f} ({profit_percent:.2f}%)")
        
        # Step 5: Update dca_assets.last_sell_price
        asset_update_success = update_asset_config(asset_config.id, {'last_sell_price': avg_fill_price})
        if not asset_update_success:
            logger.error(f"❌ Failed to update last_sell_price for asset {asset_config.id}")
            return
        
        logger.info(f"✅ Updated {symbol} last_sell_price to ${avg_fill_price:.4f}")
        
        # Step 6: Create new 'cooldown' cycle
        new_cooldown_cycle = create_cycle(
            asset_id=asset_config.id,
            status='cooldown',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            last_order_fill_price=None,
            completed_at=None
        )
        
        if not new_cooldown_cycle:
            logger.error(f"❌ Failed to create new cooldown cycle for {symbol}")
            return
        
        logger.info(f"✅ Created new cooldown cycle {new_cooldown_cycle.id} for {symbol}")
        
        # Step 7: Log completion summary
        logger.info(f"🎉 TAKE-PROFIT COMPLETED for {symbol}:")
        logger.info(f"   💰 Sell Price: ${avg_fill_price:.4f}")
        logger.info(f"   📈 Avg Purchase Price: ${current_cycle.average_purchase_price:.4f}")
        profit_amount = avg_fill_price - current_cycle.average_purchase_price
        profit_percent = (profit_amount / current_cycle.average_purchase_price) * 100
        logger.info(f"   💵 Profit per unit: ${profit_amount:.4f} ({profit_percent:.2f}%)")
        logger.info(f"   🔄 Previous Cycle: {current_cycle.id} (complete)")
        logger.info(f"   ❄️  New Cooldown Cycle: {new_cooldown_cycle.id}")
        logger.info(f"   ⏱️  Cooldown Period: {asset_config.cooldown_period} seconds")
        
        logger.info(f"✅ Phase 8 SELL fill processing completed successfully for {symbol}")
        
    except Exception as e:
        logger.error(f"❌ Error processing SELL fill for {order.symbol}: {e}")
        logger.error(f"❌ CYCLE_ERROR: {order.symbol} - Failed to process sell fill: {e}")
        logger.error(f"❌ CYCLE_ERROR: {order.symbol} - Failed to process sell fill: {e}")
        logger.exception("Full traceback:")


async def update_cycle_on_order_cancellation(order, event):
    """
    Update dca_cycles table when an order is canceled, rejected, or expired.
    
    This is Phase 9 functionality - handling order lifecycle events that 
    require reverting active cycles back to 'watching' status.
    
    Args:
        order: The canceled/rejected/expired order object
        event: The event type ('canceled', 'rejected', 'expired')
    """
    try:
        symbol = order.symbol
        order_id = order.id
        
        logger.info(f"🔄 Processing {event} order event for {symbol}...")
        
        # Step 1: Try to find the cycle linked to this order
        cycle_query = """
        SELECT id, asset_id, status, quantity, average_purchase_price, 
               safety_orders, latest_order_id, last_order_fill_price,
               completed_at, created_at, updated_at
        FROM dca_cycles 
        WHERE latest_order_id = %s
        """
        
        cycle_result = execute_query(cycle_query, (str(order_id),), fetch_one=True)
        
        if not cycle_result:
            # No cycle found - this is an orphan order (expected scenario)
            logger.warning(f"⚠️ Received {event} for order {order_id} not actively tracked or already processed. "
                          f"Ignoring DB update for this event.")
            return
        
        # Convert to cycle object for easier access
        from models.cycle_data import DcaCycle
        cycle = DcaCycle.from_dict(cycle_result)
        
        # Step 2: Check if the cycle is in an active order state
        if cycle.status not in ('buying', 'selling'):
            logger.info(f"ℹ️ Order {order_id} for cycle {cycle.id} was {event}, but cycle status is '{cycle.status}' "
                       f"(not 'buying' or 'selling'). No action needed.")
            return
        
        # Step 3: Enhanced cancellation handling with Alpaca position sync (for BUY orders)
        from models.cycle_data import update_cycle
        
        if order.side.lower() == 'buy':
            # For BUY order cancellations, sync with Alpaca position
            logger.info(f"🔄 Processing BUY order {event} with Alpaca position sync...")
            
            # Get Alpaca client and fetch current position
            client = get_trading_client()
            alpaca_position = None
            if client:
                alpaca_position = get_alpaca_position_by_symbol(client, symbol)
            
            # Extract partial fill details if available
            order_filled_qty = Decimal('0')
            order_filled_avg_price = None
            
            if hasattr(order, 'filled_qty') and order.filled_qty:
                try:
                    order_filled_qty = Decimal(str(order.filled_qty))
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_qty from canceled order: {order.filled_qty}")
            
            if hasattr(order, 'filled_avg_price') and order.filled_avg_price and order_filled_qty > 0:
                try:
                    order_filled_avg_price = Decimal(str(order.filled_avg_price))
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_avg_price from canceled order: {order.filled_avg_price}")
            
            # Prepare updates with Alpaca position sync
            updates = {
                'status': 'watching',
                'latest_order_id': None
            }
            
            if alpaca_position:
                # Use Alpaca as source of truth for quantity and average price
                alpaca_qty = Decimal(str(alpaca_position.qty))
                alpaca_avg_price = Decimal(str(alpaca_position.avg_entry_price))
                
                logger.info(f"📊 Syncing with Alpaca position after {event}: {alpaca_qty} @ ${alpaca_avg_price:.4f}")
                
                updates['quantity'] = alpaca_qty
                updates['average_purchase_price'] = alpaca_avg_price
                
                # Update last_order_fill_price if there was a partial fill
                if order_filled_qty > 0 and order_filled_avg_price:
                    updates['last_order_fill_price'] = order_filled_avg_price
                    
                    # Determine if this was a safety order and increment count
                    original_qty = cycle.quantity
                    if original_qty > Decimal('0'):
                        updates['safety_orders'] = cycle.safety_orders + 1
                        logger.info(f"📊 Partial fill on safety order - incrementing count to {cycle.safety_orders + 1}")
                
            else:
                # Fallback: Use current cycle data if Alpaca position not found
                logger.warning(f"⚠️ No Alpaca position found for {symbol} after {event}, using current cycle data")
                
                # Still update last_order_fill_price if there was a partial fill
                if order_filled_qty > 0 and order_filled_avg_price:
                    updates['last_order_fill_price'] = order_filled_avg_price
                    
                    # Determine if this was a safety order and increment count
                    original_qty = cycle.quantity
                    if original_qty > Decimal('0'):
                        updates['safety_orders'] = cycle.safety_orders + 1
                        logger.info(f"📊 Partial fill on safety order - incrementing count to {cycle.safety_orders + 1}")
            
            # Log partial fill details if applicable
            if order_filled_qty > 0:
                logger.info(f"📊 Canceled order had partial fill: {order_filled_qty} @ ${order_filled_avg_price:.4f}")
            
        else:
            # For SELL order cancellations, simple revert to watching
            updates = {
                'status': 'watching',
                'latest_order_id': None
            }
        
        success = update_cycle(cycle.id, updates)
        
        if success:
            logger.info(f"✅ Order {order_id} for cycle {cycle.id} was {event}. "
                       f"Cycle status set to watching.")
            logger.info(f"🔄 Cycle {cycle.id} ({symbol}) reverted to 'watching' status - ready for new orders")
            
            if order.side.lower() == 'buy' and alpaca_position:
                logger.info(f"   🔗 Alpaca Sync: ✅ Position synced after {event}")
            elif order.side.lower() == 'buy':
                logger.info(f"   🔗 Alpaca Sync: ⚠️ Fallback used after {event}")
        else:
            logger.error(f"❌ Failed to update cycle {cycle.id} after {event} order {order_id}")
        
    except Exception as e:
        logger.error(f"❌ Error processing {event} order event for {order.symbol}: {e}")
        logger.exception("Full traceback:")


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        global shutdown_requested, crypto_stream_ref, trading_stream_ref
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_requested = True
        
        # Try to stop the streams immediately using their internal mechanisms
        if crypto_stream_ref:
            try:
                logger.info("Stopping CryptoDataStream...")
                # Use the stream's internal stop method if available
                if hasattr(crypto_stream_ref, '_should_run'):
                    crypto_stream_ref._should_run = False
                if hasattr(crypto_stream_ref, '_ws') and crypto_stream_ref._ws:
                    try:
                        crypto_stream_ref._ws.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error stopping CryptoDataStream: {e}")
        
        if trading_stream_ref:
            try:
                logger.info("Stopping TradingStream...")
                # Use the stream's internal stop method if available
                if hasattr(trading_stream_ref, '_should_run'):
                    trading_stream_ref._should_run = False
                if hasattr(trading_stream_ref, '_ws') and trading_stream_ref._ws:
                    try:
                        trading_stream_ref._ws.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error stopping TradingStream: {e}")
        
        logger.info("Shutdown signal processed - streams should stop immediately")
        
        # Reduce force exit timeout since we're being more aggressive
        import threading
        def force_exit():
            import time
            time.sleep(2)  # Give only 2 seconds for cleanup
            if shutdown_requested:
                logger.warning("Forcing immediate exit...")
                os._exit(0)
        
        threading.Thread(target=force_exit, daemon=True).start()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def setup_crypto_stream() -> CryptoDataStream:
    """
    Setup and configure the CryptoDataStream for market data.
    
    Returns:
        Configured CryptoDataStream instance
    """
    api_key = os.getenv('APCA_API_KEY_ID')
    api_secret = os.getenv('APCA_API_SECRET_KEY')
    
    # Determine if using paper trading based on base URL
    base_url = os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    paper = 'paper-api' in base_url
    
    logger.info(f"Setting up CryptoDataStream (paper={paper})")
    
    # Initialize crypto stream
    stream = CryptoDataStream(
        api_key=api_key,
        secret_key=api_secret
    )
    
    # List of most popular crypto pairs to monitor (limited to avoid symbol limit)
    crypto_symbols = [
        'BTC/USD',   # Bitcoin
        'ETH/USD',   # Ethereum
        'SOL/USD',   # Solana
        'DOGE/USD',  # Dogecoin
        'AVAX/USD',  # Avalanche
        'LINK/USD',  # Chainlink
        'UNI/USD',   # Uniswap
        'XRP/USD'    # Ripple
    ]
    
    # Subscribe to quotes and trades for selected crypto symbols
    for symbol in crypto_symbols:
        stream.subscribe_quotes(on_crypto_quote, symbol)
        stream.subscribe_trades(on_crypto_trade, symbol)
    
    logger.info(f"Subscribed to quotes and trades for {len(crypto_symbols)} popular crypto pairs:")
    logger.info(f"Symbols: {', '.join(crypto_symbols)}")
    
    # Optionally subscribe to bars for minute-by-minute data
    # stream.subscribe_bars(on_crypto_bar, 'BTC/USD')
    
    return stream


def setup_trading_stream() -> TradingStream:
    """
    Setup and configure the TradingStream for account updates.
    
    Returns:
        Configured TradingStream instance
    """
    api_key = os.getenv('APCA_API_KEY_ID')
    api_secret = os.getenv('APCA_API_SECRET_KEY')
    
    # Determine if using paper trading based on base URL
    base_url = os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    paper = 'paper-api' in base_url
    
    logger.info(f"Setting up TradingStream (paper={paper})")
    
    # Initialize trading stream
    stream = TradingStream(
        api_key=api_key,
        secret_key=api_secret
    )
    
    # Subscribe to trade updates
    stream.subscribe_trade_updates(on_trade_update)
    
    logger.info("Subscribed to trade updates")
    
    return stream


def main():
    """Main application entry point."""
    global shutdown_requested, crypto_stream_ref, trading_stream_ref
    
    logger.info("="*60)
    logger.info("DCA Trading Bot - Main WebSocket Application Starting")
    logger.info("="*60)
    
    # Validate environment
    if not validate_environment():
        logger.error("Environment validation failed. Exiting.")
        sys.exit(1)
    
    # Create PID file for watchdog monitoring
    create_pid_file()
    
    # Set up signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    try:
        # Setup streams
        crypto_stream_ref = setup_crypto_stream()
        trading_stream_ref = setup_trading_stream()
        
        logger.info("Starting both WebSocket streams concurrently...")
        
        # Run both streams concurrently using asyncio
        asyncio.run(run_both_streams(crypto_stream_ref, trading_stream_ref))
        
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        logger.exception("Full traceback:")
        raise
    finally:
        # Ensure streams are closed
        if crypto_stream_ref:
            try:
                crypto_stream_ref.close()
                logger.info("CryptoDataStream closed")
            except:
                pass
        
        if trading_stream_ref:
            try:
                trading_stream_ref.close()
                logger.info("TradingStream closed")
            except:
                pass
        
        # Remove PID file on shutdown
        remove_pid_file()
        
        logger.info("DCA Trading Bot - Main WebSocket Application Stopped")


async def run_both_streams(crypto_stream, trading_stream):
    """
    Run both crypto data stream and trading stream concurrently.
    
    Args:
        crypto_stream: CryptoDataStream instance
        trading_stream: TradingStream instance
    """
    global shutdown_requested
    
    logger.info("Creating concurrent tasks for both streams...")
    
    # Create tasks for both streams with shutdown monitoring
    crypto_task = asyncio.create_task(run_crypto_stream_async(crypto_stream))
    trading_task = asyncio.create_task(run_trading_stream_async(trading_stream))
    
    # Create a shutdown monitor task
    shutdown_task = asyncio.create_task(monitor_shutdown_simple(crypto_task, trading_task))
    
    try:
        # Run all tasks concurrently
        await asyncio.gather(crypto_task, trading_task, shutdown_task, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("Stream tasks cancelled")
    except Exception as e:
        logger.error(f"Error in concurrent stream execution: {e}")
    finally:
        # Ensure all tasks are cancelled
        for task in [crypto_task, trading_task, shutdown_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("All WebSocket tasks have been stopped")


async def monitor_shutdown_simple(crypto_task, trading_task):
    """
    Monitor for shutdown requests and cancel stream tasks.
    
    Args:
        crypto_task: Crypto stream asyncio task
        trading_task: Trading stream asyncio task
    """
    global shutdown_requested
    
    while not shutdown_requested:
        await asyncio.sleep(0.1)  # Check every 100ms
    
    # Shutdown was requested, cancel stream tasks immediately
    logger.info("Shutdown monitor detected shutdown request - cancelling stream tasks...")
    
    # Cancel the stream tasks - this will interrupt the executor threads
    if not crypto_task.done():
        crypto_task.cancel()
        logger.info("Cancelled CryptoDataStream task")
    
    if not trading_task.done():
        trading_task.cancel()
        logger.info("Cancelled TradingStream task")
    
    logger.info("Shutdown monitor completed - all stream tasks cancelled")


async def run_crypto_stream_async(crypto_stream):
    """
    Run crypto stream asynchronously with shutdown monitoring.
    
    Args:
        crypto_stream: CryptoDataStream instance
    """
    try:
        logger.info("Starting CryptoDataStream...")
        # Run the stream in executor - cancellation will interrupt it
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, crypto_stream.run)
    except asyncio.CancelledError:
        logger.info("CryptoDataStream task cancelled during shutdown")
    except Exception as e:
        if not shutdown_requested:
            logger.error(f"CryptoDataStream error: {e}")
    finally:
        logger.info("CryptoDataStream stopped")


async def run_trading_stream_async(trading_stream):
    """
    Run trading stream asynchronously with shutdown monitoring.
    
    Args:
        trading_stream: TradingStream instance
    """
    try:
        logger.info("Starting TradingStream...")
        # Run the stream in executor - cancellation will interrupt it
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, trading_stream.run)
    except asyncio.CancelledError:
        logger.info("TradingStream task cancelled during shutdown")
    except Exception as e:
        if not shutdown_requested:
            logger.error(f"TradingStream error: {e}")
    finally:
        logger.info("TradingStream stopped")


if __name__ == "__main__":
    main() 