#!/usr/bin/env python3
"""
Historical Bars Fetcher for DCA Bot Backtesting

This script fetches historical 1-minute cryptocurrency bar data from Alpaca
and stores it in the historical_1min_bars table for backtesting purposes.

Features:
- Bulk fetch mode for initial historical data population
- Incremental mode for ongoing updates
- Support for multiple symbols
- Alpaca API rate limiting and pagination handling
- Robust error handling and logging

Usage:
    # Bulk fetch for specific symbols
    python scripts/fetch_historical_bars.py --symbols "BTC/USD,ETH/USD" --start-date "2024-01-01" --end-date "2024-01-31" --mode bulk
    
    # Incremental update for all configured assets
    python scripts/fetch_historical_bars.py --all-configured --mode incremental
    
    # Fetch recent data for one symbol
    python scripts/fetch_historical_bars.py --symbols "BTC/USD" --start-date "2024-12-01" --mode bulk
"""

import os
import sys
import argparse
from datetime import datetime, timedelta
from decimal import Decimal
import time
from typing import List, Dict, Optional, Tuple
import traceback

# Add src to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import Config
from utils.logging_config import setup_script_logging
from utils.db_utils import get_db_connection, execute_query
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.common.exceptions import APIError

# Global configuration
config = Config()
logger = setup_script_logging('fetch_historical_bars')

