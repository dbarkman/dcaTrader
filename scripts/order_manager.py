#!/usr/bin/env python3
"""
Order Manager - Caretaker Script

This script manages stale and orphaned orders by:
1. Canceling stale BUY orders (old unfilled orders)
2. Canceling orphaned orders (orders on Alpaca not tracked by active cycles)
3. Handling stuck market SELL orders

Designed to run via cron every 1-2 minutes.

Functions:
1. Stale BUY Order Management: Cancel bot's open BUY limit orders older than 5 minutes
2. Orphaned Alpaca Order Management: Cancel any open Alpaca orders older than 5 minutes 
   that don't correspond to an active dca_cycles row

Usage:
    python scripts/order_manager.py

Environment Variables:
    STALE_ORDER_THRESHOLD_MINUTES: Minutes after which orders are considered stale (default: 5)
    DRY_RUN: If set to 'true', only log actions without actually canceling orders
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Set, Optional
from decimal import Decimal

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

# Import our utilities and models
from utils.db_utils import get_db_connection, execute_query, check_connection
from utils.alpaca_client_rest import get_trading_client, get_open_orders, cancel_order, get_order
from models.cycle_data import DcaCycle, get_all_cycles, update_cycle

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/order_manager.log', mode='a') if os.path.exists('logs') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

# Import configuration
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from config import get_config

config = get_config()

# Configuration
STALE_ORDER_THRESHOLD_MINUTES = config.stale_order_threshold_minutes
STALE_ORDER_THRESHOLD = timedelta(minutes=STALE_ORDER_THRESHOLD_MINUTES)
STUCK_MARKET_SELL_TIMEOUT_SECONDS = 75  # Timeout for stuck market SELL orders
DRY_RUN = config.dry_run_mode

from alpaca.common.exceptions import APIError
import mysql.connector
from mysql.connector import Error


def get_current_utc_time() -> datetime:
    """Get current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


def calculate_order_age(order_created_at: datetime, current_time: datetime) -> timedelta:
    """
    Calculate the age of an order.
    
    Args:
        order_created_at: Order creation timestamp (should be timezone-aware)
        current_time: Current UTC time (timezone-aware)
    
    Returns:
        timedelta: Age of the order
    """
    # Ensure both timestamps are timezone-aware
    if order_created_at.tzinfo is None:
        # Assume UTC if no timezone info
        order_created_at = order_created_at.replace(tzinfo=timezone.utc)
    
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    
    return current_time - order_created_at


