#!/usr/bin/env python3
"""
Integration Test Script for DCA Trading Bot

This script tests end-to-end scenarios against the actual database and Alpaca paper trading account.
It includes setup, execution, assertions, and teardown for each phase of development.

Run this script to verify that Phase 1 functionality is working correctly.
"""

import sys
import os
from decimal import Decimal
from datetime import datetime
import logging
import time

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

# Import our utility functions and models
from utils.db_utils import get_db_connection, execute_query, check_connection
from models.asset_config import DcaAsset, get_asset_config, get_all_enabled_assets, update_asset_config
from models.cycle_data import DcaCycle, get_latest_cycle, create_cycle, update_cycle
from utils.alpaca_client_rest import (
    get_trading_client, 
    get_account_info, 
    get_latest_crypto_price,
    place_limit_buy_order,
    get_open_orders,
    cancel_order
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_phase1_asset_and_cycle_crud():
    """
    Phase 1 Integration Test: Basic Create, Read, Update, Delete (CRUD-like) operations 
    for dca_assets and dca_cycles using the functions we built.
    
    Scenario: Test complete CRUD functionality for both asset configuration and cycle data.
    """
    print("\n" + "="*80)
    print("PHASE 1 INTEGRATION TEST: Asset and Cycle CRUD Operations")
    print("="*80)
    
    # Test asset symbol to use
    test_asset_symbol = 'TEST/USD'
    test_asset_id = None
    test_cycle_id = None
    
    try:
        # Setup: Connect to database
        print("\n1. Testing database connection...")
        if not check_connection():
            print("❌ FAILED: Database connection test failed")
            return False
        print("✅ SUCCESS: Database connection established")
        
        # Setup: Insert a test dca_assets record
        print("\n2. Creating test asset configuration...")
        insert_asset_query = """
        INSERT INTO dca_assets (
            asset_symbol, is_enabled, base_order_amount, safety_order_amount,
            max_safety_orders, safety_order_deviation, take_profit_percent,
            cooldown_period, buy_order_price_deviation_percent
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        asset_params = (
            test_asset_symbol,
            True,  # is_enabled
            Decimal('100.00'),  # base_order_amount
            Decimal('50.00'),   # safety_order_amount
            5,                  # max_safety_orders
            Decimal('2.0'),     # safety_order_deviation
            Decimal('1.5'),     # take_profit_percent
            300,                # cooldown_period (5 minutes)
            Decimal('3.0')      # buy_order_price_deviation_percent
        )
        
        test_asset_id = execute_query(insert_asset_query, asset_params, commit=True)
        if not test_asset_id:
            print("❌ FAILED: Could not create test asset")
            return False
        print(f"✅ SUCCESS: Created test asset with ID {test_asset_id}")
        
        # Action 1: Call get_asset_config() for the test asset and assert the returned data is correct
        print("\n3. Testing get_asset_config()...")
        retrieved_asset = get_asset_config(test_asset_symbol)
        
        if not retrieved_asset:
            print("❌ FAILED: get_asset_config() returned None")
            return False
        
        # Verify the retrieved asset data
        assert retrieved_asset.id == test_asset_id
        assert retrieved_asset.asset_symbol == test_asset_symbol
        assert retrieved_asset.is_enabled == True
        assert retrieved_asset.base_order_amount == Decimal('100.00')
        assert retrieved_asset.safety_order_amount == Decimal('50.00')
        assert retrieved_asset.max_safety_orders == 5
        assert retrieved_asset.safety_order_deviation == Decimal('2.0')
        assert retrieved_asset.take_profit_percent == Decimal('1.5')
        assert retrieved_asset.cooldown_period == 300
        assert retrieved_asset.buy_order_price_deviation_percent == Decimal('3.0')
        assert retrieved_asset.last_sell_price is None  # Should be NULL initially
        
        print("✅ SUCCESS: get_asset_config() returned correct data")
        
        # Action 2: Call create_cycle() for this test asset
        print("\n4. Testing create_cycle()...")
        new_cycle = create_cycle(
            asset_id=test_asset_id,
            status='watching',
            quantity=Decimal('0.1'),
            average_purchase_price=Decimal('50000.00'),
            safety_orders=1,
            latest_order_id='test_order_123',
            last_order_fill_price=Decimal('49500.00')
        )
        
        if not new_cycle:
            print("❌ FAILED: create_cycle() returned None")
            return False
        
        test_cycle_id = new_cycle.id
        
        # Verify the created cycle data
        assert new_cycle.asset_id == test_asset_id
        assert new_cycle.status == 'watching'
        assert new_cycle.quantity == Decimal('0.1')
        assert new_cycle.average_purchase_price == Decimal('50000.00')
        assert new_cycle.safety_orders == 1
        assert new_cycle.latest_order_id == 'test_order_123'
        assert new_cycle.last_order_fill_price == Decimal('49500.00')
        assert new_cycle.completed_at is None
        assert new_cycle.created_at is not None
        assert new_cycle.updated_at is not None
        
        print(f"✅ SUCCESS: create_cycle() created cycle with ID {test_cycle_id}")
        
        # Action 3: Call get_latest_cycle() and assert it matches the created cycle
        print("\n5. Testing get_latest_cycle()...")
        latest_cycle = get_latest_cycle(test_asset_id)
        
        if not latest_cycle:
            print("❌ FAILED: get_latest_cycle() returned None")
            return False
        
        # Verify it's the same cycle we just created
        assert latest_cycle.id == test_cycle_id
        assert latest_cycle.asset_id == test_asset_id
        assert latest_cycle.status == 'watching'
        assert latest_cycle.quantity == Decimal('0.1')
        assert latest_cycle.average_purchase_price == Decimal('50000.00')
        
        print("✅ SUCCESS: get_latest_cycle() returned the correct cycle")
        
        # Action 4: Call update_cycle() to change the status, then fetch again and assert the update
        print("\n6. Testing update_cycle()...")
        cycle_updates = {
            'status': 'buying',
            'latest_order_id': 'updated_order_456',
            'quantity': Decimal('0.15')
        }
        
        update_success = update_cycle(test_cycle_id, cycle_updates)
        if not update_success:
            print("❌ FAILED: update_cycle() returned False")
            return False
        
        # Fetch the updated cycle and verify changes
        updated_cycle = get_latest_cycle(test_asset_id)
        if not updated_cycle:
            print("❌ FAILED: Could not fetch updated cycle")
            return False
        
        assert updated_cycle.status == 'buying'
        assert updated_cycle.latest_order_id == 'updated_order_456'
        assert updated_cycle.quantity == Decimal('0.15')
        # These should remain unchanged
        assert updated_cycle.average_purchase_price == Decimal('50000.00')
        assert updated_cycle.safety_orders == 1
        
        print("✅ SUCCESS: update_cycle() successfully updated the cycle")
        
        # Additional test: Update asset configuration
        print("\n7. Testing update_asset_config()...")
        asset_updates = {
            'last_sell_price': Decimal('51000.00'),
            'is_enabled': False
        }
        
        asset_update_success = update_asset_config(test_asset_id, asset_updates)
        if not asset_update_success:
            print("❌ FAILED: update_asset_config() returned False")
            return False
        
        # Verify the asset update
        updated_asset = get_asset_config(test_asset_symbol)
        if not updated_asset:
            print("❌ FAILED: Could not fetch updated asset")
            return False
        
        assert updated_asset.last_sell_price == Decimal('51000.00')
        assert updated_asset.is_enabled == False
        
        print("✅ SUCCESS: update_asset_config() successfully updated the asset")
        
        print("\n8. All Phase 1 tests completed successfully! 🎉")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Unexpected error during test: {e}")
        logger.exception("Integration test failed with exception")
        return False
        
    finally:
        # Teardown: Delete the test records
        print("\n9. Cleaning up test data...")
        try:
            if test_cycle_id:
                delete_cycle_query = "DELETE FROM dca_cycles WHERE id = %s"
                execute_query(delete_cycle_query, (test_cycle_id,), commit=True)
                print(f"✅ Deleted test cycle {test_cycle_id}")
            
            if test_asset_id:
                delete_asset_query = "DELETE FROM dca_assets WHERE id = %s"
                execute_query(delete_asset_query, (test_asset_id,), commit=True)
                print(f"✅ Deleted test asset {test_asset_id}")
                
        except Exception as e:
            print(f"⚠️  WARNING: Could not clean up test data: {e}")
            logger.error(f"Cleanup failed: {e}")


def test_phase2_alpaca_rest_api_order_cycle():
    """
    Integration Test for Phase 2: Alpaca REST API Order Cycle
    
    Scenario: Test the full cycle of placing, viewing, and canceling an order via REST API 
    on the Alpaca paper account.
    
    Actions:
    1. Initialize TradingClient and get account info
    2. Get latest crypto price for BTC/USD
    3. Place a limit BUY order with very small quantity at low price
    4. Verify order appears in open orders
    5. Cancel the order
    6. Verify order is no longer in open orders or shows as canceled
    """
    print("\n" + "="*60)
    print("PHASE 2 INTEGRATION TEST: Alpaca REST API Order Cycle")
    print("="*60)
    
    try:
        # Setup: Initialize TradingClient
        print("\n1. Initializing Alpaca TradingClient...")
        
        # Check if .env file has required Alpaca credentials
        required_env_vars = ['APCA_API_KEY_ID', 'APCA_API_SECRET_KEY']
        missing_vars = [var for var in required_env_vars if not os.getenv(var)]
        
        if missing_vars:
            print(f"❌ FAILED: Missing required environment variables: {missing_vars}")
            print("Please ensure your .env file contains Alpaca API credentials.")
            return False
        
        client = get_trading_client()
        if not client:
            print("❌ FAILED: Could not initialize TradingClient")
            return False
        
        print("✅ SUCCESS: TradingClient initialized")
        
        # Action 1: Call get_account_info() and print some details
        print("\n2. Fetching account information...")
        account = get_account_info(client)
        
        if not account:
            print("❌ FAILED: get_account_info() returned None")
            return False
        
        print(f"✅ SUCCESS: Account retrieved")
        print(f"   Account Number: {account.account_number}")
        print(f"   Buying Power: ${account.buying_power}")
        print(f"   Cash: ${account.cash}")
        print(f"   Account Status: {account.status}")
        
        # Action 2: Call get_latest_crypto_price() for 'BTC/USD'
        print("\n3. Fetching latest BTC/USD price...")
        btc_price = get_latest_crypto_price(client, 'BTC/USD')
        
        if not btc_price:
            print("❌ FAILED: get_latest_crypto_price() returned None")
            return False
        
        print(f"✅ SUCCESS: Latest BTC/USD price: ${btc_price:,.2f}")
        
        # Action 3: Place a limit BUY order with very small quantity at low price
        print("\n4. Placing test limit BUY order...")
        
        # Use small quantity but ensure order value meets minimum ($10)
        test_qty = 0.01  # 0.01 BTC at $1000 = $10 (meets minimum)
        test_price = 1000.0  # Well below current market price
        
        print(f"   Placing order: {test_qty} BTC/USD @ ${test_price}")
        
        order = place_limit_buy_order(client, 'BTC/USD', test_qty, test_price, 'gtc')
        
        if not order:
            print("❌ FAILED: place_limit_buy_order() returned None")
            return False
        
        test_order_id = order.id
        print(f"✅ SUCCESS: Order placed successfully")
        print(f"   Order ID: {test_order_id}")
        print(f"   Symbol: {order.symbol}")
        print(f"   Quantity: {order.qty}")
        print(f"   Limit Price: ${order.limit_price}")
        print(f"   Status: {order.status}")
        print(f"   Side: {order.side}")
        
        # Action 4: Get open orders and find our test order
        print("\n5. Verifying order appears in open orders...")
        open_orders = get_open_orders(client)
        
        if not isinstance(open_orders, list):
            print("❌ FAILED: get_open_orders() did not return a list")
            return False
        
        print(f"✅ SUCCESS: Retrieved {len(open_orders)} open orders")
        
        # Find our test order in the list
        test_order_found = None
        for open_order in open_orders:
            if open_order.id == test_order_id:
                test_order_found = open_order
                break
        
        if not test_order_found:
            print(f"❌ FAILED: Test order {test_order_id} not found in open orders")
            print("   Available order IDs:", [o.id for o in open_orders])
            return False
        
        print(f"✅ SUCCESS: Test order found in open orders")
        print(f"   Order Status: {test_order_found.status}")
        
        # Verify the order status is acceptable (new, accepted, pending_new)
        acceptable_statuses = ['new', 'accepted', 'pending_new']
        if test_order_found.status not in acceptable_statuses:
            print(f"❌ FAILED: Order status '{test_order_found.status}' not in expected statuses: {acceptable_statuses}")
            return False
        
        print(f"✅ SUCCESS: Order status '{test_order_found.status}' is acceptable")
        
        # Action 5: Cancel the order
        print("\n6. Canceling the test order...")
        cancel_success = cancel_order(client, test_order_id)
        
        if not cancel_success:
            print("❌ FAILED: cancel_order() returned False")
            return False
        
        print(f"✅ SUCCESS: Order cancellation requested")
        
        # Action 6: Verify order is no longer in open orders or shows as canceled
        print("\n7. Verifying order cancellation...")
        
        # Wait a moment for the cancellation to process
        time.sleep(2)
        
        updated_open_orders = get_open_orders(client)
        
        # Check if our order is still in open orders
        canceled_order_found = None
        for open_order in updated_open_orders:
            if open_order.id == test_order_id:
                canceled_order_found = open_order
                break
        
        if canceled_order_found:
            # Order is still there, check if it's canceled
            if canceled_order_found.status != 'canceled':
                print(f"❌ FAILED: Order still exists but status is '{canceled_order_found.status}', not 'canceled'")
                return False
            else:
                print(f"✅ SUCCESS: Order found with 'canceled' status")
        else:
            # Order is no longer in open orders (completely removed)
            print(f"✅ SUCCESS: Order no longer appears in open orders (fully processed)")
        
        print("\n8. All Phase 2 tests completed successfully! 🎉")
        return True
        
    except Exception as e:
        print(f"❌ FAILED: Unexpected error during Phase 2 test: {e}")
        logger.exception("Phase 2 integration test failed with exception")
        return False


def test_phase3_websocket_connection_and_data_receipt():
    """
    Integration Test for Phase 3: WebSocket Connection and Data Receipt
    
    Scenario: Verify that main_app.py connects to Alpaca WebSockets and receives data.
    
    NOTE: This is primarily a manual test that provides instructions for verification.
    Automated WebSocket testing is complex and out of scope for this phase.
    """
    print("\n" + "="*70)
    print("PHASE 3 INTEGRATION TEST: WebSocket Connection and Data Receipt")
    print("="*70)
    
    print("\n📋 MANUAL TEST INSTRUCTIONS:")
    print("This test requires manual observation of the WebSocket application.")
    print("Please follow these steps to verify Phase 3 functionality:\n")
    
    print("1. ⚠️  PREPARATION:")
    print("   • Ensure your .env file has valid Alpaca API credentials")
    print("   • Make sure you're in your virtual environment (source venv/bin/activate)")
    print("   • Have the Alpaca Paper Trading dashboard open in a web browser\n")
    
    print("2. 🚀 START THE WEBSOCKET APPLICATION:")
    print("   Run the following command in a separate terminal:")
    print("   $ python src/main_app.py\n")
    
    print("3. 👀 OBSERVE CONSOLE OUTPUT:")
    print("   You should see log messages indicating:")
    print("   ✅ 'DCA Trading Bot - Main WebSocket Application Starting'")
    print("   ✅ 'Initializing CryptoDataStream (paper=True)'")
    print("   ✅ 'Subscribed to BTC/USD quotes and trades'")
    print("   ✅ 'Initializing TradingStream (paper=True)'")
    print("   ✅ 'Subscribed to trade updates'")
    print("   ✅ 'Starting WebSocket streams...'")
    print("   ✅ 'Starting CryptoDataStream...'")
    print("   ✅ 'Starting TradingStream...'\n")
    
    print("4. 💰 OBSERVE MARKET DATA:")
    print("   Within 1-2 minutes, you should see regular messages like:")
    print("   ✅ 'Quote: BTC/USD - Bid: $109000.00 @ 1.5, Ask: $109001.00 @ 2.0'")
    print("   ✅ 'Trade: BTC/USD - Price: $109000.50, Size: 0.25, Time: ...'")
    print("   (Prices will vary based on current market conditions)\n")
    
    print("5. 🧪 TEST TRADE UPDATES:")
    print("   a. Go to your Alpaca Paper Trading dashboard")
    print("   b. Place a small crypto order (e.g., 0.001 BTC market order)")
    print("   c. Observe the main_app.py console output for trade update messages:")
    print("      ✅ 'Trade Update: fill - Order ID: xyz, Symbol: BTC/USD, Side: buy, Status: filled'")
    print("      ✅ 'Execution: Price $109000.25, Qty: 0.001' (if fill occurred)\n")
    
    print("6. 🛑 TEST GRACEFUL SHUTDOWN:")
    print("   a. Press Ctrl+C in the terminal running main_app.py")
    print("   b. Observe graceful shutdown messages:")
    print("      ✅ 'Received signal 2, initiating graceful shutdown...'")
    print("      ✅ 'CryptoDataStream stopped'")
    print("      ✅ 'TradingStream stopped'")
    print("      ✅ 'CryptoDataStream closed'")
    print("      ✅ 'TradingStream closed'")
    print("      ✅ 'DCA Trading Bot - Main WebSocket Application Stopped'\n")
    
    print("7. 📝 EXPECTED OUTCOMES:")
    print("   ✅ Application starts without errors")
    print("   ✅ Both WebSocket streams connect successfully")
    print("   ✅ Regular BTC/USD market data is received and logged")
    print("   ✅ Manual trades placed via dashboard trigger trade update messages")
    print("   ✅ Application shuts down gracefully when interrupted")
    print("   ✅ Log files are created in logs/main_app.log\n")
    
    print("8. 🚨 TROUBLESHOOTING:")
    print("   If you encounter issues:")
    print("   • Check logs/main_app.log for detailed error messages")
    print("   • Verify .env file has correct Alpaca credentials")
    print("   • Ensure internet connectivity for WebSocket connections")
    print("   • Check that APCA_API_BASE_URL points to paper trading URL\n")
    
    print("📊 AUTOMATED VERIFICATION:")
    print("   Checking basic prerequisites...")
    
    # Check environment variables
    print("\n🔍 Checking environment variables...")
    required_vars = ['APCA_API_KEY_ID', 'APCA_API_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"   ❌ Missing environment variables: {missing_vars}")
        print("   Please update your .env file before running the manual test.")
        return False
    else:
        print("   ✅ Required environment variables are present")
    
    # Check if main_app.py exists
    print("\n📁 Checking main_app.py file...")
    main_app_path = os.path.join('src', 'main_app.py')
    if os.path.exists(main_app_path):
        print("   ✅ src/main_app.py exists")
    else:
        print("   ❌ src/main_app.py not found")
        return False
    
    # Check logs directory
    print("\n📂 Checking logs directory...")
    logs_dir = 'logs'
    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
        print("   ✅ Created logs directory")
    else:
        print("   ✅ Logs directory exists")
    
    print("\n🎉 Prerequisites check completed successfully!")
    print("   You can now proceed with the manual test steps above.")
    print("   This manual test is considered PASSED when all expected outcomes are observed.\n")
    
    return True


def main():
    """Main integration test runner."""
    print("DCA Trading Bot - Integration Test Suite")
    print(f"Started at: {datetime.now()}")
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ ERROR: .env file not found. Please create it with database credentials.")
        print("Refer to README.md for required environment variables.")
        return
    
    # Track test results
    phase1_success = False
    phase2_success = False
    phase3_success = False
    
    # Run Phase 1 tests
    print("\nRunning Phase 1 tests...")
    phase1_success = test_phase1_asset_and_cycle_crud()
    
    # Run Phase 2 tests
    print("\nRunning Phase 2 tests...")
    phase2_success = test_phase2_alpaca_rest_api_order_cycle()
    
    # Run Phase 3 tests (manual verification)
    print("\nRunning Phase 3 tests...")
    phase3_success = test_phase3_websocket_connection_and_data_receipt()
    
    # Final results
    print("\n" + "="*60)
    print("INTEGRATION TEST RESULTS SUMMARY")
    print("="*60)
    
    print(f"Phase 1 (Database CRUD): {'✅ PASSED' if phase1_success else '❌ FAILED'}")
    print(f"Phase 2 (Alpaca REST API): {'✅ PASSED' if phase2_success else '❌ FAILED'}")
    print(f"Phase 3 (WebSocket Streams): {'✅ READY FOR MANUAL TEST' if phase3_success else '❌ PREREQUISITES FAILED'}")
    
    if phase1_success and phase2_success and phase3_success:
        print("\n🎉 ALL AUTOMATED TESTS PASSED!")
        print("Phase 3 requires manual verification - follow the instructions above.")
        print("The DCA Trading Bot Phase 1, 2, & 3 functionality is ready for testing!")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("Please review the errors above and fix any issues.")
        sys.exit(1)


if __name__ == '__main__':
    main() 