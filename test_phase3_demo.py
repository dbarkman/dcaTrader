#!/usr/bin/env python3
"""
Demo script to test Phase 3 backtesting functionality.

This script demonstrates the backtesting engine without requiring actual historical data.
"""

import sys
import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

# Add src and scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'scripts'))

from run_backtest import HistoricalDataFeeder, BacktestSimulation
from models.asset_config import DcaAsset
from models.backtest_structs import MarketTickInput, StrategyAction, OrderIntent, OrderSide, OrderType
from strategy_logic import decide_base_order_action

def demo_historical_data_feeder():
    """Demo the HistoricalDataFeeder with mock data."""
    print("🧪 Demo: HistoricalDataFeeder")
    print("=" * 50)
    
    # Mock historical data
    mock_bars = [
        {
            'timestamp': datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
            'open_price': 45000.00,
            'high_price': 45500.00,
            'low_price': 44800.00,
            'close_price': 45200.00,
            'volume': 123.45
        },
        {
            'timestamp': datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
            'open_price': 45200.00,
            'high_price': 45600.00,
            'low_price': 45000.00,
            'close_price': 45400.00,
            'volume': 234.56
        },
        {
            'timestamp': datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc),
            'open_price': 45400.00,
            'high_price': 45800.00,
            'low_price': 45300.00,
            'close_price': 45700.00,
            'volume': 345.67
        }
    ]
    
    # Mock the execute_query function
    with patch('run_backtest.execute_query', return_value=mock_bars):
        feeder = HistoricalDataFeeder(
            asset_id=1,
            start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 1, 2, tzinfo=timezone.utc)
        )
        
        print(f"📊 Bar count: {feeder.get_bar_count()}")
        
        for i, bar in enumerate(feeder.get_bars()):
            print(f"📈 Bar {i+1}: {bar['timestamp']} - "
                  f"OHLC: ${bar['open']:.2f}/${bar['high']:.2f}/"
                  f"${bar['low']:.2f}/${bar['close']:.2f}")
    
    print("✅ HistoricalDataFeeder demo completed\n")


def demo_backtest_simulation():
    """Demo the BacktestSimulation with mock strategy actions."""
    print("🎮 Demo: BacktestSimulation")
    print("=" * 50)
    
    # Create mock asset config
    mock_asset = Mock(spec=DcaAsset)
    mock_asset.id = 1
    mock_asset.symbol = 'BTC/USD'
    mock_asset.base_order_amount = Decimal('100.0')
    mock_asset.safety_order_amount = Decimal('50.0')
    mock_asset.max_safety_orders = 3
    mock_asset.take_profit_percent = Decimal('2.0')
    mock_asset.ttp_enabled = True
    
    # Initialize simulation
    simulation = BacktestSimulation(mock_asset)
    print(f"🎯 Initial cycle status: {simulation.current_cycle.status}")
    
    # Create test strategy action
    order_intent = OrderIntent(
        symbol='BTC/USD',
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal('0.002'),
        limit_price=Decimal('45000.0')
    )
    
    action = StrategyAction(order_intent=order_intent)
    timestamp = datetime.now(timezone.utc)
    
    print(f"🔄 Processing strategy action...")
    simulation.process_strategy_action(action, timestamp)
    
    print(f"📊 Order counter after action: {simulation.order_counter}")
    simulation.log_cycle_state()
    
    print("✅ BacktestSimulation demo completed\n")


def demo_strategy_integration():
    """Demo integration with actual strategy logic."""
    print("🧠 Demo: Strategy Logic Integration")
    print("=" * 50)
    
    # Create mock asset config
    mock_asset = Mock()
    mock_asset.is_enabled = True
    mock_asset.base_order_amount = Decimal('100.0')
    mock_asset.safety_order_amount = Decimal('50.0')
    mock_asset.max_safety_orders = 3
    mock_asset.safety_order_deviation = Decimal('2.0')
    mock_asset.take_profit_percent = Decimal('1.5')
    mock_asset.ttp_enabled = False
    
    # Create mock cycle
    mock_cycle = Mock()
    mock_cycle.status = 'watching'
    mock_cycle.quantity = Decimal('0')
    mock_cycle.safety_orders = 0
    mock_cycle.last_order_fill_price = None
    
    # Create market input
    market_input = MarketTickInput(
        timestamp=datetime.now(timezone.utc),
        current_ask_price=Decimal('45000.0'),
        current_bid_price=Decimal('44995.0'),
        symbol='BTC/USD'
    )
    
    print(f"📈 Market input: Ask=${market_input.current_ask_price}, Bid=${market_input.current_bid_price}")
    
    # Test base order decision
    result = decide_base_order_action(market_input, mock_asset, mock_cycle, None)
    
    if result and result.has_action():
        print("🟢 Base order action returned:")
        if result.order_intent:
            print(f"   📋 Order: {result.order_intent.side.value.upper()} "
                  f"{result.order_intent.quantity} {result.order_intent.symbol} "
                  f"@ ${result.order_intent.limit_price}")
        if result.cycle_update_intent:
            print(f"   🔄 Cycle update: Status -> {result.cycle_update_intent.new_status}")
    else:
        print("❌ No base order action (conditions not met)")
    
    print("✅ Strategy integration demo completed\n")


def main():
    """Main demo function."""
    print("🚀 Phase 3 Backtesting Engine Demo")
    print("=" * 80)
    print()
    
    try:
        demo_historical_data_feeder()
        demo_backtest_simulation() 
        demo_strategy_integration()
        
        print("🎉 All demos completed successfully!")
        
    except Exception as e:
        print(f"❌ Demo failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
        
    return 0


if __name__ == '__main__':
    exit(main()) 