def get_active_cycle_order_ids() -> Set[str]:
    """
    Get all order IDs that are currently tracked by active cycles.
    
    Returns:
        Set[str]: Set of order IDs that are actively tracked
    """
    try:
        # Query for all cycles with active orders (buying or selling status)
        query = """
        SELECT latest_order_id 
        FROM dca_cycles 
        WHERE status IN ('buying', 'selling') 
        AND latest_order_id IS NOT NULL
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No active cycles with pending orders found")
            return set()
        
        # Extract order IDs into a set
        active_order_ids = {row['latest_order_id'] for row in results if row['latest_order_id']}
        
        logger.info(f"Found {len(active_order_ids)} active order IDs in database")
        return active_order_ids
        
    except Exception as e:
        logger.error(f"Error fetching active cycle order IDs: {e}")
        return set()


def identify_stale_buy_orders(open_orders: List, active_order_ids: Set[str], current_time: datetime) -> List:
    """
    Identify stale BUY limit orders that should be canceled.
    Only identifies untracked BUY orders that are old - preserves tracked orders.
    
    Args:
        open_orders: List of open Alpaca orders
        active_order_ids: Set of order IDs tracked by active cycles
        current_time: Current UTC time
    
    Returns:
        List: Orders that are stale untracked BUY orders
    """
    stale_orders = []
    
    for order in open_orders:
        # Check if it's a BUY limit order
        if (hasattr(order, 'side') and order.side.value == 'buy' and
            hasattr(order, 'order_type') and order.order_type.value == 'limit'):
            
            # Calculate order age
            order_age = calculate_order_age(order.created_at, current_time)
            
            # Only consider untracked orders as stale (preserve tracked orders)
            if order_age > STALE_ORDER_THRESHOLD:
                order_id_str = str(order.id)
                is_tracked = order_id_str in active_order_ids
                
                if is_tracked:
                    logger.info(f"Preserving tracked BUY order: {order.id} "
                               f"(age: {order_age.total_seconds():.0f}s, "
                               f"symbol: {order.symbol}, "
                               f"qty: {order.qty}, "
                               f"price: ${order.limit_price}, "
                               f"status: tracked)")
                else:
                    stale_orders.append(order)
                    logger.info(f"Identified stale BUY order: {order.id} "
                               f"(age: {order_age.total_seconds():.0f}s, "
                               f"symbol: {order.symbol}, "
                               f"qty: {order.qty}, "
                               f"price: ${order.limit_price}, "
                               f"status: untracked)")
    
    return stale_orders


def identify_orphaned_orders(open_orders: List, active_order_ids: Set[str], current_time: datetime) -> List:
    """
    Identify orphaned orders that should be canceled.
    
    Args:
        open_orders: List of open Alpaca orders
        active_order_ids: Set of order IDs tracked by active cycles
        current_time: Current UTC time
    
    Returns:
        List: Orders that are orphaned
    """
    orphaned_orders = []
    
    for order in open_orders:
        # Calculate order age
        order_age = calculate_order_age(order.created_at, current_time)
        
        # Check if order is old enough and not tracked by any active cycle
        if (order_age > STALE_ORDER_THRESHOLD and 
            str(order.id) not in active_order_ids):
            
            orphaned_orders.append(order)
            logger.info(f"Identified orphaned order: {order.id} "
                       f"(age: {order_age.total_seconds():.0f}s, "
                       f"symbol: {order.symbol}, "
                       f"side: {order.side.value}, "
                       f"type: {order.order_type.value})")
    
    return orphaned_orders


def identify_stuck_sell_orders(current_time: datetime) -> List[DcaCycle]:
    """
    Identify cycles with stuck market SELL orders that should be canceled.
    
    Args:
        current_time: Current UTC time
    
    Returns:
        List: DcaCycle objects with stuck SELL orders
    """
    stuck_cycles = []
    
    try:
        # Query for cycles in 'selling' status with active orders
        query = """
        SELECT id, asset_id, status, quantity, average_purchase_price, 
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               highest_trailing_price, completed_at, created_at, updated_at, sell_price
        FROM dca_cycles 
        WHERE status = 'selling' 
        AND latest_order_id IS NOT NULL 
        AND latest_order_created_at IS NOT NULL
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No cycles in 'selling' status with active orders found")
            return stuck_cycles
        
        logger.info(f"Found {len(results)} cycles in 'selling' status with active orders")
        
        for row in results:
            cycle = DcaCycle.from_dict(row)
            
            # Calculate order age
            order_age = calculate_order_age(cycle.latest_order_created_at, current_time)
            
            # Check if order is stuck (older than threshold)
            if order_age.total_seconds() > STUCK_MARKET_SELL_TIMEOUT_SECONDS:
                stuck_cycles.append(cycle)
                logger.info(f"Identified stuck SELL order: cycle {cycle.id}, "
                           f"order {cycle.latest_order_id}, "
                           f"age: {order_age.total_seconds():.0f}s")
        
        logger.info(f"Found {len(stuck_cycles)} stuck SELL orders")
        return stuck_cycles
        
    except Exception as e:
        logger.error(f"Error identifying stuck SELL orders: {e}")
        return []


def cancel_orders(client, orders_to_cancel: List, order_type: str, active_order_ids: Set[str] = None) -> int:
    """
    Cancel a list of orders and update database for tracked orders.
    
    Args:
        client: Alpaca trading client
        orders_to_cancel: List of orders to cancel
        order_type: Description of order type for logging
        active_order_ids: Set of order IDs tracked by active cycles (optional)
    
    Returns:
        int: Number of orders successfully canceled
    """
    canceled_count = 0
    
    for order in orders_to_cancel:
        try:
            order_id_str = str(order.id)
            is_tracked = active_order_ids and order_id_str in active_order_ids
            
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would cancel {order_type} order: {order.id} "
                           f"({order.symbol}, {order.side.value}, age: "
                           f"{calculate_order_age(order.created_at, get_current_utc_time()).total_seconds():.0f}s)")
                if is_tracked:
                    logger.info(f"[DRY RUN] Would update database to clear tracking for order {order.id}")
                canceled_count += 1
                continue
            
            # Attempt to cancel the order
            success = cancel_order(client, order.id)
            
            if success:
                logger.info(f"✅ Canceled {order_type} order: {order.id} "
                           f"({order.symbol}, {order.side.value}, age: "
                           f"{calculate_order_age(order.created_at, get_current_utc_time()).total_seconds():.0f}s)")
                
                # If this order is tracked by an active cycle, clear the tracking
                if is_tracked:
                    try:
                        clear_query = """
                        UPDATE dca_cycles 
                        SET latest_order_id = NULL, latest_order_created_at = NULL 
                        WHERE latest_order_id = %s
                        """
                        rows_affected = execute_query(clear_query, (order_id_str,), commit=True)
                        if rows_affected and rows_affected > 0:
                            logger.info(f"🔄 Cleared tracking for canceled order {order.id} in database")
                        else:
                            logger.warning(f"⚠️ No database rows updated when clearing tracking for order {order.id}")
                    except mysql.connector.Error as db_err:
                        logger.error(f"Database error clearing tracking for order {order.id}: {db_err}")
                    except Exception as e:
                        logger.error(f"Unexpected error clearing tracking for order {order.id}: {e}")
                
                canceled_count += 1
            else:
                logger.warning(f"⚠️ Failed to cancel {order_type} order: {order.id}")
                
        except APIError as e:
            logger.error(f"Alpaca API error canceling {order_type} order {order.id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error canceling {order_type} order {order.id}: {e}")
    
    return canceled_count


