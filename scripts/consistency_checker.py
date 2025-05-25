#!/usr/bin/env python3
"""
Consistency Checker Caretaker Script

This script maintains data consistency between the database and Alpaca's live state.
It handles two main scenarios:

1. Stuck 'buying' cycles: If a DB cycle is 'buying' but no corresponding active BUY order 
   exists on Alpaca, set cycle to 'watching'.

2. Orphaned 'watching' cycles: If a DB cycle is 'watching' with quantity > 0, but Alpaca 
   shows no position, mark current cycle as 'error' and create a new 'watching' cycle 
   with zero quantity for that asset.

Usage:
    python scripts/consistency_checker.py

Environment Variables:
    DRY_RUN: If set to 'true', only log actions without actually updating cycles
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import List, Optional

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

# Import our utilities and models
from utils.db_utils import get_db_connection, execute_query, check_connection
from models.cycle_data import DcaCycle, get_cycle_by_id, update_cycle, create_cycle
from models.asset_config import DcaAsset, get_asset_config_by_id
from utils.alpaca_client_rest import get_trading_client
from alpaca.trading.client import TradingClient
from alpaca.common.exceptions import APIError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/consistency_checker.log', mode='a') if os.path.exists('logs') else logging.NullHandler()
    ]
)
logger = logging.getLogger(__name__)

# Configuration
DRY_RUN = os.getenv('DRY_RUN', 'false').lower() == 'true'
STALE_ORDER_THRESHOLD_MINUTES = 5  # Orders older than this are considered stale


def get_current_utc_time() -> datetime:
    """Get current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


def get_stuck_buying_cycles() -> List[DcaCycle]:
    """
    Get all cycles currently in 'buying' status.
    
    Returns:
        List[DcaCycle]: List of cycles in buying status
    """
    try:
        query = """
        SELECT * FROM dca_cycles 
        WHERE status = 'buying'
        ORDER BY asset_id, created_at
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No cycles in buying status found")
            return []
        
        # Convert results to DcaCycle objects
        buying_cycles = []
        for row in results:
            cycle = DcaCycle.from_dict(row)
            buying_cycles.append(cycle)
        
        logger.info(f"Found {len(buying_cycles)} cycles in buying status")
        return buying_cycles
        
    except Exception as e:
        logger.error(f"Error fetching buying cycles: {e}")
        return []


def get_watching_cycles_with_quantity() -> List[DcaCycle]:
    """
    Get all cycles in 'watching' status with quantity > 0.
    
    Returns:
        List[DcaCycle]: List of watching cycles with quantity
    """
    try:
        query = """
        SELECT * FROM dca_cycles 
        WHERE status = 'watching' 
        AND quantity > 0
        ORDER BY asset_id, created_at
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No watching cycles with quantity found")
            return []
        
        # Convert results to DcaCycle objects
        watching_cycles = []
        for row in results:
            cycle = DcaCycle.from_dict(row)
            watching_cycles.append(cycle)
        
        logger.info(f"Found {len(watching_cycles)} watching cycles with quantity")
        return watching_cycles
        
    except Exception as e:
        logger.error(f"Error fetching watching cycles with quantity: {e}")
        return []


def is_order_stale_or_terminal(client: TradingClient, order_id: str, current_time: datetime) -> bool:
    """
    Check if an order is stale (old and open) or in a terminal state.
    
    Args:
        client: Alpaca trading client
        order_id: Order ID to check
        current_time: Current UTC time
    
    Returns:
        bool: True if order should be considered inactive, False otherwise
    """
    try:
        order = client.get_order_by_id(order_id)
        
        # Check if order is in terminal state
        terminal_states = ['filled', 'canceled', 'expired', 'rejected']
        if order.status.value.lower() in terminal_states:
            logger.info(f"Order {order_id} is in terminal state: {order.status.value}")
            return True
        
        # Check if order is stale (open but old)
        if order.status.value.lower() in ['new', 'partially_filled', 'pending_new', 'accepted']:
            # Convert order creation time to UTC if needed
            order_created_at = order.created_at
            if order_created_at.tzinfo is None:
                order_created_at = order_created_at.replace(tzinfo=timezone.utc)
            
            age_minutes = (current_time - order_created_at).total_seconds() / 60
            if age_minutes > STALE_ORDER_THRESHOLD_MINUTES:
                logger.info(f"Order {order_id} is stale (age: {age_minutes:.1f} minutes)")
                return True
        
        logger.info(f"Order {order_id} is active and recent (status: {order.status.value})")
        return False
        
    except APIError as e:
        if "order not found" in str(e).lower() or "404" in str(e):
            logger.info(f"Order {order_id} not found on Alpaca")
            return True
        else:
            logger.error(f"API error checking order {order_id}: {e}")
            return False
    except Exception as e:
        # Handle invalid order IDs (like fake test IDs) as stale/terminal
        if "badly formed" in str(e).lower() or "uuid" in str(e).lower():
            logger.info(f"Order {order_id} has invalid format (likely test/fake order)")
            return True
        logger.error(f"Error checking order {order_id}: {e}")
        return False


