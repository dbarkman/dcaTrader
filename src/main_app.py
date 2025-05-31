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
import threading
import decimal
from datetime import datetime, timezone
from decimal import Decimal
import mysql.connector
from pathlib import Path
from typing import Optional

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from config import get_config
from utils.alpaca_client_rest import *
from utils.formatting import format_price, format_quantity
from models.asset_config import get_asset_config, update_asset_config
from models.cycle_data import get_latest_cycle, update_cycle, create_cycle
from utils.db_utils import execute_query
from utils.logging_config import get_asset_logger
from utils.notifications import (
    send_system_alert, 
    alert_order_placed, 
    alert_order_filled, 
    alert_cycle_completed,
    alert_critical_error
)
from utils.discord_notifications import (
    discord_order_placed,
    discord_order_filled,
    discord_cycle_completed,
    discord_system_error
)

# Import Alpaca streaming and trading clients
from alpaca.data.live import CryptoDataStream
from alpaca.trading.stream import TradingStream
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError

# Import new strategy logic and data structures
from strategy_logic import (
    decide_base_order_action,
    decide_safety_order_action, 
    decide_take_profit_action
)
from models.backtest_structs import (
    MarketTickInput, StrategyAction, OrderSide, OrderType
)

# Initialize configuration and logging
config = get_config()
recent_orders = {}  # Global dictionary to track recent orders and prevent duplicates