def handle_stuck_sell_orders(client, stuck_cycles: List[DcaCycle]) -> int:
    """
    Handle stuck market SELL orders by verifying their status and canceling if needed.
    
    Args:
        client: Alpaca trading client
        stuck_cycles: List of cycles with potentially stuck SELL orders
    
    Returns:
        int: Number of orders successfully canceled
    """
    canceled_count = 0
    
    for cycle in stuck_cycles:
        try:
            order_id = cycle.latest_order_id
            logger.info(f"Market SELL order {order_id} for cycle {cycle.id} appears stuck "
                       f"(age > {STUCK_MARKET_SELL_TIMEOUT_SECONDS}s). Attempting to verify and cancel.")
            
            # Verify order status on Alpaca
            alpaca_order = get_order(client, order_id)
            
            if not alpaca_order:
                logger.warning(f"Stuck SELL check: Order {order_id} not found on Alpaca. "
                              f"May have already been processed.")
                continue
            
            # Check if order is still in an active state
            active_statuses = ['new', 'accepted', 'pending_new', 'partially_filled']
            terminal_statuses = ['filled', 'canceled', 'cancelled', 'rejected', 'expired']
            
            order_status = alpaca_order.status.value if hasattr(alpaca_order.status, 'value') else str(alpaca_order.status)
            
            if order_status.lower() in [s.lower() for s in active_statuses]:
                # Order is still active - attempt to cancel
                logger.info(f"Order {order_id} is in active status '{order_status}'. Attempting cancellation...")
                
                if DRY_RUN:
                    logger.info(f"[DRY RUN] Would cancel stuck SELL order: {order_id} "
                               f"(cycle {cycle.id}, status: {order_status})")
                    canceled_count += 1
                else:
                    success = cancel_order(client, order_id)
                    if success:
                        logger.info(f"✅ Successfully requested cancellation of stuck SELL order: {order_id} "
                                   f"(cycle {cycle.id})")
                        canceled_count += 1
                    else:
                        logger.warning(f"⚠️ Failed to cancel stuck SELL order: {order_id} "
                                      f"(cycle {cycle.id})")
                        
            elif order_status.lower() in [s.lower() for s in terminal_statuses]:
                # Order is already in terminal state
                logger.info(f"Stuck SELL check: Order {order_id} already in terminal state '{order_status}'. "
                           f"No cancellation needed by order_manager. TradingStream should handle/have handled the final state.")
            else:
                # Unknown status
                logger.warning(f"Stuck SELL check: Order {order_id} has unknown status '{order_status}'. "
                              f"Skipping cancellation attempt.")
                
        except Exception as e:
            logger.error(f"❌ Error handling stuck SELL order {cycle.latest_order_id} for cycle {cycle.id}: {e}")
    
    return canceled_count


