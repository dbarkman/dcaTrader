#!/usr/bin/env python3
"""
Cooldown Manager Caretaker Script

This script manages cooldown period expiration for DCA Trading Bot cycles.
It should be run periodically via cron to transition cycles from 'cooldown' to 'watching'
when their configured cooldown period has expired.

Functions:
1. Find cycles in 'cooldown' status
2. Check if cooldown period has expired based on previous cycle's completed_at timestamp
3. Update expired cooldown cycles to 'watching' status

Usage:
    python scripts/cooldown_manager.py

Environment Variables:
    DRY_RUN: If set to 'true', only log actions without actually updating cycles
"""

import sys
import os
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

# Import our utilities and models
from utils.db_utils import get_db_connection, execute_query, check_connection
from utils.logging_config import setup_caretaker_logging
from models.cycle_data import DcaCycle, get_cycle_by_id, update_cycle
from models.asset_config import DcaAsset, get_asset_config, get_asset_config_by_id

# Setup logging
setup_caretaker_logging("cooldown_manager")
logger = logging.getLogger(__name__)

# Import configuration
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from config import get_config

config = get_config()

# Configuration
DRY_RUN = config.dry_run_mode


def get_current_utc_time() -> datetime:
    """Get current UTC time with timezone awareness."""
    return datetime.now(timezone.utc)


def get_cooldown_cycles() -> List[DcaCycle]:
    """
    Get all cycles currently in 'cooldown' status.
    
    Returns:
        List[DcaCycle]: List of cycles in cooldown status
    """
    try:
        query = """
        SELECT * FROM dca_cycles 
        WHERE status = 'cooldown'
        ORDER BY asset_id, created_at
        """
        
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.info("No cycles in cooldown status found")
            return []
        
        # Convert results to DcaCycle objects
        cooldown_cycles = []
        for row in results:
            cycle = DcaCycle.from_dict(row)
            cooldown_cycles.append(cycle)
        
        logger.info(f"Found {len(cooldown_cycles)} cycles in cooldown status")
        return cooldown_cycles
        
    except Exception as e:
        logger.error(f"Error fetching cooldown cycles: {e}")
        return []


def get_previous_completed_cycle(asset_id: int, cooldown_cycle_created_at: datetime) -> Optional[DcaCycle]:
    """
    Get the most recent completed cycle for an asset that occurred before the cooldown cycle.
    
    Args:
        asset_id: Asset ID to search for
        cooldown_cycle_created_at: Creation time of the cooldown cycle
    
    Returns:
        Optional[DcaCycle]: The previous completed cycle, or None if not found
    """
    try:
        query = """
        SELECT * FROM dca_cycles 
        WHERE asset_id = %s 
        AND status IN ('complete', 'error') 
        AND completed_at IS NOT NULL 
        AND created_at < %s 
        ORDER BY completed_at DESC 
        LIMIT 1
        """
        
        result = execute_query(query, (asset_id, cooldown_cycle_created_at), fetch_one=True)
        
        if not result:
            logger.warning(f"No previous completed cycle found for asset {asset_id}")
            return None
        
        previous_cycle = DcaCycle.from_dict(result)
        logger.info(f"Found previous completed cycle {previous_cycle.id} for asset {asset_id} "
                   f"(completed at: {previous_cycle.completed_at})")
        return previous_cycle
        
    except Exception as e:
        logger.error(f"Error fetching previous completed cycle for asset {asset_id}: {e}")
        return None


def is_cooldown_expired(previous_cycle: DcaCycle, asset_config: DcaAsset, current_time: datetime) -> bool:
    """
    Check if the cooldown period has expired.
    
    Args:
        previous_cycle: The previous completed cycle
        asset_config: Asset configuration with cooldown_period
        current_time: Current UTC time
    
    Returns:
        bool: True if cooldown has expired, False otherwise
    """
    if not previous_cycle.completed_at:
        logger.warning(f"Previous cycle {previous_cycle.id} has no completed_at timestamp")
        return False
    
    # Ensure completed_at is timezone-aware (assume UTC if naive)
    completed_at = previous_cycle.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=timezone.utc)
    
    # Calculate cooldown expiry time
    cooldown_expiry_time = completed_at + timedelta(seconds=asset_config.cooldown_period)
    
    # Check if cooldown has expired
    expired = current_time >= cooldown_expiry_time
    
    if expired:
        logger.info(f"Cooldown expired for asset {asset_config.id}:")
        logger.info(f"  Previous cycle completed: {completed_at}")
        logger.info(f"  Cooldown period: {asset_config.cooldown_period} seconds")
        logger.info(f"  Expiry time: {cooldown_expiry_time}")
        logger.info(f"  Current time: {current_time}")
        logger.info(f"  Time since expiry: {current_time - cooldown_expiry_time}")
    else:
        time_remaining = cooldown_expiry_time - current_time
        logger.info(f"Cooldown not yet expired for asset {asset_config.id} "
                   f"(remaining: {time_remaining.total_seconds():.0f}s)")
    
    return expired


