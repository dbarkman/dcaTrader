#!/usr/bin/env python3
"""
Add Asset Script

This script adds new cryptocurrency assets to the dca_assets table.
Assets can be added as enabled or disabled based on the --enabled flag.

Usage:
    python scripts/add_asset.py BTC/USD,ETH/USD,SOL/USD --enabled
    python scripts/add_asset.py DOGE/USD  # Adds as disabled
"""

import argparse
import sys
import os
from pathlib import Path

# Add src directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from utils.db_utils import execute_query
from utils.logging_config import setup_caretaker_logging
import logging

# Setup logging
setup_caretaker_logging("add_asset")
logger = logging.getLogger(__name__)


def validate_asset_symbol(symbol: str) -> bool:
    """
    Validate that the asset symbol follows the expected format.
    
    Args:
        symbol: Asset symbol to validate (e.g., 'BTC/USD')
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not symbol or '/' not in symbol:
        return False
    
    parts = symbol.split('/')
    if len(parts) != 2:
        return False
    
    base, quote = parts
    if not base or not quote:
        return False
    
    # Basic validation - alphanumeric characters only
    if not base.isalnum() or not quote.isalnum():
        return False
    
    return True


def asset_exists(symbol: str) -> bool:
    """
    Check if an asset already exists in the database.
    
    Args:
        symbol: Asset symbol to check
        
    Returns:
        bool: True if asset exists, False otherwise
    """
    try:
        query = "SELECT id FROM dca_assets WHERE asset_symbol = %s"
        result = execute_query(query, (symbol,), fetch_one=True)
        return result is not None
    except Exception as e:
        logger.error(f"Error checking if asset {symbol} exists: {e}")
        return False


def add_asset(symbol: str, enabled: bool = False) -> bool:
    """
    Add a new asset to the dca_assets table.
    
    Args:
        symbol: Asset symbol (e.g., 'BTC/USD')
        enabled: Whether the asset should be enabled (default: False)
        
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Check if asset already exists
        if asset_exists(symbol):
            logger.warning(f"Asset {symbol} already exists in database")
            return False
        
        # Insert new asset - let database defaults handle other fields
        query = """
        INSERT INTO dca_assets (asset_symbol, is_enabled)
        VALUES (%s, %s)
        """
        
        asset_id = execute_query(query, (symbol, 1 if enabled else 0), commit=True)
        
        if asset_id:
            status = "enabled" if enabled else "disabled"
            logger.info(f"✅ Successfully added asset {symbol} (ID: {asset_id}) as {status}")
            return True
        else:
            logger.error(f"❌ Failed to add asset {symbol} - no ID returned")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error adding asset {symbol}: {e}")
        return False


def parse_asset_list(asset_string: str) -> list:
    """
    Parse comma-separated asset symbols.
    
    Args:
        asset_string: Comma-separated asset symbols
        
    Returns:
        list: List of validated asset symbols
    """
    if not asset_string:
        return []
    
    # Split by comma and clean up whitespace
    symbols = [symbol.strip().upper() for symbol in asset_string.split(',')]
    
    # Validate each symbol
    valid_symbols = []
    for symbol in symbols:
        if validate_asset_symbol(symbol):
            valid_symbols.append(symbol)
        else:
            logger.error(f"❌ Invalid asset symbol format: {symbol}")
    
    return valid_symbols


def main():
    """Main function to handle command line arguments and add assets."""
    parser = argparse.ArgumentParser(
        description="Add cryptocurrency assets to the DCA trading system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/add_asset.py BTC/USD --enabled
  python scripts/add_asset.py BTC/USD,ETH/USD,SOL/USD --enabled
  python scripts/add_asset.py DOGE/USD  # Adds as disabled
        """
    )
    
    parser.add_argument(
        'assets',
        help='Comma-separated list of asset symbols (e.g., BTC/USD,ETH/USD)'
    )
    
    parser.add_argument(
        '--enabled',
        action='store_true',
        help='Add assets as enabled (default: disabled)'
    )
    
    args = parser.parse_args()
    
    logger.info("="*60)
    logger.info("DCA Trading Bot - Add Asset Script")
    logger.info("="*60)
    
    # Parse and validate asset symbols
    symbols = parse_asset_list(args.assets)
    
    if not symbols:
        logger.error("❌ No valid asset symbols provided")
        sys.exit(1)
    
    logger.info(f"Adding {len(symbols)} asset(s) as {'enabled' if args.enabled else 'disabled'}:")
    for symbol in symbols:
        logger.info(f"  - {symbol}")
    
    # Add each asset
    success_count = 0
    for symbol in symbols:
        if add_asset(symbol, args.enabled):
            success_count += 1
    
    # Summary
    logger.info("="*60)
    logger.info(f"✅ Successfully added {success_count}/{len(symbols)} assets")
    
    if success_count < len(symbols):
        logger.warning(f"⚠️ {len(symbols) - success_count} assets were skipped (already exist or failed)")
        sys.exit(1)
    
    logger.info("🎉 All assets added successfully!")


if __name__ == "__main__":
    main() 