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
import decimal
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

# Import configuration
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from config import get_config

config = get_config()

# Configuration
DRY_RUN = config.dry_run_mode
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


def get_all_watching_cycles() -> List[DcaCycle]:
    """
    Get all cycles in 'watching' status (regardless of quantity).
    
    Returns:
        List[DcaCycle]: List of all watching cycles
    """
    try:
        query = """
        SELECT * FROM dca_cycles 
        WHERE status = 'watching'
        ORDER BY asset_id, created_at
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No watching cycles found")
            return []
        
        # Convert results to DcaCycle objects
        watching_cycles = []
        for row in results:
            cycle = DcaCycle.from_dict(row)
            watching_cycles.append(cycle)
        
        logger.info(f"Found {len(watching_cycles)} watching cycles")
        return watching_cycles
        
    except Exception as e:
        logger.error(f"Error fetching watching cycles: {e}")
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
        # Import get_positions from alpaca_client_rest
        from utils.alpaca_client_rest import get_positions
        
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


def has_alpaca_position(client: TradingClient, symbol: str) -> bool:
    """
    Check if a position exists on Alpaca for the given symbol.
    
    Args:
        client: Alpaca trading client
        symbol: Asset symbol to check (e.g., 'UNI/USD')
    
    Returns:
        bool: True if position exists with meaningful quantity, False otherwise
    """
    try:
        # Convert symbol format for Alpaca API (UNI/USD -> UNIUSD)
        alpaca_symbol = symbol.replace('/', '')
        position = client.get_open_position(alpaca_symbol)
        
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


def process_watching_cycle_with_position_sync(client: TradingClient, cycle: DcaCycle, current_time: datetime) -> bool:
    """
    Process a 'watching' cycle with enhanced position synchronization.
    
    This function handles both position synchronization and orphaned cycle detection:
    1. If Alpaca position exists: Sync quantity and average_purchase_price if different
    2. If no Alpaca position but DB has quantity > 0: Mark as error and create new cycle
    3. If no Alpaca position and DB has quantity = 0: No action needed (consistent)
    
    Args:
        client: Alpaca trading client
        cycle: The watching cycle to process
        current_time: Current UTC time
    
    Returns:
        bool: True if cycle was updated/processed, False otherwise
    """
    try:
        logger.info(f"Processing watching cycle {cycle.id} for asset {cycle.asset_id} (qty: {cycle.quantity})")
        
        # Get asset configuration
        asset_config = get_asset_config_by_id(cycle.asset_id)
        if not asset_config:
            logger.error(f"Asset configuration not found for asset {cycle.asset_id}")
            return False
        
        logger.info(f"Checking Alpaca position for {asset_config.asset_symbol}")
        
        # Get current Alpaca position
        alpaca_position = get_alpaca_position_by_symbol(client, asset_config.asset_symbol)
        
        if alpaca_position:
            # Position exists on Alpaca - check for synchronization needs
            try:
                alpaca_qty = Decimal(str(alpaca_position.qty))
                alpaca_avg_price = Decimal(str(alpaca_position.avg_entry_price))
                
                logger.info(f"Alpaca position found: {alpaca_qty} @ ${alpaca_avg_price:.4f}")
                logger.info(f"DB cycle data: {cycle.quantity} @ ${cycle.average_purchase_price:.4f}")
                
                # Check if synchronization is needed
                qty_differs = cycle.quantity != alpaca_qty
                price_differs = cycle.average_purchase_price != alpaca_avg_price
                
                if qty_differs or price_differs:
                    logger.warning(f"POSITION SYNC NEEDED for cycle {cycle.id}:")
                    if qty_differs:
                        logger.warning(f"  Quantity: DB={cycle.quantity} vs Alpaca={alpaca_qty}")
                    if price_differs:
                        logger.warning(f"  Avg Price: DB=${cycle.average_purchase_price:.4f} vs Alpaca=${alpaca_avg_price:.4f}")
                    
                    if DRY_RUN:
                        logger.info(f"[DRY RUN] Would sync cycle {cycle.id} with Alpaca position data")
                        return True
                    else:
                        # Sync with Alpaca position data
                        updates = {
                            'quantity': alpaca_qty,
                            'average_purchase_price': alpaca_avg_price
                        }
                        # Important: Do NOT update last_order_fill_price or safety_orders count
                        
                        success = update_cycle(cycle.id, updates)
                        if success:
                            logger.info(f"✅ Synced cycle {cycle.id} with Alpaca position:")
                            logger.info(f"   Updated quantity: {cycle.quantity} → {alpaca_qty}")
                            logger.info(f"   Updated avg price: ${cycle.average_purchase_price:.4f} → ${alpaca_avg_price:.4f}")
                            logger.info(f"   Preserved: last_order_fill_price={cycle.last_order_fill_price}, safety_orders={cycle.safety_orders}")
                            return True
                        else:
                            logger.error(f"❌ Failed to sync cycle {cycle.id} with Alpaca position")
                            return False
                else:
                    logger.info(f"Cycle {cycle.id} is already in sync with Alpaca position")
                    return False
                    
            except (ValueError, TypeError, decimal.InvalidOperation) as e:
                logger.error(f"Error parsing Alpaca position data for {asset_config.asset_symbol}: {e}")
                return False
        
        else:
            # No position exists on Alpaca
            if cycle.quantity > Decimal('0'):
                # DB thinks there should be a position - this is an inconsistency
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
            else:
                # DB has quantity = 0 and no Alpaca position - this is consistent
                logger.info(f"Cycle {cycle.id} is consistent: no position on Alpaca and quantity=0 in DB")
                return False
        
    except Exception as e:
        logger.error(f"Error processing watching cycle {cycle.id}: {e}")
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
        
        # Step 5: Process watching cycles with position synchronization (Enhanced Scenario 2)
        logger.info("🔍 SCENARIO 2: Checking 'watching' cycles for position synchronization...")
        all_watching_cycles = get_all_watching_cycles()
        
        watching_processed = 0
        watching_updated = 0
        
        for cycle in all_watching_cycles:
            watching_processed += 1
            logger.info(f"📋 Processing watching cycle {watching_processed}/{len(all_watching_cycles)}: {cycle.id}")
            
            if process_watching_cycle_with_position_sync(client, cycle, current_time):
                watching_updated += 1
        
        # Step 6: Summary
        logger.info("="*60)
        logger.info("CONSISTENCY CHECKER SUMMARY:")
        logger.info(f"📊 Stuck buying cycles found: {len(stuck_buying_cycles)}")
        logger.info(f"📊 Buying cycles processed: {buying_processed}")
        logger.info(f"📊 Buying cycles corrected: {buying_updated}")
        logger.info(f"📊 Watching cycles found: {len(all_watching_cycles)}")
        logger.info(f"📊 Watching cycles processed: {watching_processed}")
        logger.info(f"📊 Watching cycles synced/corrected: {watching_updated}")
        
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