def process_cooldown_cycle(cooldown_cycle: DcaCycle, current_time: datetime) -> bool:
    """
    Process a single cooldown cycle to check if it should be updated to 'watching'.
    
    Args:
        cooldown_cycle: The cycle in cooldown status
        current_time: Current UTC time
    
    Returns:
        bool: True if cycle was updated, False otherwise
    """
    try:
        logger.info(f"Processing cooldown cycle {cooldown_cycle.id} for asset {cooldown_cycle.asset_id}")
        
        # Get asset configuration
        asset_config = get_asset_config_by_id(cooldown_cycle.asset_id)
        if not asset_config:
            logger.error(f"Asset configuration not found for asset {cooldown_cycle.asset_id}")
            return False
        
        logger.info(f"Asset {asset_config.asset_symbol} cooldown period: {asset_config.cooldown_period} seconds")
        
        # Get previous completed cycle
        previous_cycle = get_previous_completed_cycle(cooldown_cycle.asset_id, cooldown_cycle.created_at)
        if not previous_cycle:
            logger.warning(f"No previous completed cycle found for cooldown cycle {cooldown_cycle.id}")
            return False
        
        # Check if cooldown has expired
        if not is_cooldown_expired(previous_cycle, asset_config, current_time):
            return False
        
        # Update cycle status to 'watching'
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would update cooldown cycle {cooldown_cycle.id} to 'watching' status")
            return True
        else:
            success = update_cycle(cooldown_cycle.id, {'status': 'watching'})
            if success:
                logger.info(f"✅ Updated cooldown cycle {cooldown_cycle.id} to 'watching' status")
                logger.info(f"🔄 Asset {asset_config.asset_symbol} is now ready for new orders")
                return True
            else:
                logger.error(f"❌ Failed to update cooldown cycle {cooldown_cycle.id}")
                return False
        
    except Exception as e:
        logger.error(f"Error processing cooldown cycle {cooldown_cycle.id}: {e}")
        return False


def main():
    """Main cooldown management function."""
    logger.info("="*60)
    logger.info("COOLDOWN MANAGER CARETAKER SCRIPT STARTED")
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
        
        # Step 2: Get current time
        current_time = get_current_utc_time()
        logger.info(f"🕐 Current UTC time: {current_time.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        
        # Step 3: Get all cooldown cycles
        logger.info("🔍 Fetching cycles in cooldown status...")
        cooldown_cycles = get_cooldown_cycles()
        
        if not cooldown_cycles:
            logger.info("✅ No cooldown cycles found - nothing to process")
            return True
        
        # Step 4: Process each cooldown cycle
        logger.info(f"🔄 Processing {len(cooldown_cycles)} cooldown cycles...")
        
        updated_count = 0
        processed_count = 0
        
        for cycle in cooldown_cycles:
            processed_count += 1
            logger.info(f"📋 Processing cycle {processed_count}/{len(cooldown_cycles)}: {cycle.id}")
            
            if process_cooldown_cycle(cycle, current_time):
                updated_count += 1
        
        # Step 5: Summary
        logger.info("="*60)
        logger.info("COOLDOWN MANAGER SUMMARY:")
        logger.info(f"📊 Total cooldown cycles found: {len(cooldown_cycles)}")
        logger.info(f"📊 Cycles processed: {processed_count}")
        logger.info(f"📊 Cycles updated to 'watching': {updated_count}")
        logger.info(f"📊 Cycles still in cooldown: {len(cooldown_cycles) - updated_count}")
        
        if DRY_RUN:
            logger.info("🔍 DRY RUN: No actual updates performed")
        
        logger.info("✅ COOLDOWN MANAGER COMPLETED SUCCESSFULLY")
        logger.info("="*60)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ CRITICAL ERROR in cooldown manager: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1) 