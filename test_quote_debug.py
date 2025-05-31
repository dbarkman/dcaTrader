#!/usr/bin/env python3
"""
Debug script to test the new on_crypto_quote function with real database setup
"""

import asyncio
import sys
import os
from decimal import Decimal
import logging

# Load test environment first
from dotenv import load_dotenv
load_dotenv('.env.test')

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/main.log'),
        logging.StreamHandler()
    ]
)

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from main_app import on_crypto_quote
from strategy_logic import decide_take_profit_action
from models.backtest_structs import MarketTickInput, OrderSide, OrderType
from datetime import datetime, timezone

# Import integration test functions
sys.path.insert(0, os.path.dirname(__file__))
from integration_test import setup_test_asset, setup_test_cycle, execute_test_query, comprehensive_test_teardown

# Import test utils
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'tests', 'utils'))
from test_utils import create_mock_crypto_quote_event

# Mock quote object
class MockQuote:
    def __init__(self, symbol, bid_price, ask_price):
        self.symbol = symbol
        self.bid_price = bid_price
        self.ask_price = ask_price
        self.bid_size = 100.0
        self.ask_size = 100.0

async def test_integration_take_profit():
    print("Testing take-profit with real database setup...")
    
    test_asset_id = None
    test_cycle_id = None
    
    try:
        # 1. Set up test asset in database
        print("1. Setting up test asset...")
        test_asset_id = setup_test_asset(
            symbol='BTC/USD',
            enabled=True,
            base_order_amount=Decimal('20.00'),
            safety_order_amount=Decimal('20.00'),
            max_safety_orders=2,
            safety_order_deviation=Decimal('2.0'),
            take_profit_percent=Decimal('1.5'),
            ttp_enabled=False,
            cooldown_period=60
        )
        print(f"   ✅ Created test asset BTC/USD with ID {test_asset_id}")
        
        # 2. Set up test cycle in database (simulating after buy sequence)
        print("2. Setting up test cycle...")
        test_cycle_id = setup_test_cycle(
            asset_id=test_asset_id,
            status='watching',
            quantity=Decimal('0.000725089'),
            average_purchase_price=Decimal('104892.7488870440'),
            safety_orders=2,
            last_order_fill_price=Decimal('100566.632096800000')
        )
        print(f"   ✅ Created test cycle with ID {test_cycle_id}")
        
        # 3. Calculate take-profit prices
        print("3. Calculating take-profit scenario...")
        current_avg_price = Decimal('104892.7488870440')
        take_profit_percent = Decimal('1.5')
        tp_trigger_price = current_avg_price * (Decimal('1') + take_profit_percent / Decimal('100'))
        mock_tp_bid_price = tp_trigger_price + Decimal('100')  # Rise above trigger
        mock_tp_ask_price = mock_tp_bid_price * Decimal('1.001')
        
        print(f"   Current avg price: ${current_avg_price}")
        print(f"   Take profit trigger: ${tp_trigger_price}")
        print(f"   Mock bid price: ${mock_tp_bid_price}")
        
        # 4. Clear recent orders
        print("4. Clearing recent orders...")
        import main_app
        main_app.recent_orders.clear()
        
        # 5. Test pure strategy logic first
        print("5. Testing pure strategy logic...")
        from models.asset_config import get_asset_config
        from models.cycle_data import get_latest_cycle
        
        asset_config = get_asset_config('BTC/USD')
        latest_cycle = get_latest_cycle(test_asset_id)
        
        print(f"   Asset config found: {asset_config is not None}")
        print(f"   Latest cycle found: {latest_cycle is not None}")
        
        if asset_config and latest_cycle:
            market_input = MarketTickInput(
                timestamp=datetime.now(timezone.utc),
                symbol='BTC/USD',
                current_ask_price=mock_tp_ask_price,
                current_bid_price=mock_tp_bid_price
            )
            
            tp_action = decide_take_profit_action(market_input, asset_config, latest_cycle, None)
            print(f"   Take-profit action returned: {tp_action is not None}")
            if tp_action:
                print(f"   Has action: {tp_action.has_action()}")
                print(f"   Order intent: {tp_action.order_intent}")
        
        # 6. Call on_crypto_quote with take-profit conditions
        print("6. Calling on_crypto_quote...")
        mock_quote = create_mock_crypto_quote_event(
            symbol='BTC/USD',
            ask_price=float(mock_tp_ask_price),
            bid_price=float(mock_tp_bid_price)
        )
        
        await on_crypto_quote(mock_quote)
        print("   ✅ on_crypto_quote completed")
        
        # 7. Check for logs
        print("7. Checking logs...")
        try:
            with open('logs/main.log', 'r') as f:
                recent_logs = f.readlines()[-20:]  # Get last 20 lines
                log_content = ''.join(recent_logs)
                print("   Recent log content:")
                for line in recent_logs:
                    print(f"     {line.strip()}")
                    
                if 'take_profit' in log_content.lower() or 'SELL' in log_content:
                    print("   ✅ Take-profit logic detected in logs")
                else:
                    print("   ❌ No take-profit logic detected in logs")
        except FileNotFoundError:
            print("   ⚠️ No log file found")
        except Exception as e:
            print(f"   ⚠️ Error reading logs: {e}")
            
        # 8. Check database state
        print("8. Checking database state...")
        cycle_after = execute_test_query(
            "SELECT * FROM dca_cycles WHERE id = %s",
            (test_cycle_id,),
            fetch_one=True
        )
        print(f"   Cycle status: {cycle_after['status']}")
        print(f"   Latest order ID: {cycle_after.get('latest_order_id', 'None')}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        
    finally:
        # Cleanup
        print("9. Cleaning up...")
        if test_asset_id and test_cycle_id:
            comprehensive_test_teardown("debug_test")
        print("   ✅ Cleanup completed")

if __name__ == "__main__":
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    asyncio.run(test_integration_take_profit()) 