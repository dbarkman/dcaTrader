#!/usr/bin/env python3
"""
Asset Caretaker Script

This script performs maintenance tasks for the DCA trading system:
- Ensures all enabled assets have at least one cycle (creates 'watching' cycles if missing)
- Can be run periodically via cron for automated maintenance

Usage:
    python scripts/asset_caretaker.py
    python scripts/asset_caretaker.py --dry-run  # Show what would be done without making changes
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from utils.db_utils import execute_query
from utils.logging_config import setup_caretaker_logging
from models.asset_config import get_all_enabled_assets
from models.cycle_data import get_latest_cycle, create_cycle
from decimal import Decimal
import logging

# Setup logging
setup_caretaker_logging("asset_caretaker")
logger = logging.getLogger(__name__)


def get_enabled_assets_without_cycles() -> list:
    """
    Find enabled assets that don't have any cycles.
    
    Returns:
        list: List of asset dictionaries that need cycles
    """
    try:
        # Get all enabled assets
        enabled_assets = get_all_enabled_assets()
        
        if not enabled_assets:
            logger.info("No enabled assets found in database")
            return []
        
        assets_without_cycles = []
        
        for asset in enabled_assets:
            # Check if this asset has any cycles
            latest_cycle = get_latest_cycle(asset.id)
            
            if not latest_cycle:
                assets_without_cycles.append({
                    'id': asset.id,
                    'symbol': asset.asset_symbol,
                    'asset': asset
                })
                logger.debug(f"Asset {asset.asset_symbol} (ID: {asset.id}) has no cycles")
            else:
                logger.debug(f"Asset {asset.asset_symbol} (ID: {asset.id}) has cycle {latest_cycle.id}")
        
        return assets_without_cycles
        
    except Exception as e:
        logger.error(f"Error finding assets without cycles: {e}")
        return []


def create_watching_cycle(asset_id: int, asset_symbol: str, dry_run: bool = False) -> bool:
    """
    Create a 'watching' cycle for an asset.
    
    Args:
        asset_id: ID of the asset
        asset_symbol: Symbol of the asset (for logging)
        dry_run: If True, don't actually create the cycle
        
    Returns:
        bool: True if successful (or would be successful in dry-run), False otherwise
    """
    try:
        if dry_run:
            logger.info(f"[DRY RUN] Would create watching cycle for {asset_symbol} (ID: {asset_id})")
            return True
        
        # Create a new 'watching' cycle with default values
        new_cycle = create_cycle(
            asset_id=asset_id,
            status='watching',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            latest_order_created_at=None,
            last_order_fill_price=None,
            completed_at=None
        )
        
        if new_cycle:
            logger.info(f"✅ Created watching cycle {new_cycle.id} for {asset_symbol} (asset ID: {asset_id})")
            return True
        else:
            logger.error(f"❌ Failed to create watching cycle for {asset_symbol} (asset ID: {asset_id})")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error creating watching cycle for {asset_symbol}: {e}")
        return False


def run_maintenance(dry_run: bool = False) -> dict:
    """
    Run asset maintenance tasks.
    
    Args:
        dry_run: If True, show what would be done without making changes
        
    Returns:
        dict: Summary of maintenance results
    """
    logger.info("🔧 Starting asset maintenance...")
    
    results = {
        'assets_checked': 0,
        'cycles_created': 0,
        'errors': 0
    }
    
    # Find enabled assets without cycles
    assets_without_cycles = get_enabled_assets_without_cycles()
    results['assets_checked'] = len(assets_without_cycles)
    
    if not assets_without_cycles:
        logger.info("✅ All enabled assets have cycles - no maintenance needed")
        return results
    
    logger.info(f"Found {len(assets_without_cycles)} enabled asset(s) without cycles:")
    for asset_info in assets_without_cycles:
        logger.info(f"  - {asset_info['symbol']} (ID: {asset_info['id']})")
    
    # Create watching cycles for assets that need them
    for asset_info in assets_without_cycles:
        if create_watching_cycle(asset_info['id'], asset_info['symbol'], dry_run):
            results['cycles_created'] += 1
        else:
            results['errors'] += 1
    
    return results


def main():
    """Main function to handle command line arguments and run maintenance."""
    parser = argparse.ArgumentParser(
        description="Asset caretaker for DCA trading system maintenance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script ensures all enabled assets have the necessary database cycles.
It can be run manually or scheduled via cron for automated maintenance.

Examples:
  python scripts/asset_caretaker.py
  python scripts/asset_caretaker.py --dry-run
        """
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("DCA Trading Bot - Asset Caretaker")
    logger.info("="*60)
    
    if args.dry_run:
        logger.info("🔍 Running in DRY RUN mode - no changes will be made")
    
    # Run maintenance
    try:
        results = run_maintenance(args.dry_run)
        
        # Summary
        logger.info("="*60)
        logger.info("📊 Maintenance Summary:")
        logger.info(f"  Assets checked: {results['assets_checked']}")
        logger.info(f"  Cycles created: {results['cycles_created']}")
        logger.info(f"  Errors: {results['errors']}")
        
        if results['errors'] > 0:
            logger.warning(f"⚠️ {results['errors']} error(s) occurred during maintenance")
            sys.exit(1)
        elif results['cycles_created'] > 0:
            if args.dry_run:
                logger.info("🔍 DRY RUN completed - no actual changes made")
            else:
                logger.info("✅ Maintenance completed successfully!")
        else:
            logger.info("✅ No maintenance needed - all assets are properly configured")
            
    except Exception as e:
        logger.error(f"❌ Unexpected error during maintenance: {e}")
        logger.exception("Full traceback:")
        sys.exit(1)


if __name__ == "__main__":
    main() 