# Setup logging
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False
# Global stream references for shutdown
crypto_stream_ref = None
trading_stream_ref = None

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
    
    Refactored to use pure strategy logic that returns intents,
    then execute those intents using Alpaca client and database utilities.
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    logger.debug(f"Quote: {quote.symbol} - Bid: ${quote.bid_price} @ {quote.bid_size}, Ask: ${quote.ask_price} @ {quote.ask_size}")
    
    # Check for recent orders to prevent duplicates
    global recent_orders
    symbol = quote.symbol
    now = datetime.now()
    recent_order_cooldown = config.order_cooldown_seconds
    
    if symbol in recent_orders:
        time_since_order = now - recent_orders[symbol]['timestamp']
        if time_since_order.total_seconds() < recent_order_cooldown:
            return
    
    try:
        # Step 1: Convert quote to MarketTickInput for strategy functions
        market_input = MarketTickInput(
            timestamp=now,
            current_ask_price=Decimal(str(quote.ask_price)),
            current_bid_price=Decimal(str(quote.bid_price)),
            symbol=symbol
        )
        
        # Step 2: Get asset configuration and current cycle
        asset_config = get_asset_config(symbol)
        if not asset_config:
            # Asset not configured - skip silently
            return
        
        if not asset_config.is_enabled:
            logger.debug(f"Asset {symbol} is disabled, skipping")
            return
        
        latest_cycle = get_latest_cycle(asset_config.id)
        if not latest_cycle:
            return
        
        # Step 3: Initialize Alpaca client and get current position
        client = get_trading_client()
        if not client:
            logger.error(f"Could not initialize Alpaca client for {symbol}")
            return
        
        # Get current Alpaca position for base order conflict check and sell quantity accuracy
        current_alpaca_position = None
        try:
            positions = get_positions(client)
            alpaca_symbol = symbol.replace('/', '')  # Convert UNI/USD -> UNIUSD
            
            for position in positions:
                if position.symbol == alpaca_symbol and float(position.qty) != 0:
                    current_alpaca_position = position
                    break
        except Exception as e:
            logger.error(f"Error fetching Alpaca positions for {symbol}: {e}")
            # Continue without position data - some strategy functions will handle this gracefully
        
        # Step 4: Call strategy functions to get action intents
        actions_to_execute = []
        
        # Check base order action
        try:
            base_action = decide_base_order_action(
                market_input, asset_config, latest_cycle, current_alpaca_position
            )
            if base_action and base_action.has_action():
                actions_to_execute.append(('base_order', base_action))
        except Exception as e:
            logger.error(f"Error in decide_base_order_action for {symbol}: {e}")
        
        # Check safety order action
        try:
            safety_action = decide_safety_order_action(
                market_input, asset_config, latest_cycle
            )
            if safety_action and safety_action.has_action():
                actions_to_execute.append(('safety_order', safety_action))
        except Exception as e:
            logger.error(f"Error in decide_safety_order_action for {symbol}: {e}")
        
        # Check take-profit action
        try:
            tp_action = decide_take_profit_action(
                market_input, asset_config, latest_cycle, current_alpaca_position
            )
            if tp_action and tp_action.has_action():
                actions_to_execute.append(('take_profit', tp_action))
        except Exception as e:
            logger.error(f"Error in decide_take_profit_action for {symbol}: {e}")
        
        # Step 5: Execute the action intents
        for action_type, action in actions_to_execute:
            try:
                await execute_strategy_action(action, action_type, latest_cycle, client, symbol, now)
            except Exception as e:
                logger.error(f"Error executing {action_type} action for {symbol}: {e}")
                
    except Exception as e:
        logger.error(f"Error in on_crypto_quote for {symbol}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


async def execute_strategy_action(
    action: StrategyAction, 
    action_type: str, 
    cycle: 'DcaCycle', 
    client: 'TradingClient', 
    symbol: str, 
    timestamp: datetime
) -> None:
    """
    Execute a strategy action by placing orders and updating cycle state.
    
    Args:
        action: The StrategyAction to execute
        action_type: Type of action for logging ('base_order', 'safety_order', 'take_profit')
        cycle: The DCA cycle to update
        client: Alpaca trading client
        symbol: Trading symbol
        timestamp: Current timestamp
    """
    global recent_orders
    
    try:
        order_id = None
        
        # Step 1: Execute order intent if present
        if action.order_intent:
            order = await execute_order_intent(action.order_intent, client, action_type, symbol)
            if order:
                order_id = str(order.id)
                
                # Track this order to prevent duplicates
                recent_orders[symbol] = {
                    'order_id': order_id,
                    'timestamp': timestamp
                }
                
                # Send Discord notification for order placement
                order_type_name = {
                    'base_order': 'Base Order',
                    'safety_order': f'Safety Order #{cycle.safety_orders + 1}',
                    'take_profit': 'Take Profit'
                }.get(action_type, action_type.title())
                
                discord_order_placed(
                    asset_symbol=symbol,
                    order_type=order_type_name,
                    order_id=order_id,
                    quantity=float(action.order_intent.quantity),
                    price=float(action.order_intent.limit_price or action.order_intent.quantity)
                )
            else:
                logger.error(f"❌ Failed to place {action_type} order for {symbol}")
                
                # Track failed order attempts to prevent immediate retries
                recent_orders[symbol] = {
                    'order_id': 'FAILED',
                    'timestamp': timestamp
                }
                return
        
        # Step 2: Execute cycle state update intent if present
        if action.cycle_update_intent:
            await execute_cycle_update_intent(action.cycle_update_intent, cycle, order_id)
        
        # Step 3: Execute TTP state update intent if present
        if action.ttp_update_intent:
            await execute_ttp_update_intent(action.ttp_update_intent, cycle)
            
    except Exception as e:
        logger.error(f"Error executing strategy action for {symbol}: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")


async def execute_order_intent(
    order_intent: 'OrderIntent', 
    client: 'TradingClient', 
    action_type: str, 
    symbol: str
) -> Optional[object]:
    """
    Execute an order intent by placing the actual order with Alpaca.
    
    Args:
        order_intent: The order intent to execute
        client: Alpaca trading client
        action_type: Type of action for logging
        symbol: Trading symbol
        
    Returns:
        Alpaca order object if successful, None otherwise
    """
    try:
        if order_intent.side == OrderSide.BUY and order_intent.order_type == OrderType.LIMIT:
            logger.info(f"🔄 Placing LIMIT BUY order for {symbol} ({action_type}):")
            logger.info(f"   Quantity: {format_quantity(order_intent.quantity)}")
            logger.info(f"   Limit Price: {format_price(order_intent.limit_price)}")
            
            order = place_limit_buy_order(
                client=client,
                symbol=symbol,
                qty=float(order_intent.quantity),
                limit_price=float(order_intent.limit_price),
                time_in_force='gtc'
            )
            
            if order:
                logger.info(f"✅ LIMIT BUY order PLACED for {symbol}:")
                logger.info(f"   Order ID: {order.id}")
                logger.info(f"   Quantity: {format_quantity(order_intent.quantity)}")
                logger.info(f"   Limit Price: {format_price(order_intent.limit_price)}")
                
            return order
            
        elif order_intent.side == OrderSide.SELL and order_intent.order_type == OrderType.MARKET:
            logger.info(f"🔄 Placing MARKET SELL order for {symbol} ({action_type}):")
            logger.info(f"   Quantity: {format_quantity(order_intent.quantity)}")
            
            order = place_market_sell_order(
                client=client,
                symbol=symbol,
                qty=float(order_intent.quantity),
                time_in_force='gtc'
            )
            
            if order:
                logger.info(f"✅ MARKET SELL order PLACED for {symbol}:")
                logger.info(f"   Order ID: {order.id}")
                logger.info(f"   Quantity: {format_quantity(order_intent.quantity)}")
                
            return order
            
        else:
            logger.error(f"Unsupported order intent: {order_intent.side.value} {order_intent.order_type.value}")
            return None
            
    except Exception as e:
        logger.error(f"Error executing order intent for {symbol}: {e}")
        return None


async def execute_cycle_update_intent(
    update_intent: 'CycleStateUpdateIntent', 
    cycle: 'DcaCycle', 
    order_id: Optional[str]
) -> None:
    """
    Execute a cycle state update intent.
    
    Args:
        update_intent: The cycle update intent to execute
        cycle: The DCA cycle to update
        order_id: Order ID from placed order (if any)
    """
    try:
        updates = {}
        
        if update_intent.new_status:
            updates['status'] = update_intent.new_status
        
        if order_id:
            updates['latest_order_id'] = order_id
        elif update_intent.new_latest_order_id:
            updates['latest_order_id'] = update_intent.new_latest_order_id
            
        if update_intent.new_latest_order_created_at:
            updates['latest_order_created_at'] = update_intent.new_latest_order_created_at
        
        if update_intent.new_quantity is not None:
            updates['quantity'] = update_intent.new_quantity
            
        if update_intent.new_average_purchase_price is not None:
            updates['average_purchase_price'] = update_intent.new_average_purchase_price
            
        if update_intent.new_safety_orders is not None:
            updates['safety_orders'] = update_intent.new_safety_orders
            
        if update_intent.new_last_order_fill_price is not None:
            updates['last_order_fill_price'] = update_intent.new_last_order_fill_price
        
        if updates:
            update_success = update_cycle(cycle.id, updates)
            if update_success:
                logger.info(f"🔄 Updated cycle {cycle.id} with {updates}")
            else:
                logger.warning(f"⚠️ Failed to update cycle {cycle.id} with {updates}")
                
    except Exception as e:
        logger.error(f"Error executing cycle update intent: {e}")


async def execute_ttp_update_intent(
    ttp_intent: 'TTPStateUpdateIntent', 
    cycle: 'DcaCycle'
) -> None:
    """
    Execute a TTP state update intent.
    
    Args:
        ttp_intent: The TTP update intent to execute
        cycle: The DCA cycle to update
    """
    try:
        updates = {}
        
        if ttp_intent.new_status:
            updates['status'] = ttp_intent.new_status
            
        if ttp_intent.new_highest_trailing_price is not None:
            updates['highest_trailing_price'] = ttp_intent.new_highest_trailing_price
        
        if updates:
            update_success = update_cycle(cycle.id, updates)
            if update_success:
                logger.info(f"🎯 Updated TTP state for cycle {cycle.id} with {updates}")
            else:
                logger.warning(f"⚠️ Failed to update TTP state for cycle {cycle.id} with {updates}")
                
    except Exception as e:
        logger.error(f"Error executing TTP update intent: {e}")


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