def process_stuck_buying_cycle(client: TradingClient, cycle: DcaCycle, current_time: datetime) -> bool:
    """
    Process a cycle stuck in 'buying' status.
    
    Args:
        client: Alpaca trading client
        cycle: The cycle in buying status
        current_time: Current UTC time
    
    Returns:
        bool: True if cycle was updated, False otherwise
    """
    try:
        logger.info(f"Processing stuck buying cycle {cycle.id} for asset {cycle.asset_id}")
        
        # Check if cycle has no order ID
        if not cycle.latest_order_id:
            logger.warning(f"Cycle {cycle.id} is in 'buying' status but has no latest_order_id")
            
            # Update cycle to watching status
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would update cycle {cycle.id} to 'watching' status (no order ID)")
                return True
            else:
                success = update_cycle(cycle.id, {'status': 'watching', 'latest_order_id': None})
                if success:
                    logger.info(f"✅ Updated cycle {cycle.id} to 'watching' status (no order ID)")
                    return True
                else:
                    logger.error(f"❌ Failed to update cycle {cycle.id}")
                    return False
        
        # Check if the order is stale or terminal
        if is_order_stale_or_terminal(client, cycle.latest_order_id, current_time):
            logger.info(f"Order {cycle.latest_order_id} for cycle {cycle.id} is inactive")
            
            # Update cycle to watching status
            if DRY_RUN:
                logger.info(f"[DRY RUN] Would update cycle {cycle.id} to 'watching' status (inactive order)")
                return True
            else:
                success = update_cycle(cycle.id, {'status': 'watching', 'latest_order_id': None})
                if success:
                    logger.info(f"✅ Updated cycle {cycle.id} to 'watching' status (inactive order)")
                    return True
                else:
                    logger.error(f"❌ Failed to update cycle {cycle.id}")
                    return False
        
        # Order is active and recent, no action needed
        logger.info(f"Cycle {cycle.id} has active order {cycle.latest_order_id}, no action needed")
        return False
        
    except Exception as e:
        logger.error(f"Error processing stuck buying cycle {cycle.id}: {e}")
        return False


def has_alpaca_position(client: TradingClient, symbol: str) -> bool:
    """
    Check if a position exists on Alpaca for the given symbol.
    
    Args:
        client: Alpaca trading client
        symbol: Asset symbol to check
    
    Returns:
        bool: True if position exists with meaningful quantity, False otherwise
    """
    try:
        position = client.get_open_position(symbol)
        
        # Check if position has meaningful quantity
        if position and position.qty and abs(float(position.qty)) > 0.0001:
            logger.info(f"Found Alpaca position for {symbol}: {position.qty}")
            return True
        else:
            logger.info(f"No meaningful Alpaca position for {symbol}")
            return False
            
    except APIError as e:
        if "position not found" in str(e).lower() or "404" in str(e):
            logger.info(f"No Alpaca position found for {symbol}")
            return False
        else:
            logger.error(f"API error checking position for {symbol}: {e}")
            return False
    except Exception as e:
        logger.error(f"Error checking position for {symbol}: {e}")
        return False