class HistoricalBarsFetcher:
    """Handles fetching and storing historical cryptocurrency bars."""
    
    def __init__(self):
        """Initialize the fetcher with Alpaca client and database connection."""
        self.client = CryptoHistoricalDataClient()
        self.rate_limit_delay = 0.2  # 200ms between requests to respect API limits
        self.batch_size = 1000  # Number of bars to process in each batch
        
    def get_asset_mapping(self) -> Dict[str, int]:
        """Get mapping of asset symbols to asset IDs from dca_assets table."""
        logger.info("🗺️ Loading asset symbol to ID mapping...")
        
        query = "SELECT id, asset_symbol FROM dca_assets WHERE is_enabled = TRUE"
        results = execute_query(query, fetch_all=True)
        
        if not results:
            logger.warning("⚠️ No enabled assets found in dca_assets table")
            return {}
        
        mapping = {row['asset_symbol']: row['id'] for row in results}
        logger.info(f"✅ Loaded {len(mapping)} asset mappings: {list(mapping.keys())}")
        return mapping
    
    def get_all_configured_symbols(self) -> List[str]:
        """Get all enabled asset symbols from dca_assets table."""
        mapping = self.get_asset_mapping()
        return list(mapping.keys())
    
    def get_latest_timestamp(self, asset_id: int) -> Optional[datetime]:
        """Get the latest timestamp for which we have data for an asset."""
        query = """
            SELECT MAX(timestamp) as latest_timestamp 
            FROM historical_1min_bars 
            WHERE asset_id = %s
        """
        
        result = execute_query(query, (asset_id,), fetch_one=True)
        
        if result and result['latest_timestamp']:
            logger.debug(f"📅 Latest timestamp for asset_id {asset_id}: {result['latest_timestamp']}")
            return result['latest_timestamp']
        
        logger.debug(f"📅 No existing data found for asset_id {asset_id}")
        return None
    
    def store_bars(self, asset_id: int, bars: List) -> int:
        """Store fetched bars in the database using upsert logic."""
        if not bars:
            return 0
        
        inserted_count = 0
        skipped_count = 0
        
        # Prepare batch insert with ON DUPLICATE KEY UPDATE (upsert)
        insert_query = """
            INSERT INTO historical_1min_bars 
            (asset_id, timestamp, open, high, low, close, volume, trade_count, vwap)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                open = VALUES(open),
                high = VALUES(high),
                low = VALUES(low),
                close = VALUES(close),
                volume = VALUES(volume),
                trade_count = VALUES(trade_count),
                vwap = VALUES(vwap),
                updated_at = CURRENT_TIMESTAMP
        """
        
        # Process bars in batches for efficiency
        for i in range(0, len(bars), self.batch_size):
            batch = bars[i:i + self.batch_size]
            batch_data = []
            
            for bar in batch:
                # Convert timestamp to naive datetime (assuming UTC)
                if bar.timestamp.tzinfo:
                    timestamp = bar.timestamp.replace(tzinfo=None)
                else:
                    timestamp = bar.timestamp
                
                # Prepare data tuple
                data_tuple = (
                    asset_id,
                    timestamp,
                    Decimal(str(bar.open)),
                    Decimal(str(bar.high)),
                    Decimal(str(bar.low)),
                    Decimal(str(bar.close)),
                    Decimal(str(bar.volume)),
                    Decimal(str(bar.trade_count)) if bar.trade_count is not None else None,
                    Decimal(str(bar.vwap)) if bar.vwap is not None else None
                )
                batch_data.append(data_tuple)
            
            try:
                # Execute batch insert
                connection = get_db_connection()
                cursor = connection.cursor()
                cursor.executemany(insert_query, batch_data)
                
                # Check how many were actually inserted vs updated
                rows_affected = cursor.rowcount
                connection.commit()
                
                inserted_count += len(batch_data)
                logger.debug(f"📥 Processed batch of {len(batch_data)} bars, {rows_affected} rows affected")
                
                cursor.close()
                connection.close()
                
            except Exception as e:
                logger.error(f"❌ Error storing batch: {e}")
                if 'connection' in locals():
                    connection.rollback()
                    connection.close()
                raise
        
        logger.info(f"✅ Stored {inserted_count} bars for asset_id {asset_id}")
        return inserted_count
    
    def fetch_bars_for_period(self, symbol: str, start_date: datetime, end_date: datetime) -> List:
        """Fetch bars for a symbol within a date range, handling pagination."""
        logger.info(f"📈 Fetching bars for {symbol} from {start_date} to {end_date}")
        
        all_bars = []
        current_start = start_date
        page_token = None
        page_count = 0
        
        while current_start < end_date:
            try:
                # Create request with pagination
                request_params = {
                    'symbol_or_symbols': [symbol],
                    'timeframe': TimeFrame.Minute,
                    'start': current_start,
                    'end': end_date,
                }
                
                if page_token:
                    request_params['page_token'] = page_token
                
                request = CryptoBarsRequest(**request_params)
                
                logger.debug(f"🔄 API request page {page_count + 1} for {symbol}")
                
                # Make API call with rate limiting
                if page_count > 0:  # Don't delay on first request
                    time.sleep(self.rate_limit_delay)
                
                response = self.client.get_crypto_bars(request)
                page_count += 1
                
                if symbol not in response.data:
                    logger.warning(f"⚠️ No data returned for {symbol}")
                    break
                
                bars = response.data[symbol]
                all_bars.extend(bars)
                
                logger.debug(f"📊 Page {page_count}: Fetched {len(bars)} bars")
                
                # Check for pagination
                if hasattr(response, 'next_page_token') and response.next_page_token:
                    page_token = response.next_page_token
                    logger.debug(f"📄 Continuing with next page token: {page_token[:20]}...")
                else:
                    logger.debug(f"📄 No more pages available")
                    break
                
                # Update current_start based on last bar timestamp to avoid gaps
                if bars:
                    last_timestamp = bars[-1].timestamp
                    current_start = last_timestamp + timedelta(minutes=1)
                
                # Safety check to prevent infinite loops
                if page_count > 1000:  # Arbitrary large number
                    logger.warning(f"⚠️ Reached maximum page limit for {symbol}")
                    break
                    
            except APIError as e:
                logger.error(f"❌ Alpaca API error for {symbol}: {e}")
                if "rate limit" in str(e).lower():
                    logger.info("⏳ Rate limit hit, waiting 60 seconds...")
                    time.sleep(60)
                    continue
                else:
                    raise
            except Exception as e:
                logger.error(f"❌ Unexpected error fetching {symbol}: {e}")
                raise
        
        logger.info(f"✅ Fetched total of {len(all_bars)} bars for {symbol} across {page_count} pages")
        return all_bars
    
    def fetch_bulk(self, symbols: List[str], start_date: datetime, end_date: datetime) -> bool:
        """Perform bulk fetch for specified symbols and date range."""
        logger.info(f"🔄 Starting BULK fetch for {len(symbols)} symbols")
        logger.info(f"📅 Date range: {start_date} to {end_date}")
        
        asset_mapping = self.get_asset_mapping()
        total_bars_stored = 0
        successful_symbols = []
        failed_symbols = []
        
        for symbol in symbols:
            if symbol not in asset_mapping:
                logger.error(f"❌ Symbol {symbol} not found in dca_assets table")
                failed_symbols.append(symbol)
                continue
            
            asset_id = asset_mapping[symbol]
            
            try:
                logger.info(f"🔄 Processing {symbol} (asset_id: {asset_id})")
                
                # Fetch bars
                bars = self.fetch_bars_for_period(symbol, start_date, end_date)
                
                if bars:
                    # Store bars
                    stored_count = self.store_bars(asset_id, bars)
                    total_bars_stored += stored_count
                    successful_symbols.append(symbol)
                    
                    logger.info(f"✅ {symbol}: Stored {stored_count} bars")
                else:
                    logger.warning(f"⚠️ {symbol}: No bars received")
                    
            except Exception as e:
                logger.error(f"❌ Failed to process {symbol}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                failed_symbols.append(symbol)
                continue
        
        # Summary
        logger.info(f"\n🎉 BULK FETCH COMPLETED")
        logger.info(f"✅ Successful: {len(successful_symbols)} symbols - {successful_symbols}")
        logger.info(f"❌ Failed: {len(failed_symbols)} symbols - {failed_symbols}")
        logger.info(f"📊 Total bars stored: {total_bars_stored}")
        
        return len(failed_symbols) == 0
    
    def fetch_incremental(self, symbols: List[str], end_date: Optional[datetime] = None) -> bool:
        """Perform incremental fetch for specified symbols."""
        if end_date is None:
            end_date = datetime.now()
        
        logger.info(f"🔄 Starting INCREMENTAL fetch for {len(symbols)} symbols")
        logger.info(f"📅 End date: {end_date}")
        
        asset_mapping = self.get_asset_mapping()
        total_bars_stored = 0
        successful_symbols = []
        failed_symbols = []
        
        for symbol in symbols:
            if symbol not in asset_mapping:
                logger.error(f"❌ Symbol {symbol} not found in dca_assets table")
                failed_symbols.append(symbol)
                continue
            
            asset_id = asset_mapping[symbol]
            
            try:
                logger.info(f"🔄 Processing {symbol} (asset_id: {asset_id})")
                
                # Get latest timestamp
                latest_timestamp = self.get_latest_timestamp(asset_id)
                
                if latest_timestamp:
                    # Start from next minute after latest data
                    start_date = latest_timestamp + timedelta(minutes=1)
                    logger.info(f"📅 {symbol}: Latest data at {latest_timestamp}, fetching from {start_date}")
                else:
                    # No existing data, start from a reasonable default
                    start_date = end_date - timedelta(days=30)  # Last 30 days
                    logger.info(f"📅 {symbol}: No existing data, starting from {start_date}")
                
                # Skip if start_date is in the future
                if start_date >= end_date:
                    logger.info(f"✅ {symbol}: Data is already up to date")
                    successful_symbols.append(symbol)
                    continue
                
                # Fetch bars
                bars = self.fetch_bars_for_period(symbol, start_date, end_date)
                
                if bars:
                    # Store bars
                    stored_count = self.store_bars(asset_id, bars)
                    total_bars_stored += stored_count
                    successful_symbols.append(symbol)
                    
                    logger.info(f"✅ {symbol}: Stored {stored_count} new bars")
                else:
                    logger.info(f"✅ {symbol}: No new bars available")
                    successful_symbols.append(symbol)
                    
            except Exception as e:
                logger.error(f"❌ Failed to process {symbol}: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                failed_symbols.append(symbol)
                continue
        
        # Summary
        logger.info(f"\n🎉 INCREMENTAL FETCH COMPLETED")
        logger.info(f"✅ Successful: {len(successful_symbols)} symbols - {successful_symbols}")
        logger.info(f"❌ Failed: {len(failed_symbols)} symbols - {failed_symbols}")
        logger.info(f"📊 Total new bars stored: {total_bars_stored}")
        
        return len(failed_symbols) == 0

def parse_date(date_string: str) -> datetime:
    """Parse date string in YYYY-MM-DD format."""
    try:
        return datetime.strptime(date_string, '%Y-%m-%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_string}. Use YYYY-MM-DD")

def main():
    """Main function to handle command line arguments and execute fetching."""
    parser = argparse.ArgumentParser(
        description="Fetch historical 1-minute cryptocurrency bars from Alpaca",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Bulk fetch for specific symbols
  python scripts/fetch_historical_bars.py --symbols "BTC/USD,ETH/USD" --start-date "2024-01-01" --end-date "2024-01-31" --mode bulk
  
  # Incremental update for all configured assets
  python scripts/fetch_historical_bars.py --all-configured --mode incremental
  
  # Fetch recent data for one symbol
  python scripts/fetch_historical_bars.py --symbols "BTC/USD" --start-date "2024-12-01" --mode bulk
        """
    )
    
    # Symbol selection (mutually exclusive)
    symbol_group = parser.add_mutually_exclusive_group(required=True)
    symbol_group.add_argument(
        '--symbols',
        type=str,
        help='Comma-separated list of asset symbols (e.g., "BTC/USD,ETH/USD")'
    )
    symbol_group.add_argument(
        '--all-configured',
        action='store_true',
        help='Fetch for all assets in dca_assets table'
    )
    
    # Date parameters
    parser.add_argument(
        '--start-date',
        type=parse_date,
        help='Start date in YYYY-MM-DD format (required for bulk mode)'
    )
    parser.add_argument(
        '--end-date',
        type=parse_date,
        default=datetime.now(),
        help='End date in YYYY-MM-DD format (defaults to current date)'
    )
    
    # Mode selection
    parser.add_argument(
        '--mode',
        choices=['bulk', 'incremental'],
        required=True,
        help='Fetch mode: bulk (initial fetch) or incremental (updates)'
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Validation
    if args.mode == 'bulk' and not args.start_date:
        parser.error("--start-date is required for bulk mode")
    
    if args.start_date and args.end_date and args.start_date >= args.end_date:
        parser.error("start-date must be before end-date")
    
    logger.info("🚀 Starting Historical Bars Fetcher")
    logger.info(f"Mode: {args.mode}")
    
    try:
        # Initialize fetcher
        fetcher = HistoricalBarsFetcher()
        
        # Determine symbols to process
        if args.symbols:
            symbols = [s.strip() for s in args.symbols.split(',')]
            logger.info(f"📊 Processing specified symbols: {symbols}")
        else:
            symbols = fetcher.get_all_configured_symbols()
            logger.info(f"📊 Processing all configured symbols: {symbols}")
        
        if not symbols:
            logger.error("❌ No symbols to process")
            return 1
        
        # Execute based on mode
        if args.mode == 'bulk':
            success = fetcher.fetch_bulk(symbols, args.start_date, args.end_date)
        else:  # incremental
            success = fetcher.fetch_incremental(symbols, args.end_date)
        
        if success:
            logger.info("🎉 All operations completed successfully!")
            return 0
        else:
            logger.warning("⚠️ Some operations failed - check logs for details")
            return 1
            
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code) 