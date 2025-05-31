#!/usr/bin/env python3
"""
Phase 3: Backtesting Engine - Core Loop & Data Feeder

This script creates the basic structure of the backtesting engine that:
1. Reads historical 1-minute bars from the database
2. Feeds them to our refactored strategy logic
3. Logs the strategy intents (orders, state changes)
4. Manages in-memory DcaCycle state

Usage:
    python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2024-01-01" --end-date "2024-01-02"
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Iterator, Optional, Any
import traceback

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Project imports
from config import config
from utils.logging_config import setup_logging
from utils.db_utils import get_db_connection, execute_query
from models.asset_config import DcaAsset, get_asset_config
from models.cycle_data import DcaCycle
from strategy_logic import decide_base_order_action, decide_safety_order_action, decide_take_profit_action
from models.backtest_structs import MarketTickInput, StrategyAction


class HistoricalDataFeeder:
    """
    Feeds historical 1-minute bar data from the database for backtesting.
    """
    
    def __init__(self, asset_id: int, start_date: datetime, end_date: datetime):
        """
        Initialize the data feeder.
        
        Args:
            asset_id: Database ID of the asset to fetch data for
            start_date: Start date for historical data (UTC)
            end_date: End date for historical data (UTC)
        """
        self.asset_id = asset_id
        self.start_date = start_date
        self.end_date = end_date
        self._data_cache = None
        
    def fetch_data(self) -> List[Dict[str, Any]]:
        """
        Fetch historical bar data from the database.
        
        Returns:
            List of bar dictionaries with timestamp, open, high, low, close, volume
        """
        if self._data_cache is not None:
            return self._data_cache
            
        query = """
        SELECT timestamp, open_price, high_price, low_price, close_price, volume
        FROM historical_1min_bars
        WHERE asset_id = %s 
        AND timestamp >= %s 
        AND timestamp <= %s
        ORDER BY timestamp ASC
        """
        
        try:
            rows = execute_query(
                query,
                (self.asset_id, self.start_date, self.end_date),
                fetch_all=True
            )
            
            # Convert to list of dictionaries
            bars = []
            for row in rows:
                bars.append({
                    'timestamp': row['timestamp'],
                    'open': Decimal(str(row['open_price'])),
                    'high': Decimal(str(row['high_price'])),
                    'low': Decimal(str(row['low_price'])),
                    'close': Decimal(str(row['close_price'])),
                    'volume': Decimal(str(row['volume']))
                })
                
            self._data_cache = bars
            return bars
            
        except Exception as e:
            logging.error(f"Error fetching historical data: {e}")
            raise
            
    def get_bars(self) -> Iterator[Dict[str, Any]]:
        """
        Generator that yields historical bars one at a time.
        
        Yields:
            Dict containing bar data
        """
        bars = self.fetch_data()
        for bar in bars:
            yield bar
            
    def get_bar_count(self) -> int:
        """Get total number of bars in the dataset."""
        return len(self.fetch_data())


class BacktestSimulation:
    """
    Manages the in-memory state for backtesting simulation.
    """
    
    def __init__(self, asset_config: DcaAsset):
        """
        Initialize simulation state.
        
        Args:
            asset_config: Asset configuration for the backtest
        """
        self.asset_config = asset_config
        self.logger = logging.getLogger('backtest_sim')
        
        # Initialize in-memory cycle state
        self.current_cycle = DcaCycle(
            id=0,  # Simulated cycle ID
            asset_id=asset_config.id,
            status='watching',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            latest_order_created_at=None,
            last_order_fill_price=None,
            highest_trailing_price=None,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        # Simulation state
        self.current_alpaca_position = None  # Mock position for base order checks
        self.order_counter = 0  # For generating simulated order IDs
        
    def get_next_order_id(self) -> str:
        """Generate a simulated order ID."""
        self.order_counter += 1
        return f"sim_order_{self.order_counter}"
        
    def process_strategy_action(self, action: StrategyAction, current_timestamp: datetime) -> None:
        """
        Process a strategy action by updating in-memory cycle state.
        
        Args:
            action: Strategy action with intents to process
            current_timestamp: Current simulation timestamp
        """
        if not action or not action.has_action():
            return
            
        # Process order intent (just log for now)
        if action.order_intent:
            order_id = self.get_next_order_id()
            self.logger.info(f"📋 ORDER INTENT: {action.order_intent.side.value.upper()} "
                           f"{action.order_intent.order_type.value.upper()} - "
                           f"Symbol: {action.order_intent.symbol}, "
                           f"Quantity: {action.order_intent.quantity}, "
                           f"Price: {action.order_intent.limit_price or 'MARKET'}, "
                           f"Simulated ID: {order_id}")
        
        # Process cycle state update intent
        if action.cycle_update_intent:
            intent = action.cycle_update_intent
            
            if intent.new_status:
                old_status = self.current_cycle.status
                self.current_cycle.status = intent.new_status
                self.logger.info(f"🔄 CYCLE STATUS: {old_status} → {intent.new_status}")
                
            if intent.new_latest_order_id or action.order_intent:
                self.current_cycle.latest_order_id = self.get_next_order_id()
                self.current_cycle.latest_order_created_at = current_timestamp
                
            if intent.new_quantity is not None:
                self.current_cycle.quantity = intent.new_quantity
                self.logger.info(f"📊 QUANTITY: {intent.new_quantity}")
                
            if intent.new_average_purchase_price is not None:
                self.current_cycle.average_purchase_price = intent.new_average_purchase_price
                self.logger.info(f"💰 AVG PRICE: ${intent.new_average_purchase_price}")
                
            if intent.new_safety_orders is not None:
                self.current_cycle.safety_orders = intent.new_safety_orders
                self.logger.info(f"🛡️ SAFETY ORDERS: {intent.new_safety_orders}")
                
            if intent.new_last_order_fill_price is not None:
                self.current_cycle.last_order_fill_price = intent.new_last_order_fill_price
                self.logger.info(f"📈 LAST FILL PRICE: ${intent.new_last_order_fill_price}")
        
        # Process TTP state update intent
        if action.ttp_update_intent:
            intent = action.ttp_update_intent
            
            if intent.new_status:
                old_status = self.current_cycle.status
                self.current_cycle.status = intent.new_status
                self.logger.info(f"🎯 TTP STATUS: {old_status} → {intent.new_status}")
                
            if intent.new_highest_trailing_price is not None:
                self.current_cycle.highest_trailing_price = intent.new_highest_trailing_price
                self.logger.info(f"⬆️ TTP PEAK: ${intent.new_highest_trailing_price}")
    
    def log_cycle_state(self) -> None:
        """Log current cycle state for debugging."""
        self.logger.debug(f"💾 CYCLE STATE: Status={self.current_cycle.status}, "
                         f"Qty={self.current_cycle.quantity}, "
                         f"AvgPrice=${self.current_cycle.average_purchase_price}, "
                         f"SafetyOrders={self.current_cycle.safety_orders}, "
                         f"TTPPeak=${self.current_cycle.highest_trailing_price}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DCA Trading Bot Backtesting Engine - Phase 3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2024-01-01" --end-date "2024-01-02"
  python scripts/run_backtest.py --asset-id 1 --start-date "2024-01-01" --end-date "2024-01-02"
        """
    )
    
    parser.add_argument(
        '--symbol',
        type=str,
        help='Trading symbol (e.g., "BTC/USD"). Required if --asset-id not provided.'
    )
    
    parser.add_argument(
        '--asset-id',
        type=int,
        help='Asset ID from dca_assets table. Takes precedence over --symbol.'
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD format'
    )
    
    parser.add_argument(
        '--end-date', 
        type=str,
        required=True,
        help='End date in YYYY-MM-DD format'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Validate that either symbol or asset-id is provided
    if not args.symbol and not args.asset_id:
        parser.error("Either --symbol or --asset-id must be provided")
        
    return args


def setup_backtest_logging(log_level: str) -> logging.Logger:
    """Setup logging specific to the backtester."""
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/backtest.log'),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger('backtest')


def main():
    """Main backtesting function."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Setup logging
        logger = setup_backtest_logging(args.log_level)
        logger.info("🚀 Starting DCA Backtesting Engine - Phase 3")
        
        # Parse dates
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            return 1
            
        # Load asset configuration
        if args.asset_id:
            # Load by asset ID (would need a function to get asset by ID)
            asset_config = execute_query(
                "SELECT * FROM dca_assets WHERE id = %s",
                (args.asset_id,),
                fetch_one=True
            )
            if not asset_config:
                logger.error(f"Asset with ID {args.asset_id} not found")
                return 1
            # Convert to DcaAsset object (simplified for now)
            symbol = asset_config['symbol']
        else:
            # Load by symbol
            symbol = args.symbol
            asset_config = get_asset_config(symbol)
            if not asset_config:
                logger.error(f"Asset configuration for {symbol} not found")
                return 1
                
        logger.info(f"📊 Asset: {symbol}")
        logger.info(f"📅 Date Range: {start_date.date()} to {end_date.date()}")
        logger.info(f"⚙️ Config: Base=${asset_config.base_order_amount}, "
                   f"Safety=${asset_config.safety_order_amount}, "
                   f"Max Safety={asset_config.max_safety_orders}, "
                   f"TP={asset_config.take_profit_percent}%, "
                   f"TTP={asset_config.ttp_enabled}")
        
        # Initialize historical data feeder
        data_feeder = HistoricalDataFeeder(asset_config.id, start_date, end_date)
        bar_count = data_feeder.get_bar_count()
        logger.info(f"📈 Historical bars loaded: {bar_count}")
        
        if bar_count == 0:
            logger.warning("No historical data found for the specified date range")
            return 1
            
        # Initialize simulation
        simulation = BacktestSimulation(asset_config)
        logger.info(f"🎮 Simulation initialized with cycle state: {simulation.current_cycle.status}")
        
        # Main backtest loop
        logger.info("🔄 Starting backtest loop...")
        bar_counter = 0
        
        for bar in data_feeder.get_bars():
            bar_counter += 1
            
            # Log progress every 100 bars
            if bar_counter % 100 == 0:
                logger.info(f"📊 Processed {bar_counter}/{bar_count} bars "
                           f"({bar_counter/bar_count*100:.1f}%)")
            
            # Create market input from bar
            market_input = MarketTickInput(
                timestamp=bar['timestamp'],
                current_ask_price=bar['close'],  # Simplified: use close as both ask/bid
                current_bid_price=bar['close'],
                symbol=symbol
            )
            
            # Log current bar (every 500 bars to avoid spam)
            if bar_counter % 500 == 0:
                logger.info(f"📈 Bar {bar_counter}: {bar['timestamp']} "
                           f"OHLC: ${bar['open']:.2f}/${bar['high']:.2f}/"
                           f"${bar['low']:.2f}/${bar['close']:.2f}")
            
            # Call strategy functions based on current cycle status
            actions_executed = []
            
            # Check base order action
            if simulation.current_cycle.status in ['watching', 'cooldown']:
                try:
                    base_action = decide_base_order_action(
                        market_input, 
                        asset_config, 
                        simulation.current_cycle, 
                        simulation.current_alpaca_position
                    )
                    if base_action and base_action.has_action():
                        logger.info(f"🟢 BASE ORDER ACTION at ${bar['close']}")
                        simulation.process_strategy_action(base_action, bar['timestamp'])
                        actions_executed.append('base_order')
                except Exception as e:
                    logger.error(f"Error in base order logic: {e}")
            
            # Check safety order action
            if simulation.current_cycle.status == 'watching':
                try:
                    safety_action = decide_safety_order_action(
                        market_input,
                        asset_config,
                        simulation.current_cycle
                    )
                    if safety_action and safety_action.has_action():
                        logger.info(f"🛡️ SAFETY ORDER ACTION at ${bar['close']}")
                        simulation.process_strategy_action(safety_action, bar['timestamp'])
                        actions_executed.append('safety_order')
                except Exception as e:
                    logger.error(f"Error in safety order logic: {e}")
            
            # Check take-profit action
            if simulation.current_cycle.status in ['watching', 'trailing']:
                try:
                    tp_action = decide_take_profit_action(
                        market_input,
                        asset_config,
                        simulation.current_cycle,
                        simulation.current_alpaca_position
                    )
                    if tp_action and tp_action.has_action():
                        logger.info(f"💰 TAKE-PROFIT ACTION at ${bar['close']}")
                        simulation.process_strategy_action(tp_action, bar['timestamp'])
                        actions_executed.append('take_profit')
                except Exception as e:
                    logger.error(f"Error in take-profit logic: {e}")
            
            # Log cycle state periodically or when actions are taken
            if actions_executed or bar_counter % 1000 == 0:
                simulation.log_cycle_state()
        
        # Final summary
        logger.info("✅ Backtest completed!")
        logger.info(f"📊 Total bars processed: {bar_counter}")
        logger.info(f"💾 Final cycle state: Status={simulation.current_cycle.status}, "
                   f"Qty={simulation.current_cycle.quantity}, "
                   f"SafetyOrders={simulation.current_cycle.safety_orders}")
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Backtesting failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == '__main__':
    exit(main()) 