def process_orphaned_watching_cycle(client: TradingClient, cycle: DcaCycle, current_time: datetime) -> bool:
    """
    Process a 'watching' cycle that has quantity but no corresponding Alpaca position.
    
    Args:
        client: Alpaca trading client
        cycle: The watching cycle with quantity
        current_time: Current UTC time
    
    Returns:
        bool: True if cycle was processed, False otherwise
    """
    try:
        logger.info(f"Processing orphaned watching cycle {cycle.id} for asset {cycle.asset_id} (qty: {cycle.quantity})")
        
        # Get asset configuration
        asset_config = get_asset_config_by_id(cycle.asset_id)
        if not asset_config:
            logger.error(f"Asset configuration not found for asset {cycle.asset_id}")
            return False
        
        logger.info(f"Checking Alpaca position for {asset_config.asset_symbol}")
        
        # Check if position exists on Alpaca
        if has_alpaca_position(client, asset_config.asset_symbol):
            logger.info(f"Alpaca position exists for {asset_config.asset_symbol}, no action needed")
            return False
        
        # No position found - this is an inconsistency
        logger.warning(f"INCONSISTENCY: Cycle {cycle.id} has quantity {cycle.quantity} but no Alpaca position for {asset_config.asset_symbol}")
        
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would mark cycle {cycle.id} as 'error' and create new 'watching' cycle")
            return True
        else:
            # Mark current cycle as error
            error_updates = {
                'status': 'error',
                'completed_at': current_time
            }
            success1 = update_cycle(cycle.id, error_updates)
            
            if not success1:
                logger.error(f"❌ Failed to update cycle {cycle.id} to error status")
                return False
            
            logger.info(f"✅ Marked cycle {cycle.id} as 'error'")
            
            # Create new watching cycle with zero quantity
            new_cycle_id = create_cycle(
                asset_id=cycle.asset_id,
                status='watching',
                quantity=Decimal('0'),
                average_purchase_price=Decimal('0'),
                safety_orders=0,
                latest_order_id=None,
                last_order_fill_price=None
            )
            
            if new_cycle_id:
                logger.info(f"✅ Created new watching cycle {new_cycle_id} for asset {cycle.asset_id}")
                logger.info(f"🔄 Asset {asset_config.asset_symbol} is now ready for new orders")
                return True
            else:
                logger.error(f"❌ Failed to create new watching cycle for asset {cycle.asset_id}")
                return False
        
    except Exception as e:
        logger.error(f"Error processing orphaned watching cycle {cycle.id}: {e}")
        return False


def main():
    """Main consistency checking function."""
    logger.info("="*60)
    logger.info("CONSISTENCY CHECKER CARETAKER SCRIPT STARTED")
    logger.info("="*60)
    
    if DRY_RUN:
        logger.info("🔍 DRY RUN MODE: No cycles will actually be updated")
    
    try:
        # Step 1: Check database connection
        logger.info("🔧 Checking database connection...")
        if not check_connection():
            logger.error("❌ Database connection failed")
            return False
        logger.info("✅ Database connection established")
        
        # Step 2: Get Alpaca trading client
        logger.info("🔧 Initializing Alpaca trading client...")
        client = get_trading_client()
        if not client:
            logger.error("❌ Failed to initialize Alpaca trading client")
            return False
        logger.info("✅ Alpaca trading client initialized")
        
        # Step 3: Get current time
        current_time = get_current_utc_time()
        logger.info(f"🕐 Current UTC time: {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        # Step 4: Process stuck buying cycles (Scenario 1)
        logger.info("🔍 SCENARIO 1: Checking for stuck 'buying' cycles...")
        stuck_buying_cycles = get_stuck_buying_cycles()
        
        buying_processed = 0
        buying_updated = 0
        
        for cycle in stuck_buying_cycles:
            buying_processed += 1
            logger.info(f"📋 Processing buying cycle {buying_processed}/{len(stuck_buying_cycles)}: {cycle.id}")
            
            if process_stuck_buying_cycle(client, cycle, current_time):
                buying_updated += 1
        
        # Step 5: Process orphaned watching cycles (Scenario 2)
        logger.info("🔍 SCENARIO 2: Checking for orphaned 'watching' cycles...")
        orphaned_watching_cycles = get_watching_cycles_with_quantity()
        
        watching_processed = 0
        watching_updated = 0
        
        for cycle in orphaned_watching_cycles:
            watching_processed += 1
            logger.info(f"📋 Processing watching cycle {watching_processed}/{len(orphaned_watching_cycles)}: {cycle.id}")
            
            if process_orphaned_watching_cycle(client, cycle, current_time):
                watching_updated += 1
        
        # Step 6: Summary
        logger.info("="*60)
        logger.info("CONSISTENCY CHECKER SUMMARY:")
        logger.info(f"📊 Stuck buying cycles found: {len(stuck_buying_cycles)}")
        logger.info(f"📊 Buying cycles processed: {buying_processed}")
        logger.info(f"📊 Buying cycles corrected: {buying_updated}")
        logger.info(f"📊 Orphaned watching cycles found: {len(orphaned_watching_cycles)}")
        logger.info(f"📊 Watching cycles processed: {watching_processed}")
        logger.info(f"📊 Watching cycles corrected: {watching_updated}")
        
        if DRY_RUN:
            logger.info("🔍 DRY RUN: No actual updates performed")
        
        logger.info("✅ CONSISTENCY CHECKER COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR in consistency checker: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 