#!/usr/bin/env python3
"""
Order Manager Caretaker Script

This script manages stale and orphaned orders in the DCA Trading Bot system.
It should be run periodically via cron to maintain a clean trading environment.

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

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

# Import our utilities and models
from utils.db_utils import get_db_connection, execute_query, check_connection
from utils.alpaca_client_rest import get_trading_client, get_open_orders, cancel_order
from models.cycle_data import DcaCycle

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
DRY_RUN = config.dry_run_mode


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
    Only identifies BUY orders that are old AND not actively tracked.
    
    Args:
        open_orders: List of open Alpaca orders
        active_order_ids: Set of order IDs tracked by active cycles
        current_time: Current UTC time
    
    Returns:
        List: Orders that are stale BUY orders
    """
    stale_orders = []
    
    for order in open_orders:
        # Check if it's a BUY limit order
        if (hasattr(order, 'side') and order.side.value == 'buy' and
            hasattr(order, 'order_type') and order.order_type.value == 'limit'):
            
            # Calculate order age
            order_age = calculate_order_age(order.created_at, current_time)
            
            # Only consider it stale if it's old AND not actively tracked
            if (order_age > STALE_ORDER_THRESHOLD and 
                str(order.id) not in active_order_ids):
                
                stale_orders.append(order)
                logger.info(f"Identified stale BUY order: {order.id} "
                           f"(age: {order_age.total_seconds():.0f}s, "
                           f"symbol: {order.symbol}, "
                           f"qty: {order.qty}, "
                           f"price: ${order.limit_price})")
    
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


def cancel_orders(client, orders_to_cancel: List, order_type: str) -> int:
    """
    Cancel a list of orders.
    
    Args:
        client: Alpaca trading client
        orders_to_cancel: List of orders to cancel
        order_type: Description of order type for logging
    
    Returns:
        int: Number of orders successfully canceled
    """
    canceled_count = 0
    
    for order in orders_to_cancel:
        try:
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would cancel {order_type} order: {order.id} "
                           f"({order.symbol}, {order.side.value}, age: "
                           f"{calculate_order_age(order.created_at, get_current_utc_time()).total_seconds():.0f}s)")
                canceled_count += 1
            else:
                success = cancel_order(client, order.id)
                if success:
                    logger.info(f"✅ Successfully canceled {order_type} order: {order.id} "
                               f"({order.symbol}, {order.side.value})")
                    canceled_count += 1
                else:
                    logger.warning(f"⚠️ Failed to cancel {order_type} order: {order.id} "
                                  f"({order.symbol}, {order.side.value})")
                    
        except Exception as e:
            logger.error(f"❌ Error canceling {order_type} order {order.id}: {e}")
    
    return canceled_count


def main():
    """Main order management function."""
    logger.info("="*60)
    logger.info("ORDER MANAGER CARETAKER SCRIPT STARTED")
    logger.info("="*60)
    
    if DRY_RUN:
        logger.info("🔍 DRY RUN MODE: No orders will actually be canceled")
    
    logger.info(f"⏱️ Stale order threshold: {STALE_ORDER_THRESHOLD_MINUTES} minutes")
    
    try:
        # Step 1: Initialize connections
        logger.info("🔧 Initializing connections...")
        
        # Check database connection
        if not check_connection():
            logger.error("❌ Database connection failed")
            return False
        logger.info("✅ Database connection established")
        
        # Initialize Alpaca client
        client = get_trading_client()
        if not client:
            logger.error("❌ Failed to initialize Alpaca trading client")
            return False
        logger.info("✅ Alpaca trading client initialized")
        
        # Step 2: Get current time and open orders
        current_time = get_current_utc_time()
        logger.info(f"🕐 Current UTC time: {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        open_orders = get_open_orders(client)
        logger.info(f"📋 Found {len(open_orders)} open orders on Alpaca")
        
        if not open_orders:
            logger.info("✅ No open orders found - nothing to manage")
            return True
        
        # Step 3: Get active cycle order IDs
        logger.info("🔍 Fetching active cycle order IDs from database...")
        active_order_ids = get_active_cycle_order_ids()
        
        # Step 4: Identify stale BUY orders
        logger.info("🔍 Identifying stale BUY limit orders...")
        stale_buy_orders = identify_stale_buy_orders(open_orders, active_order_ids, current_time)
        logger.info(f"Found {len(stale_buy_orders)} stale BUY orders")
        
        # Step 5: Identify orphaned orders
        logger.info("🔍 Identifying orphaned orders...")
        orphaned_orders = identify_orphaned_orders(open_orders, active_order_ids, current_time)
        logger.info(f"Found {len(orphaned_orders)} orphaned orders")
        
        # Step 6: Cancel stale BUY orders (these are BUY limit orders not tracked in DB)
        if stale_buy_orders:
            logger.info(f"🧹 Canceling {len(stale_buy_orders)} stale BUY orders...")
            stale_canceled = cancel_orders(client, stale_buy_orders, "stale BUY")
            logger.info(f"✅ Canceled {stale_canceled}/{len(stale_buy_orders)} stale BUY orders")
        else:
            logger.info("✅ No stale BUY orders to cancel")
            stale_canceled = 0
        
        # Step 7: Cancel orphaned orders (non-BUY orders not tracked in DB)
        # Filter out BUY orders since they were already handled above
        non_buy_orphaned = [o for o in orphaned_orders if o.side.value != 'buy']
        
        if non_buy_orphaned:
            logger.info(f"🧹 Canceling {len(non_buy_orphaned)} orphaned non-BUY orders...")
            orphaned_canceled = cancel_orders(client, non_buy_orphaned, "orphaned")
            logger.info(f"✅ Canceled {orphaned_canceled}/{len(non_buy_orphaned)} orphaned orders")
        else:
            logger.info("✅ No orphaned non-BUY orders to cancel")
            orphaned_canceled = 0
        
        # Step 8: Summary
        total_canceled = stale_canceled + orphaned_canceled
        total_identified = len(stale_buy_orders) + len(non_buy_orphaned)
        
        logger.info("="*60)
        logger.info("ORDER MANAGER SUMMARY:")
        logger.info(f"📊 Total orders checked: {len(open_orders)}")
        logger.info(f"📊 Active cycle orders: {len(active_order_ids)}")
        logger.info(f"📊 Stale BUY orders found: {len(stale_buy_orders)}")
        logger.info(f"📊 Orphaned orders found: {len(orphaned_orders)}")
        logger.info(f"📊 Total orders canceled: {total_canceled}/{total_identified}")
        
        if DRY_RUN:
            logger.info("🔍 DRY RUN: No actual cancellations performed")
        
        logger.info("✅ ORDER MANAGER COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR in order manager: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 