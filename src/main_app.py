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
from datetime import datetime, timedelta, timezone
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
from utils.logging_config import setup_main_app_logging, get_asset_logger, log_asset_lifecycle_event
from utils.notifications import alert_order_placed, alert_order_filled, alert_system_error, alert_critical_error
from utils.discord_notifications import (
    discord_order_placed, discord_order_filled, discord_cycle_completed, 
    discord_system_error, discord_system_alert
)

# Import our database models and utilities
from utils.db_utils import get_db_connection, execute_query
from models.asset_config import get_asset_config, update_asset_config, get_all_enabled_assets
from models.cycle_data import get_latest_cycle, update_cycle, create_cycle
from utils.alpaca_client_rest import get_trading_client, place_limit_buy_order, get_positions, place_market_sell_order
from utils.formatting import format_price, format_quantity, format_percentage

# Initialize configuration and logging
config = get_config()
setup_main_app_logging(enable_asset_tracking=True)
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
    logger.debug(f"Quote: {quote.symbol} - Bid: ${quote.bid_price} @ {quote.bid_size}, Ask: ${quote.ask_price} @ {quote.ask_size}")
    
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
                return
        
        # Step 2: Get asset configuration
        asset_config = get_asset_config(symbol)
        if not asset_config:
            # Asset not configured - skip silently
            return
        
        if not asset_config.is_enabled:
            logger.debug(f"Asset {symbol} is disabled, skipping base order check")
            return
        
        # Step 3: Get latest cycle for this asset
        latest_cycle = get_latest_cycle(asset_config.id)
        if not latest_cycle:
            return
        
        # Step 4: Check if cycle is in 'watching' status with zero quantity
        if latest_cycle.status != 'watching':
            return
        
        if latest_cycle.quantity != Decimal('0'):
            return
        
        logger.info(f"Base order conditions met for {symbol} - checking Alpaca positions...")
        
        # Step 5: Initialize Alpaca client and check for existing positions
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for {symbol}")
            return
        
        # Step 6: Check for existing positions (ignore tiny positions below minimum order size)
        try:
            positions = get_positions(client)
        except APIError as e:
            logger.error(f"Alpaca API error fetching positions for {symbol}: {e}")
            return
        except Exception as e:
            logger.error(f"Unexpected error fetching positions for {symbol}: {e}")
            return
            
        existing_position = None
        min_order_qty = 0.000000002  # Alpaca's minimum order quantity for crypto
        
        # Convert symbol format for Alpaca comparison (UNI/USD -> UNIUSD)
        alpaca_symbol = symbol.replace('/', '')
        
        for position in positions:
            if position.symbol == alpaca_symbol and float(position.qty) != 0:
                position_qty = float(position.qty)
                
                # Ignore tiny positions that are below minimum order size
                if position_qty < min_order_qty:
                    logger.debug(f"Ignoring tiny position for {symbol}: {position_qty} < {min_order_qty}")
                    continue
                    
                existing_position = position
                break
        
        if existing_position:
            logger.warning(f"Base order for {symbol} skipped, existing position found on Alpaca. "
                          f"Position: {existing_position.qty} @ ${existing_position.avg_entry_price}")
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
        logger.info(f"   Bid: {format_price(bid_price)} | Ask: {format_price(ask_price)} | Spread: {format_price(spread)} ({spread_pct:.3f}%)")
        logger.info(f"   Order Amount: ${base_order_usd} ÷ {format_price(ask_price)} = {format_quantity(order_quantity)} {symbol.split('/')[0]}")
        
        # Step 9: Place the base limit buy order with detailed logging
        
        # For integration testing, use aggressive pricing to ensure fast fills
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            aggressive_price = ask_price * 1.05
            logger.info(f"🚀 TESTING MODE: Using aggressive pricing (5% above ask)")
            logger.info(f"   Ask Price: {format_price(ask_price)}")
            logger.info(f"   Aggressive Price: {format_price(aggressive_price)} (+5%)")
            limit_price = aggressive_price
        else:
            # Normal production mode: use ask price
            limit_price = ask_price
        
        logger.info(f"🔄 Placing LIMIT BUY order for {symbol}:")
        logger.info(f"   Type: LIMIT | Side: BUY")
        logger.info(f"   Limit Price: {format_price(limit_price)} {'(AGGRESSIVE +5%)' if testing_mode else '(current ask)'}")
        logger.info(f"   Quantity: {format_quantity(order_quantity)}")
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
            
            # Update cycle to 'buying' status with order details
            try:
                updates = {
                    'status': 'buying',
                    'latest_order_id': str(order.id),  # Convert UUID to string
                    'latest_order_created_at': now
                }
                update_success = update_cycle(latest_cycle.id, updates)
                if update_success:
                    logger.info(f"🔄 Updated cycle {latest_cycle.id} to 'buying' status with order {order.id}")
                else:
                    logger.warning(f"⚠️ Failed to update cycle {latest_cycle.id} with order {order.id}")
            except Exception as e:
                logger.error(f"Error updating cycle for {symbol}: {e}")
            
            logger.info(f"✅ LIMIT BUY order PLACED for {symbol}:")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Quantity: {format_quantity(order_quantity)}")
            logger.info(f"   Limit Price: {format_price(limit_price)}")
            logger.info(f"   Time in Force: GTC")
            
            # Send Discord notification for order placement
            discord_order_placed(
                asset_symbol=symbol,
                order_type="Base Order",
                order_id=str(order.id),
                quantity=float(order_quantity),
                price=float(limit_price)
            )
        else:
            logger.error(f"❌ Failed to place base order for {symbol}")
            
            # Track failed order attempts to prevent immediate retries
            recent_orders[symbol] = {
                'order_id': 'FAILED',
                'timestamp': now
            }
            
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
            return
        
        # Step 4: Check if cycle is in 'watching' status with quantity > 0 (existing position)
        if latest_cycle.status != 'watching':
            return
        
        if latest_cycle.quantity <= Decimal('0'):
            return
        
        # Step 5: Check if we can place more safety orders
        if latest_cycle.safety_orders >= asset_config.max_safety_orders:
            logger.debug(f"Asset {symbol} already at max safety orders ({latest_cycle.safety_orders}/{asset_config.max_safety_orders}) - skipping")
            return
        
        # Step 6: Check if we have a last_order_fill_price to calculate trigger from
        if latest_cycle.last_order_fill_price is None:
            return
        
        # Step 7: Calculate trigger price for safety order
        safety_deviation_decimal = asset_config.safety_order_deviation / Decimal('100')  # Convert % to decimal
        trigger_price = latest_cycle.last_order_fill_price * (Decimal('1') - safety_deviation_decimal)
        
        # Convert ask_price to Decimal for consistent calculations
        ask_price_decimal = Decimal(str(ask_price))
        
        # Step 8: Check if current ask price has dropped enough to trigger safety order
        if ask_price_decimal > trigger_price:
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
        logger.info(f"   Last Fill: {format_price(latest_cycle.last_order_fill_price)} | Current Ask: {format_price(ask_price)}")
        logger.info(f"   Price Drop: {format_price(price_drop)} ({price_drop_pct:.2f}%)")
        logger.info(f"   Trigger at: {format_price(trigger_price)} ({asset_config.safety_order_deviation}% drop)")
        logger.info(f"   Safety Orders: {latest_cycle.safety_orders + 1}/{asset_config.max_safety_orders}")
        logger.info(f"   Order Amount: ${safety_order_usd} ÷ {format_price(ask_price)} = {format_quantity(order_quantity)} {symbol.split('/')[0]}")
        
        # Step 12: Place the safety limit buy order with detailed logging
        
        # For integration testing, use aggressive pricing to ensure fast fills
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            aggressive_price = ask_price * 1.05
            logger.info(f"🚀 TESTING MODE: Using aggressive pricing (5% above ask)")
            logger.info(f"   Ask Price: {format_price(ask_price)}")
            logger.info(f"   Aggressive Price: {format_price(aggressive_price)} (+5%)")
            limit_price = aggressive_price
        else:
            # Normal production mode: use ask price
            limit_price = ask_price
        
        logger.info(f"🔄 Placing SAFETY LIMIT BUY order for {symbol}:")
        logger.info(f"   Type: LIMIT | Side: BUY | Order Type: SAFETY #{latest_cycle.safety_orders + 1}")
        logger.info(f"   Limit Price: {format_price(limit_price)} {'(AGGRESSIVE +5%)' if testing_mode else '(current ask)'}")
        logger.info(f"   Quantity: {format_quantity(order_quantity)}")
        logger.info(f"   Total Value: ${safety_order_usd}")
        
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
            
            # Update cycle to 'buying' status with order details
            try:
                updates = {
                    'status': 'buying',
                    'latest_order_id': str(order.id),  # Convert UUID to string
                    'latest_order_created_at': now
                }
                update_success = update_cycle(latest_cycle.id, updates)
                if update_success:
                    logger.info(f"🔄 Updated cycle {latest_cycle.id} to 'buying' status with safety order {order.id}")
                else:
                    logger.warning(f"⚠️ Failed to update cycle {latest_cycle.id} with safety order {order.id}")
            except mysql.connector.Error as db_err:
                logger.error(f"Database error updating cycle for safety order {symbol}: {db_err}")
            except Exception as e:
                logger.error(f"Unexpected error updating cycle for safety order {symbol}: {e}")
            
            logger.info(f"✅ SAFETY LIMIT BUY order PLACED for {symbol}:")
            logger.info(f"   Order ID: {order.id}")
            logger.info(f"   Safety Order #: {latest_cycle.safety_orders + 1}")
            logger.info(f"   Quantity: {format_quantity(order_quantity)}")
            logger.info(f"   Limit Price: {format_price(limit_price)}")
            logger.info(f"   Time in Force: GTC")
            
            # Send Discord notification for safety order placement
            discord_order_placed(
                asset_symbol=symbol,
                order_type=f"Safety Order #{latest_cycle.safety_orders + 1}",
                order_id=str(order.id),
                quantity=float(order_quantity),
                price=float(limit_price)
            )
        else:
            logger.error(f"❌ Failed to place safety order for {symbol}")
            
            # Track failed order attempts to prevent immediate retries
            recent_orders[symbol] = {
                'order_id': 'FAILED',
                'timestamp': now
            }
            
    except APIError as e:
        logger.error(f"Alpaca API error in safety order check for {symbol}: {e}")
    except mysql.connector.Error as db_err:
        logger.error(f"Database error in safety order check for {symbol}: {db_err}")
    except Exception as e:
        logger.error(f"Unexpected error in check_and_place_safety_order for {symbol}: {e}")
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
    from decimal import Decimal
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
            return

        # Step 4: Check if cycle is in valid status for take-profit/TTP processing
        # Valid statuses: 'watching' (standard TP or TTP activation) or 'trailing' (TTP active)
        if latest_cycle.status not in ['watching', 'trailing']:
            return

        if latest_cycle.quantity <= Decimal('0'):
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
            
            # Safely convert ask_price to Decimal
            try:
                ask_price_decimal = Decimal(str(ask_price))
            except (ValueError, TypeError, decimal.InvalidOperation) as e:
                logger.debug(f"Invalid ask_price for {symbol}: {ask_price} (type: {type(ask_price)}) - skipping")
                return
            
            if ask_price_decimal <= safety_trigger_price:
                safety_order_would_trigger = True
                logger.debug(f"Safety order would trigger for {symbol} (ask ${ask_price} <= trigger {format_price(safety_trigger_price)}) - skipping take-profit")
                return
        
        # Step 7: TTP-aware take-profit logic
        take_profit_percent_decimal = asset_config.take_profit_percent / Decimal('100')  # Convert % to decimal
        take_profit_trigger_price = latest_cycle.average_purchase_price * (Decimal('1') + take_profit_percent_decimal)
        
        # Convert bid_price to Decimal for consistent calculations
        bid_price_decimal = Decimal(str(bid_price))
        
        # Step 8: TTP Logic Implementation
        if not asset_config.ttp_enabled:
            # Standard take-profit logic (TTP disabled)
            if bid_price_decimal < take_profit_trigger_price:
                return
            
            logger.info(f"💰 Standard take-profit conditions met for {symbol}!")
            
        else:
            # TTP logic (TTP enabled)
            if latest_cycle.status == 'watching':
                # TTP not yet activated - check if we should activate it
                if bid_price_decimal >= take_profit_trigger_price:
                    # Activate TTP - update cycle to 'trailing' status and set initial peak
                    logger.info(f"🎯 TTP activated for {symbol}, cycle {latest_cycle.id}. Initial peak: ${bid_price}")
                    
                    updates = {
                        'status': 'trailing',
                        'highest_trailing_price': bid_price_decimal
                    }
                    
                    update_success = update_cycle(latest_cycle.id, updates)
                    if update_success:
                        logger.info(f"✅ Cycle {latest_cycle.id} updated to 'trailing' status with peak ${bid_price}")
                    else:
                        logger.error(f"❌ Failed to activate TTP for cycle {latest_cycle.id}")
                    
                    return  # Don't place sell order yet, just activated TTP
                else:
                    return
                    
            elif latest_cycle.status == 'trailing':
                # TTP is active - check for new peak or sell trigger
                current_peak = latest_cycle.highest_trailing_price or Decimal('0')
                
                if bid_price_decimal > current_peak:
                    # New peak reached - update highest_trailing_price
                    logger.info(f"🎯 TTP new peak for {symbol}, cycle {latest_cycle.id}: ${bid_price}")
                    
                    updates = {
                        'highest_trailing_price': bid_price_decimal
                    }
                    
                    update_success = update_cycle(latest_cycle.id, updates)
                    if update_success:
                        logger.debug(f"Updated highest_trailing_price to ${bid_price} for cycle {latest_cycle.id}")
                    else:
                        logger.error(f"❌ Failed to update TTP peak for cycle {latest_cycle.id}")
                    
                    return  # Don't sell yet, just updated peak
                    
                else:
                    # Check if price has dropped enough to trigger TTP sell
                    if asset_config.ttp_deviation_percent is None:
                        logger.error(f"TTP enabled for {symbol} but ttp_deviation_percent is None - cannot calculate sell trigger")
                        return
                    
                    ttp_deviation_decimal = asset_config.ttp_deviation_percent / Decimal('100')
                    ttp_sell_trigger_price = current_peak * (Decimal('1') - ttp_deviation_decimal)
                    
                    if bid_price_decimal < ttp_sell_trigger_price:
                        # TTP sell triggered!
                        logger.info(f"🎯 TTP sell triggered for {symbol}, cycle {latest_cycle.id}. Peak: ${current_peak}, Deviation: {asset_config.ttp_deviation_percent}%, Current Price: ${bid_price}")
                        logger.info(f"💰 TTP conditions met for {symbol}!")
                    else:
                        return
        
        # Step 9: Validate market data
        if not bid_price or bid_price <= 0:
            logger.error(f"Invalid bid price for take-profit {symbol}: {bid_price}")
            return
        
        # Step 10: Initialize Alpaca client 
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for take-profit {symbol}")
            return
        
        # Step 11: Get actual Alpaca position quantity for accurate sell order
        alpaca_position = get_alpaca_position_by_symbol(client, symbol)
        if not alpaca_position:
            logger.error(f"No Alpaca position found for take-profit {symbol} - cannot place sell order")
            return
        
        # Use actual Alpaca position quantity to avoid quantity mismatches
        # Handle precision issues by using the exact string value from Alpaca
        alpaca_qty_str = str(alpaca_position.qty)
        
        # For all assets, use normal float conversion
        sell_quantity = float(alpaca_qty_str)
        
        # Validate calculated values before placing order
        if not sell_quantity or sell_quantity <= 0:
            logger.error(f"Invalid sell quantity for take-profit {symbol}: {sell_quantity}")
            return
        
        # Check if quantity meets Alpaca's minimum order requirements
        min_order_qty = 0.000000002  # Alpaca's minimum order quantity for crypto
        if sell_quantity < min_order_qty:
            logger.warning(f"⚠️ Take-profit skipped for {symbol}: quantity {sell_quantity} < minimum {min_order_qty}")
            
            # Auto-reset tiny positions to unblock the cycle
            handle_tiny_position(latest_cycle, alpaca_position, symbol, bid_price_decimal)
            return
        
        # Log quantity comparison for debugging
        db_quantity = float(latest_cycle.quantity)
        if abs(sell_quantity - db_quantity) > 0.000001:  # Allow for small floating point differences
            logger.warning(f"Quantity mismatch for {symbol}: DB={format_quantity(db_quantity)}, Alpaca={format_quantity(sell_quantity)}")
            logger.info(f"Using Alpaca position quantity for accuracy: {format_quantity(sell_quantity)}")
        
        # Enhanced logging for take-profit order
        price_gain = bid_price_decimal - latest_cycle.average_purchase_price
        price_gain_pct = (price_gain / latest_cycle.average_purchase_price) * Decimal('100')
        estimated_proceeds = bid_price_decimal * latest_cycle.quantity
        estimated_cost = latest_cycle.average_purchase_price * latest_cycle.quantity
        estimated_profit = estimated_proceeds - estimated_cost
        
        # Determine order type for logging
        order_type_desc = "TTP" if asset_config.ttp_enabled else "TAKE-PROFIT"
        
        logger.info(f"📊 {order_type_desc} Analysis for {symbol}:")
        logger.info(f"   Avg Purchase: {format_price(latest_cycle.average_purchase_price)} | Current Bid: {format_price(bid_price)}")
        logger.info(f"   Price Gain: {format_price(price_gain)} ({price_gain_pct:.2f}%)")
        logger.info(f"   Take-Profit Trigger: {format_price(take_profit_trigger_price)} ({asset_config.take_profit_percent}% gain)")
        
        if asset_config.ttp_enabled and latest_cycle.status == 'trailing':
            current_peak = latest_cycle.highest_trailing_price or Decimal('0')
            ttp_deviation_decimal = asset_config.ttp_deviation_percent / Decimal('100')
            ttp_sell_trigger_price = current_peak * (Decimal('1') - ttp_deviation_decimal)
            logger.info(f"   TTP Peak: {format_price(current_peak)} | TTP Deviation: {asset_config.ttp_deviation_percent}%")
            logger.info(f"   TTP Sell Trigger: {format_price(ttp_sell_trigger_price)}")
        
        logger.info(f"   Position: {latest_cycle.quantity} {symbol.split('/')[0]}")
        logger.info(f"   Est. Proceeds: ${estimated_proceeds:.2f} | Est. Cost: ${estimated_cost:.2f}")
        logger.info(f"   Est. Profit: ${estimated_profit:.2f}")
        
        # Step 12: Place the market sell order
        logger.info(f"🔄 Placing MARKET SELL order for {symbol}:")
        logger.info(f"   Type: MARKET | Side: SELL | Order Type: {order_type_desc}")
        logger.info(f"   Quantity: {format_quantity(sell_quantity)}")
        logger.info(f"   Current Bid: {format_price(bid_price)}")
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
            logger.info(f"   Quantity: {format_quantity(sell_quantity)}")
            logger.info(f"   Order Type: MARKET")
            logger.info(f"   💰 {order_type_desc} triggered by {price_gain_pct:.2f}% gain")
            
            # NEW: Immediately update the cycle to reflect that we're actively trying to sell
            from datetime import timezone
            updates = {
                'status': 'selling',
                'latest_order_id': str(order.id),  # Convert UUID to string
                'latest_order_created_at': datetime.now(timezone.utc)
            }
            
            update_success = update_cycle(latest_cycle.id, updates)
            if update_success:
                logger.info(f"✅ Cycle {latest_cycle.id} status updated to 'selling', latest_order_id set for SELL order {order.id}")
            else:
                logger.error(f"❌ Failed to update cycle {latest_cycle.id} after placing SELL order {order.id}")
                
            # TradingStream will complete the cycle update when the order fills
        else:
            logger.error(f"❌ Failed to place take-profit order for {symbol}")
            
            # Track failed order attempts to prevent immediate retries
            recent_orders[symbol] = {
                'order_id': 'FAILED',
                'timestamp': now
            }
            
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
    # Trade data is informational only - no logging needed
    # Bot makes decisions based on quote data, not trade data
    pass


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
            logger.info(f"   Limit Price: {format_price(limit_price_float)}")
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
                logger.info(f"   Fill Price: {format_price(price_float)}")
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
        # STANDARDIZED: Only log partial fills, no database updates
        logger.info(f"📊 PARTIAL FILL: {order.symbol} order {order.id}")
        logger.info(f"   Side: {order.side.upper()}")
        
        # Log detailed partial fill information
        if hasattr(order, 'filled_qty') and order.filled_qty:
            logger.info(f"   Partially Filled Qty: {order.filled_qty}")
        
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            try:
                avg_price_float = float(order.filled_avg_price)
                logger.info(f"   Avg Fill Price: {format_price(avg_price_float)}")
            except (ValueError, TypeError):
                logger.info(f"   Avg Fill Price: {order.filled_avg_price}")
        
        # Log order status if available
        if hasattr(order, 'status') and order.status:
            logger.info(f"   Order Status: {order.status.upper()}")
            if order.status.lower() == 'partially_filled':
                logger.info(f"   📋 Order remains active with partial fill")
        
        # Log remaining quantity if available
        if hasattr(order, 'qty') and hasattr(order, 'filled_qty'):
            try:
                total_qty = float(order.qty)
                filled_qty = float(order.filled_qty)
                remaining_qty = total_qty - filled_qty
                logger.info(f"   Remaining Qty: {remaining_qty} (of {total_qty} total)")
            except (ValueError, TypeError):
                logger.info(f"   Total Qty: {order.qty}, Filled Qty: {order.filled_qty}")
        
        logger.info("   ℹ️ PARTIAL FILL: No database updates - cycle remains in current status")
        logger.info("   ⏳ Waiting for terminal event (fill/canceled) to update cycle financials")
        
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
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               highest_trailing_price, completed_at, created_at, updated_at, sell_price
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
        
        # Step 3: Extract TERMINAL fill details (order is now completely filled)
        # For terminal 'fill' events, use order.filled_avg_price as the definitive last_order_fill_price
        filled_qty = None
        avg_fill_price = None
        
        logger.info(f"📊 Processing TERMINAL FILL event - extracting definitive order data...")
        
        # Use order.filled_qty and order.filled_avg_price as definitive source for terminal fills
        if hasattr(order, 'filled_qty') and order.filled_qty:
            try:
                filled_qty = Decimal(str(order.filled_qty))
                logger.info(f"   Total Filled Qty: {filled_qty}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.error(f"❌ Cannot parse filled_qty from order: {order.filled_qty}")
                return
        
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            try:
                avg_fill_price = Decimal(str(order.filled_avg_price))
                logger.info(f"   Avg Fill Price: {format_price(avg_fill_price)} (definitive)")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.error(f"❌ Cannot parse filled_avg_price from order: {order.filled_avg_price}")
                return
        
        # Fallback to trade_update execution details if order fields not available
        if filled_qty is None and hasattr(trade_update, 'qty') and trade_update.qty:
            try:
                filled_qty = Decimal(str(trade_update.qty))
                logger.info(f"   Using trade_update qty as fallback: {filled_qty}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.warning(f"Could not parse qty from trade_update: {trade_update.qty}")
        
        if avg_fill_price is None and hasattr(trade_update, 'price') and trade_update.price:
            try:
                avg_fill_price = Decimal(str(trade_update.price))
                logger.info(f"   Using trade_update price as fallback: ${avg_fill_price}")
            except (ValueError, TypeError, decimal.InvalidOperation):
                logger.warning(f"Could not parse price from trade_update: {trade_update.price}")
        
        # Final validation
        if filled_qty is None or avg_fill_price is None:
            logger.error(f"❌ Cannot update cycle: Missing terminal fill data (filled_qty={filled_qty}, avg_fill_price={avg_fill_price})")
            return
        
        if filled_qty <= 0 or avg_fill_price <= 0:
            logger.error(f"❌ Invalid terminal fill data: filled_qty={filled_qty}, avg_fill_price={avg_fill_price}")
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
            
            logger.info(f"📊 Syncing with Alpaca position: {alpaca_qty} @ {format_price(alpaca_avg_price)}")
            
            # Check if the position quantity is too small for future take-profit orders
            min_order_qty = Decimal('0.000000002')  # Alpaca's minimum order quantity
            if alpaca_qty < min_order_qty:
                logger.warning(f"⚠️ Position quantity {alpaca_qty} is below minimum order size {min_order_qty}")
                logger.warning(f"   This position may not be sellable via take-profit orders")
            
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
            logger.info(f"   💰 Avg Purchase Price: {format_price(final_avg_price)}")
            logger.info(f"   📊 Last Fill Price: {format_price(avg_fill_price)}")
            logger.info(f"   🛡️ Safety Orders: {final_safety_orders}")
            logger.info(f"   📈 Order Type: {'Safety Order' if is_safety_order else 'Base Order'}")
            logger.info(f"   ⚡ Status: watching (ready for take-profit)")
            logger.info(f"   🔗 Alpaca Sync: {'✅ Position synced' if alpaca_position else '⚠️ Fallback used'}")
            
            # Lifecycle marker: Log cycle start/continuation
            if not is_safety_order:
                logger.info(f"🚀 CYCLE_START: {symbol} - New DCA cycle initiated with base order")
            else:
                logger.info(f"🔄 CYCLE_CONTINUE: {symbol} - Safety order #{final_safety_orders} added to active cycle")
            
            # Send Discord notification for successful order fill
            order_type = "Safety Order" if is_safety_order else "Base Order"
            discord_order_filled(
                asset_symbol=symbol,
                order_type=order_type,
                order_id=str(order_id),
                fill_price=float(avg_fill_price),
                quantity=float(filled_qty),
                is_full_fill=True
            )
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
        # Convert symbol format for Alpaca comparison (UNI/USD -> UNIUSD)
        alpaca_symbol = symbol.replace('/', '')
        
        for position in positions:
            if position.symbol == alpaca_symbol and float(position.qty) != 0:
                logger.debug(f"Found Alpaca position for {symbol}: {position.qty} @ ${position.avg_entry_price}")
                return position
        
        logger.debug(f"No Alpaca position found for {symbol}")
        return None
        
    except Exception as e:
        logger.error(f"Error fetching Alpaca position for {symbol}: {e}")
        return None


def handle_tiny_position(cycle, alpaca_position, symbol: str, current_price: Decimal):
    """
    Reset cycles with positions too small for take-profit orders.
    
    This function handles the situation where a cycle has a position that's below
    Alpaca's minimum order size, which blocks the cycle from being able to place
    take-profit orders and prevents new base orders from being placed.
    
    Args:
        cycle: The DcaCycle object with the tiny position
        alpaca_position: The Alpaca position object
        symbol: Asset symbol (e.g., 'PEPE/USD')
        current_price: Current market price as Decimal
    """
    try:
        min_order_qty = Decimal('0.000000002')  # Alpaca's minimum order quantity
        position_qty = Decimal(str(alpaca_position.qty))
        
        # Calculate market value for logging
        market_value = position_qty * current_price
        
        logger.info(f"🔄 Auto-resetting tiny position for {symbol}:")
        logger.info(f"   Cycle ID: {cycle.id}")
        logger.info(f"   Position Quantity: {position_qty}")
        logger.info(f"   Minimum Required: {min_order_qty}")
        logger.info(f"   Market Value: ${market_value:.8f}")
        logger.info(f"   Action: Reset cycle to zero quantity, continue normal lifecycle")
        
        # Reset the cycle to zero state - this unblocks the cycle for new base orders
        updates = {
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'last_order_fill_price': None
        }
        
        success = update_cycle(cycle.id, updates)
        
        if success:
            logger.info(f"✅ Cycle {cycle.id} reset to zero - ready for new base orders")
            logger.info(f"   Status: watching (unchanged)")
            logger.info(f"   Quantity: 0 (was {cycle.quantity})")
            logger.info(f"   Safety Orders: 0 (was {cycle.safety_orders})")
            logger.info(f"   🚀 {symbol} cycle unblocked - can now place base orders")
            
            # Note: We intentionally leave the tiny Alpaca position as-is
            # It's worth essentially $0 and will be ignored going forward
            logger.info(f"   📝 Note: Tiny Alpaca position (${market_value:.8f}) left as-is")
            
        else:
            logger.error(f"❌ Failed to reset cycle {cycle.id} for {symbol}")
            logger.error(f"   Cycle remains blocked - manual intervention may be required")
            
    except Exception as e:
        logger.error(f"❌ Error handling tiny position for {symbol}: {e}")
        logger.exception("Full traceback:")


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
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               highest_trailing_price, completed_at, created_at, updated_at, sell_price
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
        
        logger.info(f"💰 Take-profit SELL filled at {format_price(avg_fill_price)}")
        
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
            'completed_at': datetime.now(timezone.utc),
            'latest_order_id': None,
            'latest_order_created_at': None,  # Clear the order timestamp
            'sell_price': avg_fill_price  # Store the sell price for P/L calculations
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
        
        # Step 5: Update dca_assets.last_sell_price
        asset_update_success = update_asset_config(asset_config.id, {'last_sell_price': avg_fill_price})
        if not asset_update_success:
            logger.error(f"❌ Failed to update last_sell_price for asset {asset_config.id}")
            return
        
        logger.info(f"✅ Updated {symbol} last_sell_price to {format_price(avg_fill_price)}")
        
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
        logger.info(f"   💰 Sell Price: {format_price(avg_fill_price)}")
        logger.info(f"   📈 Avg Purchase Price: {format_price(current_cycle.average_purchase_price)}")
        profit_amount = avg_fill_price - current_cycle.average_purchase_price
        profit_percent = (profit_amount / current_cycle.average_purchase_price) * 100
        logger.info(f"   💵 Profit per unit: {format_price(profit_amount)} ({profit_percent:.2f}%)")
        logger.info(f"   🔄 Previous Cycle: {current_cycle.id} (complete)")
        logger.info(f"   ❄️  New Cooldown Cycle: {new_cooldown_cycle.id}")
        logger.info(f"   ⏱️  Cooldown Period: {asset_config.cooldown_period} seconds")
        
        # Send Discord notifications for sell order fill and cycle completion
        # First, send Discord notification for the sell order fill (with user mention)
        discord_order_filled(
            asset_symbol=symbol,
            order_type="Take-Profit",
            order_id=str(order.id),
            fill_price=float(avg_fill_price),
            quantity=float(filled_qty),
            is_full_fill=True
        )
        
        # Then, send Discord notification for cycle completion (with user mention)
        total_profit = profit_amount * current_cycle.quantity
        discord_cycle_completed(
            asset_symbol=symbol,
            profit=float(total_profit),
            profit_percent=float(profit_percent)
        )
        
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
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               highest_trailing_price, completed_at, created_at, updated_at, sell_price
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
            
            # Extract partial fill details if available (STANDARDIZED)
            order_filled_qty = Decimal('0')
            order_filled_avg_price = None
            
            logger.info(f"📊 Checking for partial fills in {event} BUY order...")
            
            if hasattr(order, 'filled_qty') and order.filled_qty:
                try:
                    order_filled_qty = Decimal(str(order.filled_qty))
                    if order_filled_qty > 0:
                        logger.info(f"   Partial Fill Detected: {order_filled_qty} filled")
                    else:
                        logger.info(f"   No Partial Fills: Order was {event} without any fills")
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_qty from {event} order: {order.filled_qty}")
            
            if hasattr(order, 'filled_avg_price') and order.filled_avg_price and order_filled_qty > 0:
                try:
                    order_filled_avg_price = Decimal(str(order.filled_avg_price))
                    logger.info(f"   Partial Fill Avg Price: {format_price(order_filled_avg_price)} (definitive)")
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_avg_price from {event} order: {order.filled_avg_price}")
            
            # Prepare updates with Alpaca position sync
            updates = {
                'status': 'watching',
                'latest_order_id': None,
                'latest_order_created_at': None
            }
            
            if alpaca_position:
                # Use Alpaca as source of truth for quantity and average price
                alpaca_qty = Decimal(str(alpaca_position.qty))
                alpaca_avg_price = Decimal(str(alpaca_position.avg_entry_price))
                
                logger.info(f"📊 Syncing with Alpaca position after {event}: {alpaca_qty} @ {format_price(alpaca_avg_price)}")
                
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
                logger.info(f"📊 Canceled order had partial fill: {order_filled_qty} @ {format_price(order_filled_avg_price)}")
            
        else:
            # For SELL order cancellations, enhanced handling with Alpaca position sync
            logger.info(f"🔄 Processing SELL order {event} with Alpaca position sync...")
            
            # Get Alpaca client and fetch current position
            client = get_trading_client()
            alpaca_position = None
            current_quantity_on_alpaca = cycle.quantity  # Fallback to original quantity
            
            if client:
                alpaca_position = get_alpaca_position_by_symbol(client, symbol)
                if alpaca_position:
                    try:
                        current_quantity_on_alpaca = Decimal(str(alpaca_position.qty))
                        logger.info(f"📊 Current Alpaca position after SELL {event}: {current_quantity_on_alpaca} @ ${alpaca_position.avg_entry_price}")
                    except (ValueError, TypeError, decimal.InvalidOperation):
                        logger.warning(f"Could not parse Alpaca position quantity: {alpaca_position.qty}")
                        current_quantity_on_alpaca = cycle.quantity
                else:
                    logger.info(f"📊 No Alpaca position found for {symbol} after SELL {event}")
                    # Don't assume zero position means completion - could be test environment
                    # Only treat as zero if we have evidence of actual selling (partial fills)
                    current_quantity_on_alpaca = None  # Will be handled below
            else:
                logger.warning(f"⚠️ Could not get Alpaca client for position sync after SELL {event}")
                current_quantity_on_alpaca = None
            
            # Extract partial fill details if available (STANDARDIZED)
            order_filled_qty = Decimal('0')
            order_filled_avg_price = None
            
            logger.info(f"📊 Checking for partial fills in {event} SELL order...")
            
            if hasattr(order, 'filled_qty') and order.filled_qty:
                try:
                    order_filled_qty = Decimal(str(order.filled_qty))
                    if order_filled_qty > 0:
                        logger.info(f"   Partial Fill Detected: {order_filled_qty} sold")
                    else:
                        logger.info(f"   No Partial Fills: SELL order was {event} without any fills")
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_qty from {event} SELL order: {order.filled_qty}")
            
            if hasattr(order, 'filled_avg_price') and order.filled_avg_price and order_filled_qty > 0:
                try:
                    order_filled_avg_price = Decimal(str(order.filled_avg_price))
                    logger.info(f"   Partial Fill Avg Price: {format_price(order_filled_avg_price)} (definitive)")
                except (ValueError, TypeError, decimal.InvalidOperation):
                    logger.warning(f"Could not parse filled_avg_price from {event} SELL order: {order.filled_avg_price}")
            
            # Prepare base updates (always clear order tracking fields)
            updates = {
                'latest_order_id': None,
                'latest_order_created_at': None
            }
            
            # Determine if we should complete the cycle or revert to watching
            should_complete_cycle = False
            
            if current_quantity_on_alpaca is not None and current_quantity_on_alpaca > Decimal('0'):
                # Position remains - revert to watching status
                updates['status'] = 'watching'
                updates['quantity'] = current_quantity_on_alpaca
                
                # Sync average price from Alpaca if available
                if alpaca_position:
                    try:
                        alpaca_avg_price = Decimal(str(alpaca_position.avg_entry_price))
                        updates['average_purchase_price'] = alpaca_avg_price
                    except (ValueError, TypeError, decimal.InvalidOperation):
                        logger.warning(f"Could not parse Alpaca avg_entry_price: {alpaca_position.avg_entry_price}")
                        # Keep existing average_purchase_price
                
                logger.info(f"✅ SELL order {order_id} for cycle {cycle.id} was {event}. "
                           f"Position remains: {current_quantity_on_alpaca}. Cycle status set to watching.")
                
                # Log partial fill details if applicable
                if order_filled_qty > 0:
                    logger.info(f"📊 Canceled SELL order had partial fill: {order_filled_qty} @ {format_price(order_filled_avg_price)}")
                    logger.info(f"📊 Remaining position: {current_quantity_on_alpaca} (was {cycle.quantity})")
                
            elif (current_quantity_on_alpaca is not None and current_quantity_on_alpaca == Decimal('0') and order_filled_qty > 0) or \
                 (current_quantity_on_alpaca is None and order_filled_qty > 0):
                # Position is zero AND we have evidence of partial fills - treat as completion
                # OR position sync failed but we have partial fills - also treat as completion
                should_complete_cycle = True
                logger.info(f"⚠️ SELL order {order_id} for cycle {cycle.id} was {event}, with partial fills. "
                           f"Treating as cycle completion.")
                
            else:
                # No position info or no partial fills - default to reverting to watching
                # This handles test environments and cases where Alpaca sync fails
                updates['status'] = 'watching'
                # Keep existing quantity and average price
                logger.info(f"✅ SELL order {order_id} for cycle {cycle.id} was {event}. "
                           f"Reverting to watching status (position sync unavailable or no fills).")
            
            if should_complete_cycle:
                updates['status'] = 'complete'
                updates['completed_at'] = datetime.now(timezone.utc)
                updates['quantity'] = Decimal('0')
                
                # Determine best price for last_sell_price and cycle sell_price
                sell_price = None
                if order_filled_avg_price:
                    sell_price = order_filled_avg_price
                elif hasattr(order, 'filled_avg_price') and order.filled_avg_price:
                    try:
                        sell_price = Decimal(str(order.filled_avg_price))
                    except (ValueError, TypeError, decimal.InvalidOperation):
                        sell_price = cycle.average_purchase_price
                else:
                    sell_price = cycle.average_purchase_price
                
                # Store the sell price in the cycle for P/L calculations
                updates['sell_price'] = sell_price
                
                # Update asset last_sell_price
                asset_config = get_asset_config(symbol)
                if asset_config:
                    asset_update_success = update_asset_config(asset_config.id, {'last_sell_price': sell_price})
                    if asset_update_success:
                        logger.info(f"✅ Updated {symbol} last_sell_price to {format_price(sell_price)}")
                    else:
                        logger.error(f"❌ Failed to update last_sell_price for asset {asset_config.id}")
                
                    # Create new cooldown cycle
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
                    
                    if new_cooldown_cycle:
                        logger.info(f"✅ Created new cooldown cycle {new_cooldown_cycle.id} for {symbol}")
                    else:
                        logger.error(f"❌ Failed to create new cooldown cycle for {symbol}")
                
                logger.info(f"✅ SELL order {order_id} for cycle {cycle.id} was {event}, but position is zero. Cycle completed.")
        
        success = update_cycle(cycle.id, updates)
        
        if success:
            if order.side.lower() == 'buy':
                logger.info(f"✅ BUY order {order_id} for cycle {cycle.id} was {event}. "
                           f"Cycle status set to watching.")
                logger.info(f"🔄 Cycle {cycle.id} ({symbol}) reverted to 'watching' status - ready for new orders")
                
                if alpaca_position:
                    logger.info(f"   🔗 Alpaca Sync: ✅ Position synced after {event}")
                else:
                    logger.info(f"   🔗 Alpaca Sync: ⚠️ Fallback used after {event}")
            else:
                # SELL order - status depends on whether position remains
                if updates.get('status') == 'watching':
                    logger.info(f"✅ SELL order cancellation processed - cycle {cycle.id} ({symbol}) reverted to 'watching' status")
                    logger.info(f"   🔗 Alpaca Sync: ✅ Position synced - ready for new take-profit attempts")
                elif updates.get('status') == 'complete':
                    logger.info(f"✅ SELL order cancellation processed - cycle {cycle.id} ({symbol}) completed (zero position)")
                    logger.info(f"   🔗 Alpaca Sync: ✅ Position confirmed zero - cycle completed")
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
                # Remove direct WebSocket close to avoid RuntimeWarning
                # The stream will close its WebSocket properly through its async mechanisms
            except Exception as e:
                logger.error(f"Error stopping CryptoDataStream: {e}")
        
        if trading_stream_ref:
            try:
                logger.info("Stopping TradingStream...")
                # Use the stream's internal stop method if available
                if hasattr(trading_stream_ref, '_should_run'):
                    trading_stream_ref._should_run = False
                # Remove direct WebSocket close to avoid RuntimeWarning
                # The stream will close its WebSocket properly through its async mechanisms
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
    
    # Check if we're in integration test mode
    if os.getenv('INTEGRATION_TEST_MODE') == 'true':
        logger.info("INTEGRATION_TEST_MODE detected - using hardcoded test assets")
        crypto_symbols = [
            'BTC/USD',   # Bitcoin
            'ETH/USD',   # Ethereum
            'XRP/USD',   # Ripple
            'SOL/USD',   # Solana
            'DOGE/USD',  # Dogecoin
            'LINK/USD',  # Chainlink
            'AVAX/USD',  # Avalanche
            'SHIB/USD',  # Shiba Inu
            'BCH/USD',   # Bitcoin Cash
            'LTC/USD',   # Litecoin
            'DOT/USD',   # Polkadot
            'PEPE/USD',  # Pepe
            'AAVE/USD',  # Aave
            'UNI/USD',   # Uniswap
            'TRUMP/USD'  # Trump
        ]
        logger.info(f"Using {len(crypto_symbols)} hardcoded test assets")
    else:
        # Get enabled assets from database
        try:
            from models.asset_config import get_all_enabled_assets
            enabled_assets = get_all_enabled_assets()
            crypto_symbols = [asset.asset_symbol for asset in enabled_assets]
            
            if not crypto_symbols:
                logger.warning("No enabled assets found in database - using fallback symbols")
                crypto_symbols = ['BTC/USD', 'ETH/USD']  # Minimal fallback
            
            logger.info(f"Loaded {len(crypto_symbols)} enabled assets from database")
            
        except Exception as e:
            logger.error(f"Error loading enabled assets from database: {e}")
            logger.warning("Using fallback crypto symbols")
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
    
    # Check WebSocket subscription limits (30 symbols max for free plan)
    if len(crypto_symbols) > 30:
        logger.warning(f"Too many symbols ({len(crypto_symbols)}) for WebSocket limit (30). Using first 30.")
        crypto_symbols = crypto_symbols[:30]
    
    # Subscribe to quotes and trades for selected crypto symbols
    for symbol in crypto_symbols:
        stream.subscribe_quotes(on_crypto_quote, symbol)
        stream.subscribe_trades(on_crypto_trade, symbol)
    
    logger.info(f"Subscribed to quotes and trades for {len(crypto_symbols)} crypto pairs:")
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