def main():
    """Main order management function."""
    logger.info("="*60)
    logger.info("DCA TRADING BOT - ORDER MANAGER")
    logger.info("="*60)
    
    if DRY_RUN:
        logger.info("🔍 DRY RUN MODE: No actual changes will be made")
    
    try:
        # Step 1: Initialize Alpaca client
        logger.info("1. 🔗 Initializing Alpaca client...")
        try:
            client = get_trading_client()
            if not client:
                logger.error("❌ Failed to initialize Alpaca client")
                return False
            logger.info("   ✅ Alpaca client initialized successfully")
        except APIError as e:
            logger.error(f"❌ Alpaca API error initializing client: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error initializing Alpaca client: {e}")
            return False
        
        # Step 2: Get all open orders from Alpaca
        logger.info("2. 📋 Fetching open orders from Alpaca...")
        try:
            all_orders = get_open_orders(client)
            logger.info(f"   📊 Found {len(all_orders)} open orders on Alpaca")
        except APIError as e:
            logger.error(f"❌ Alpaca API error fetching open orders: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching open orders: {e}")
            return False
        
        if not all_orders:
            logger.info("   ℹ️ No open orders found - nothing to manage")
            logger.info("✅ ORDER MANAGER COMPLETED SUCCESSFULLY")
            logger.info("="*60)
            return True
        
        # Step 3: Get active cycles and their tracked orders
        logger.info("3. 🗄️ Fetching active cycles from database...")
        try:
            active_cycles = get_all_cycles()
            active_order_ids = {str(cycle.latest_order_id) for cycle in active_cycles 
                              if cycle.latest_order_id and cycle.status in ['buying', 'selling']}
            logger.info(f"   📊 Found {len(active_cycles)} total cycles")
            logger.info(f"   🔗 Found {len(active_order_ids)} tracked order IDs")
        except mysql.connector.Error as db_err:
            logger.error(f"❌ Database error fetching active cycles: {db_err}")
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error fetching active cycles: {e}")
            return False
        
        # Step 4: Categorize orders
        logger.info("4. 📂 Categorizing orders...")
        current_time = get_current_utc_time()
        
        stale_buy_orders = []
        orphaned_orders = []
        stuck_sell_orders = []
        
        for order in all_orders:
            order_id_str = str(order.id)
            order_age = calculate_order_age(order.created_at, current_time)
            
            # Check for stuck market SELL orders first
            if (order.side.value.lower() == 'sell' and 
                order.order_type.value.lower() == 'market' and
                order_age.total_seconds() > STUCK_MARKET_SELL_TIMEOUT_SECONDS):
                stuck_sell_orders.append(order)
                continue
            
            # Check if order is tracked by an active cycle
            if order_id_str in active_order_ids:
                # This is a tracked order - preserve it (don't cancel even if stale)
                # Tracked orders are part of active trading strategies
                continue
            else:
                # This is an orphaned order (not tracked by any active cycle)
                # Check if it's a stale BUY order
                if (order.side.value.lower() == 'buy' and 
                    order_age > STALE_ORDER_THRESHOLD):
                    stale_buy_orders.append(order)
                else:
                    orphaned_orders.append(order)
        
        logger.info(f"   🕐 Stale BUY orders (>{STALE_ORDER_THRESHOLD_MINUTES}min): {len(stale_buy_orders)}")
        logger.info(f"   👻 Orphaned orders (not tracked): {len(orphaned_orders)}")
        logger.info(f"   🔒 Stuck SELL orders (>{STUCK_MARKET_SELL_TIMEOUT_SECONDS}s): {len(stuck_sell_orders)}")
        
        # Step 5: Cancel stale BUY orders
        if stale_buy_orders:
            logger.info("5. 🕐 Canceling stale BUY orders...")
            canceled_stale = cancel_orders(client, stale_buy_orders, "stale BUY", active_order_ids)
            logger.info(f"   ✅ Canceled {canceled_stale}/{len(stale_buy_orders)} stale BUY orders")
        else:
            logger.info("5. 🕐 No stale BUY orders to cancel")
        
        # Step 6: Cancel orphaned orders
        if orphaned_orders:
            logger.info("6. 👻 Canceling orphaned orders...")
            canceled_orphaned = cancel_orders(client, orphaned_orders, "orphaned")
            logger.info(f"   ✅ Canceled {canceled_orphaned}/{len(orphaned_orders)} orphaned orders")
        else:
            logger.info("6. 👻 No orphaned orders to cancel")
        
        # Step 7: Handle stuck SELL orders
        if stuck_sell_orders:
            logger.info("7. 🔒 Handling stuck market SELL orders...")
            try:
                stuck_cycles = get_stuck_sell_cycles()
                canceled_stuck = handle_stuck_sell_orders(client, stuck_cycles)
                logger.info(f"   ✅ Handled {canceled_stuck} stuck SELL orders")
            except mysql.connector.Error as db_err:
                logger.error(f"❌ Database error handling stuck SELL orders: {db_err}")
            except Exception as e:
                logger.error(f"❌ Unexpected error handling stuck SELL orders: {e}")
        else:
            logger.info("7. 🔒 No stuck market SELL orders to handle")
        
        if DRY_RUN:
            logger.info("🔍 DRY RUN: No actual updates performed")
        
        logger.info("✅ ORDER MANAGER COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        
        return True
        
    except APIError as e:
        logger.error(f"❌ Alpaca API error in order manager: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    except mysql.connector.Error as db_err:
        logger.error(f"❌ Database error in order manager: {db_err}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False
    except Exception as e:
        logger.error(f"❌ Unexpected error in order manager: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 