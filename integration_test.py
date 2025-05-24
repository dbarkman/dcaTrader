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
import subprocess
import threading
import signal
import re
from queue import Queue, Empty

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
    cancel_order,
    get_positions
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


def _wait_for_trade_update_with_order_id(log_monitor, order_id, timeout):
    """
    Wait for trade update with specific order ID.
    Handles our multi-line log format where Order ID appears after Trade Update header.
    """
    print(f"   🔍 Waiting for trade update for order {order_id}...")
    start_time = time.time()
    
    # Convert order_id to string to handle UUID objects
    order_id_str = str(order_id)
    
    # Buffer to track recent lines for multi-line matching
    recent_lines = []
    
    while time.time() - start_time < timeout:
        try:
            log_type, message = log_monitor.log_queue.get(timeout=1)
            recent_lines.append(message)
            
            # Keep only last 5 lines for efficiency  
            if len(recent_lines) > 5:
                recent_lines.pop(0)
            
            # Check if we have a trade update followed by our order ID
            for i, line in enumerate(recent_lines):
                if "Trade Update:" in line:
                    # Check next few lines for our order ID
                    for j in range(i + 1, min(i + 4, len(recent_lines))):
                        if order_id_str in recent_lines[j]:
                            print(f"   ✅ Found trade update for order {order_id}")
                            return True
                            
        except Empty:
            continue
        except Exception as e:
            print(f"   Error waiting for trade update: {e}")
            continue
    
    print(f"   ❌ Timeout waiting for trade update after {timeout}s")
    return False


def test_phase3_websocket_connection_and_data_receipt():
    """
    Fully Automated Integration Test for Phase 3: WebSocket Connection and Data Receipt
    
    This test automatically:
    1. Starts main_app.py as subprocess
    2. Monitors logs for connection success
    3. Verifies market data reception
    4. Places test orders programmatically 
    5. Verifies trade updates appear
    6. Tests graceful shutdown
    7. Reports comprehensive results
    """
    print("\n" + "="*70)
    print("PHASE 3 AUTOMATED INTEGRATION TEST: WebSocket Connection and Data Receipt")
    print("="*70)
    
    # Test configuration
    test_timeout = 120  # Total test timeout (2 minutes)
    connection_timeout = 30  # Time to wait for connections
    market_data_timeout = 30  # Time to wait for market data
    trade_update_timeout = 30  # Time to wait for trade updates
    shutdown_timeout = 10   # Time to wait for graceful shutdown
    
    # Results tracking
    results = {
        'process_started': False,
        'crypto_stream_connected': False,
        'trading_stream_connected': False,
        'market_data_received': False,
        'test_order_placed': False,
        'trade_update_received': False,
        'graceful_shutdown': False,
        'process_terminated': False,
        'error_messages': []
    }
    
    main_process = None
    log_monitor = None
    
    class LogMonitor:
        """Monitor subprocess output for specific patterns"""
        
        def __init__(self, process):
            self.process = process
            self.log_queue = Queue()
            self.patterns_found = {}
            self.all_logs = []
            self.running = True
            
            # Start monitoring threads
            self.stdout_thread = threading.Thread(target=self._monitor_stdout, daemon=True)
            self.stderr_thread = threading.Thread(target=self._monitor_stderr, daemon=True)
            self.stdout_thread.start()
            self.stderr_thread.start()
        
        def _monitor_stdout(self):
            """Monitor stdout in separate thread"""
            while self.running and self.process.poll() is None:
                try:
                    line = self.process.stdout.readline()
                    if line:
                        line_str = line.decode('utf-8').strip()
                        self.log_queue.put(('stdout', line_str))
                        self.all_logs.append(line_str)
                except Exception as e:
                    self.log_queue.put(('error', f"Error reading stdout: {e}"))
        
        def _monitor_stderr(self):
            """Monitor stderr in separate thread"""
            while self.running and self.process.poll() is None:
                try:
                    line = self.process.stderr.readline()
                    if line:
                        line_str = line.decode('utf-8').strip()
                        self.log_queue.put(('stderr', line_str))
                        self.all_logs.append(line_str)
                        
                        # Only treat actual ERROR/WARNING messages as problems
                        # Normal Python logging goes to stderr but isn't an "error"
                        if line_str.strip():
                            if " - ERROR - " in line_str:
                                self.error_logs.append(f"ERROR: {line_str}")
                                print(f"   🚨 ERROR: {line_str}")
                            elif " - WARNING - " in line_str:
                                self.warning_logs.append(f"WARNING: {line_str}")
                                print(f"   ⚠️ WARNING: {line_str}")
                            # Don't print normal INFO/DEBUG log messages
                                
                except Exception as e:
                    self.log_queue.put(('error', f"Error reading stderr: {e}"))
        
        def wait_for_pattern(self, pattern, timeout=30, description="pattern"):
            """Wait for a specific regex pattern in logs"""
            print(f"   🔍 Waiting for {description}...")
            start_time = time.time()
            
            while time.time() - start_time < timeout:
                try:
                    log_type, message = self.log_queue.get(timeout=1)
                    if re.search(pattern, message, re.IGNORECASE):
                        print(f"   ✅ Found {description}: {message}")
                        self.patterns_found[description] = message
                        return True
                except Empty:
                    continue
                except Exception as e:
                    print(f"   ❌ Error waiting for {description}: {e}")
                    return False
            
            print(f"   ❌ Timeout waiting for {description} after {timeout}s")
            return False
        
        def wait_for_multiple_patterns(self, patterns, timeout=30):
            """Wait for multiple patterns within timeout"""
            start_time = time.time()
            found_patterns = set()
            
            while time.time() - start_time < timeout and len(found_patterns) < len(patterns):
                try:
                    log_type, message = self.log_queue.get(timeout=1)
                    for pattern_name, pattern_regex in patterns.items():
                        if pattern_name not in found_patterns and re.search(pattern_regex, message, re.IGNORECASE):
                            print(f"   ✅ Found {pattern_name}: {message}")
                            found_patterns.add(pattern_name)
                            self.patterns_found[pattern_name] = message
                except Empty:
                    continue
            
            return len(found_patterns) == len(patterns)
        
        def get_recent_logs(self, lines=10):
            """Get recent log lines"""
            return self.all_logs[-lines:] if self.all_logs else []
        
        def stop(self):
            """Stop monitoring"""
            self.running = False
    
    try:
        print("\n1. 🚀 Starting main_app.py subprocess...")
        
        # Set up environment with TESTING_MODE for aggressive pricing
        test_env = os.environ.copy()
        test_env['TESTING_MODE'] = 'true'  # Enable aggressive pricing (5% above ask)
        
        # Start main_app.py as subprocess
        main_process = subprocess.Popen(
            ['python', 'src/main_app.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            env=test_env  # Use modified environment with TESTING_MODE
        )
        
        results['process_started'] = True
        print(f"   ✅ Process started with PID: {main_process.pid}")
        
        # Start log monitoring
        log_monitor = LogMonitor(main_process)
        
        print("\n2. 🔌 Waiting for WebSocket connections...")
        
        # Wait for both streams to connect
        connection_patterns = {
            'crypto_connected': r'connected to wss://stream\.data\.alpaca\.markets',
            'trading_connected': r'connected to.*wss://paper-api\.alpaca\.markets',
            'subscriptions': r'subscribed to trades.*quotes'
        }
        
        if log_monitor.wait_for_multiple_patterns(connection_patterns, connection_timeout):
            results['crypto_stream_connected'] = True
            results['trading_stream_connected'] = True
            print("   ✅ Both WebSocket streams connected successfully!")
        else:
            results['error_messages'].append("Failed to establish WebSocket connections")
            print("   ❌ WebSocket connections failed")
            
        print("\n3. 📊 Waiting for market data...")
        
        # Wait for market data (quotes from any crypto pair)
        if log_monitor.wait_for_pattern(r'Quote:.*USD.*Bid:.*Ask:', market_data_timeout, "market data"):
            results['market_data_received'] = True
            print("   ✅ Market data is flowing!")
        else:
            results['error_messages'].append("No market data received")
            print("   ❌ No market data received")
        
        print("\n4. 💰 Placing test order programmatically...")
        
        # Place a test order using our REST API
        try:
            client = get_trading_client()
            if not client:
                raise Exception("Could not initialize trading client")
            
            # Place $10 limit order well below market to meet Alpaca's minimum
            test_qty = 0.0002  # Small quantity (~$10-20 at current BTC prices)
            test_price = 50000.0  # Well below current market price (~$109k)
            
            order = place_limit_buy_order(client, 'BTC/USD', test_qty, test_price, 'gtc')
            if order:
                test_order_id = order.id
                results['test_order_placed'] = True
                print(f"   ✅ Test order placed: {test_order_id}")
                print(f"   💵 Order value: {test_qty} BTC @ ${test_price} = ${test_qty * test_price}")
                
                print("\n5. 📨 Waiting for trade update...")
                
                # Wait for trade update matching our order ID with improved detection
                if _wait_for_trade_update_with_order_id(log_monitor, test_order_id, trade_update_timeout):
                    results['trade_update_received'] = True
                    print("   ✅ Trade update received!")
                else:
                    results['error_messages'].append("Trade update not received")
                    print("   ❌ Trade update not received")
                
                # Clean up: cancel the test order
                try:
                    cancel_order(client, test_order_id)
                    print(f"   🧹 Test order {test_order_id} cancelled")
                except Exception as e:
                    print(f"   ⚠️ Could not cancel test order: {e}")
            else:
                results['error_messages'].append("Failed to place test order")
                print("   ❌ Failed to place test order")
                
        except Exception as e:
            results['error_messages'].append(f"Order placement error: {e}")
            print(f"   ❌ Order placement failed: {e}")
        
        print("\n6. 🛑 Testing graceful shutdown...")
        
        # Send SIGINT to test graceful shutdown
        try:
            main_process.send_signal(signal.SIGINT)
            print("   📡 Sent SIGINT signal")
            
            # Wait for graceful shutdown messages
            shutdown_patterns = {
                'shutdown_signal': r'Received signal.*graceful shutdown',
                'streams_stopped': r'All WebSocket tasks have been stopped'
            }
            
            if log_monitor.wait_for_multiple_patterns(shutdown_patterns, shutdown_timeout):
                results['graceful_shutdown'] = True
                print("   ✅ Graceful shutdown completed!")
            else:
                results['error_messages'].append("Graceful shutdown failed")
                print("   ❌ Graceful shutdown failed")
            
            # Wait for process to terminate
            try:
                main_process.wait(timeout=5)
                results['process_terminated'] = True
                print("   ✅ Process terminated successfully")
            except subprocess.TimeoutExpired:
                print("   ⚠️ Process did not terminate gracefully, forcing...")
                main_process.kill()
                main_process.wait()
                
        except Exception as e:
            results['error_messages'].append(f"Shutdown test error: {e}")
            print(f"   ❌ Shutdown test failed: {e}")
        
        print("\n7. 📋 Test Results Summary:")
        print("="*50)
        
        # Calculate overall success
        critical_tests = [
            'process_started',
            'crypto_stream_connected', 
            'trading_stream_connected',
            'market_data_received',
            'test_order_placed',
            'trade_update_received'
        ]
        
        optional_tests = [
            'graceful_shutdown',
            'process_terminated'
        ]
        
        critical_passed = all(results[test] for test in critical_tests)
        optional_passed = sum(results[test] for test in optional_tests)
        
        print(f"✅ Critical Tests: {sum(results[test] for test in critical_tests)}/{len(critical_tests)}")
        for test in critical_tests:
            status = "✅ PASS" if results[test] else "❌ FAIL"
            print(f"   {test}: {status}")
        
        print(f"\n🔧 Optional Tests: {optional_passed}/{len(optional_tests)}")
        for test in optional_tests:
            status = "✅ PASS" if results[test] else "❌ FAIL"
            print(f"   {test}: {status}")
        
        if results['error_messages']:
            print(f"\n❌ Errors encountered:")
            for error in results['error_messages']:
                print(f"   • {error}")
        
        print(f"\n📊 Recent logs (last 10 lines):")
        if log_monitor:
            for log_line in log_monitor.get_recent_logs():
                print(f"   {log_line}")
        
        # Determine overall result
        if critical_passed:
            if optional_passed >= 1:
                print(f"\n🎉 PHASE 3 TEST: ✅ PASSED")
                print("   WebSocket application and trading functionality working correctly!")
            else:
                print(f"\n⚠️ PHASE 3 TEST: 🟡 PARTIAL PASS")
                print("   Core functionality works, but shutdown issues detected")
            return True
        else:
            print(f"\n❌ PHASE 3 TEST: ❌ FAILED") 
            print("   Critical functionality is not working - trading bot cannot operate")
            return False
            
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR in Phase 3 test: {e}")
        logger.exception("Phase 3 test failed with exception")
        return False
        
    finally:
        # Cleanup
        print(f"\n🧹 Cleaning up...")
        
        if log_monitor:
            log_monitor.stop()
        
        if main_process and main_process.poll() is None:
            try:
                print("   Terminating main_app.py process...")
                main_process.terminate()
                main_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("   Force killing process...")
                main_process.kill()
                main_process.wait()
            except Exception as e:
                print(f"   Error during cleanup: {e}")
        
        print("   ✅ Cleanup completed")


def test_phase4_marketdata_places_base_order():
    """
    Fully Automated Integration Test for Phase 4: MarketData Places Base Order
    
    This test automatically:
    1. Sets up ALL 8 crypto pairs for trading (increases chance of quote triggers)
    2. Ensures no existing Alpaca positions for test assets
    3. Starts main_app.py subprocess  
    4. Monitors logs for base order placement on ANY of the 8 pairs
    5. Monitors for ERROR/WARNING messages
    6. Verifies order appears in Alpaca
    7. Cleans up ALL test data and cancels ALL orders
    """
    print("\n" + "="*70)
    print("PHASE 4 AUTOMATED INTEGRATION TEST: MarketData Places Base Order")
    print("="*70)
    
    # Test configuration
    test_timeout = 120  # Total test timeout (2 minutes)
    base_order_timeout = 60  # Time to wait for base order placement
    
    # ALL 8 crypto pairs from main_app.py for maximum quote coverage
    test_symbols = [
        'BTC/USD',   # Bitcoin
        'ETH/USD',   # Ethereum
        'SOL/USD',   # Solana
        'DOGE/USD',  # Dogecoin
        'AVAX/USD',  # Avalanche
        'LINK/USD',  # Chainlink
        'UNI/USD',   # Uniswap
        'XRP/USD'    # Ripple
    ]
    
    base_order_amount = Decimal('50.00')  # $50 base order for each pair
    
    # Results tracking
    results = {
        'test_assets_created': 0,
        'test_cycles_created': 0,
        'no_existing_positions': 0,
        'process_started': False,
        'streams_connected': False,
        'base_order_placed': False,
        'order_found_in_alpaca': False,
        'cleanup_completed': False,
        'error_messages': [],
        'warning_messages': [],
        'placed_orders': []
    }
    
    main_process = None
    log_monitor = None
    test_asset_ids = []
    test_cycle_ids = []
    placed_order_ids = []
    
    try:
        print(f"\n1. 🛠️ Setting up {len(test_symbols)} test asset configurations...")
        
        # Clean up any existing test data for all symbols
        try:
            print("   🧹 Cleaning up any existing test data...")
            
            for symbol in test_symbols:
                existing_asset = get_asset_config(symbol)
                if existing_asset:
                    # Delete any cycles for this asset
                    delete_cycles_query = "DELETE FROM dca_cycles WHERE asset_id = %s"
                    execute_query(delete_cycles_query, (existing_asset.id,), commit=True)
                    
                    # Delete the asset
                    delete_asset_query = "DELETE FROM dca_assets WHERE id = %s"
                    execute_query(delete_asset_query, (existing_asset.id,), commit=True)
                    
                    print(f"   ✅ Cleaned up existing test data for {symbol}")
            
            print("   ✅ All existing test data cleaned up")
                
        except Exception as e:
            print(f"   ⚠️ Warning during cleanup: {e}")
            # Continue anyway
        
        # Insert all test assets into database
        insert_asset_query = """
        INSERT INTO dca_assets (
            asset_symbol, is_enabled, base_order_amount, safety_order_amount,
            max_safety_orders, safety_order_deviation, take_profit_percent,
            cooldown_period, buy_order_price_deviation_percent
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        for symbol in test_symbols:
            asset_params = (
                symbol,
                True,  # is_enabled
                base_order_amount,  # base_order_amount ($50)
                Decimal('25.00'),   # safety_order_amount
                3,                  # max_safety_orders
                Decimal('2.0'),     # safety_order_deviation (2%)
                Decimal('1.5'),     # take_profit_percent (1.5%)
                300,                # cooldown_period (5 minutes)
                Decimal('3.0')      # buy_order_price_deviation_percent
            )
            
            asset_id = execute_query(insert_asset_query, asset_params, commit=True)
            if not asset_id:
                results['error_messages'].append(f"Failed to create test asset for {symbol}")
                print(f"   ❌ Failed to create test asset for {symbol}")
                continue
            
            test_asset_ids.append((asset_id, symbol))
            results['test_assets_created'] += 1
            print(f"   ✅ Created asset {symbol} with ID: {asset_id}")
        
        print(f"   ✅ Created {results['test_assets_created']}/{len(test_symbols)} test assets")
        
        print(f"\n2. 🔄 Setting up {len(test_asset_ids)} test cycles (watching, quantity=0)...")
        
        # Create test cycles for all assets
        for asset_id, symbol in test_asset_ids:
            new_cycle = create_cycle(
                asset_id=asset_id,
                status='watching',
                quantity=Decimal('0'),  # This is key - triggers base order logic
                average_purchase_price=Decimal('0'),
                safety_orders=0,
                latest_order_id=None,
                last_order_fill_price=None
            )
            
            if not new_cycle:
                results['error_messages'].append(f"Failed to create test cycle for {symbol}")
                print(f"   ❌ Failed to create test cycle for {symbol}")
                continue
            
            test_cycle_ids.append((new_cycle.id, symbol))
            results['test_cycles_created'] += 1
            print(f"   ✅ Created cycle for {symbol} with ID: {new_cycle.id}")
        
        print(f"   ✅ Created {results['test_cycles_created']}/{len(test_asset_ids)} test cycles")
        
        print(f"\n3. 🔍 Checking for existing Alpaca positions...")
        
        # Ensure no existing positions for test symbols
        client = get_trading_client()
        if not client:
            results['error_messages'].append("Could not initialize Alpaca client")
            print("   ❌ Could not initialize Alpaca client")
            return False
        
        positions = get_positions(client)
        existing_positions = []
        
        for position in positions:
            if position.symbol in test_symbols and float(position.qty) != 0:
                existing_positions.append(position)
        
        if existing_positions:
            for pos in existing_positions:
                results['warning_messages'].append(f"Existing position: {pos.qty} {pos.symbol}")
                print(f"   ⚠️ WARNING: Existing position: {pos.qty} {pos.symbol}")
            print(f"   Found {len(existing_positions)} existing positions that may interfere")
        else:
            results['no_existing_positions'] = len(test_symbols)
            print(f"   ✅ No existing positions for any of the {len(test_symbols)} test symbols")
        
        print("\n4. 🚀 Starting main_app.py subprocess...")
        
        # Set up environment with TESTING_MODE for aggressive pricing
        test_env = os.environ.copy()
        test_env['TESTING_MODE'] = 'true'  # Enable aggressive pricing (5% above ask)
        
        # Start main_app.py as subprocess
        main_process = subprocess.Popen(
            ['python', 'src/main_app.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=os.getcwd(),
            env=test_env  # Use modified environment with TESTING_MODE
        )
        
        results['process_started'] = True
        print(f"   ✅ Process started with PID: {main_process.pid}")
        
        # Enhanced log monitoring with ERROR/WARNING detection
        class LogMonitor:
            def __init__(self, process):
                self.process = process
                self.log_queue = Queue()
                self.patterns_found = {}
                self.all_logs = []
                self.error_logs = []
                self.warning_logs = []
                self.running = True
                
                self.stdout_thread = threading.Thread(target=self._monitor_stdout, daemon=True)
                self.stderr_thread = threading.Thread(target=self._monitor_stderr, daemon=True)
                self.stdout_thread.start()
                self.stderr_thread.start()
            
            def _monitor_stdout(self):
                while self.running and self.process.poll() is None:
                    try:
                        line = self.process.stdout.readline()
                        if line:
                            line_str = line.decode('utf-8').strip()
                            self.log_queue.put(('stdout', line_str))
                            self.all_logs.append(line_str)
                            
                            # Check for ERROR/WARNING
                            if 'ERROR' in line_str:
                                self.error_logs.append(line_str)
                                print(f"   🚨 DETECTED ERROR: {line_str}")
                            elif 'WARNING' in line_str:
                                self.warning_logs.append(line_str)
                                print(f"   ⚠️ DETECTED WARNING: {line_str}")
                                
                    except Exception as e:
                        self.log_queue.put(('error', f"Error reading stdout: {e}"))
            
            def _monitor_stderr(self):
                while self.running and self.process.poll() is None:
                    try:
                        line = self.process.stderr.readline()
                        if line:
                            line_str = line.decode('utf-8').strip()
                            self.log_queue.put(('stderr', line_str))
                            self.all_logs.append(line_str)
                            
                            # Only treat actual ERROR/WARNING messages as problems
                            # Normal Python logging goes to stderr but isn't an "error"
                            if line_str.strip():
                                if " - ERROR - " in line_str:
                                    self.error_logs.append(f"ERROR: {line_str}")
                                    print(f"   🚨 ERROR: {line_str}")
                                elif " - WARNING - " in line_str:
                                    self.warning_logs.append(f"WARNING: {line_str}")
                                    print(f"   ⚠️ WARNING: {line_str}")
                                # Don't print normal INFO/DEBUG log messages
                                
                    except Exception as e:
                        self.log_queue.put(('error', f"Error reading stderr: {e}"))
            
            def wait_for_pattern(self, pattern, timeout=30, description="pattern"):
                print(f"   🔍 Waiting for {description}...")
                start_time = time.time()
                
                while time.time() - start_time < timeout:
                    try:
                        stream, line = self.log_queue.get(timeout=1)
                        if re.search(pattern, line):
                            self.patterns_found[pattern] = line
                            print(f"   ✅ Found {description}: {line}")
                            return line
                    except Empty:
                        continue
                    except Exception as e:
                        print(f"   Error in pattern search: {e}")
                        continue
                
                print(f"   ❌ Timeout waiting for {description} after {timeout}s")
                return None
            
            def wait_for_base_order_any_symbol(self, symbols, timeout=60):
                """Wait for base order placement on ANY of the provided symbols"""
                print(f"   🔍 Waiting for base order placement on ANY of: {', '.join(symbols)}...")
                start_time = time.time()
                
                # Create patterns for all symbols - updated to match actual log format
                base_order_patterns = [
                    f"LIMIT BUY order PLACED for {symbol}" for symbol in symbols
                ]
                
                while time.time() - start_time < timeout:
                    try:
                        stream, line = self.log_queue.get(timeout=1)
                        
                        # Check if this line matches any base order pattern
                        for pattern in base_order_patterns:
                            if pattern in line:
                                symbol = None
                                for s in symbols:
                                    if s in line:
                                        symbol = s
                                        break
                                        
                                self.patterns_found['base_order'] = line
                                print(f"   ✅ Found base order for {symbol}: {line}")
                                return line
                                
                    except Empty:
                        continue
                    except Exception as e:
                        print(f"   Error in base order search: {e}")
                        continue
                
                print(f"   ❌ Timeout waiting for base order placement after {timeout}s")
                return None
            
            def get_recent_logs(self, lines=10):
                return self.all_logs[-lines:] if self.all_logs else []
            
            def get_error_summary(self):
                return {
                    'errors': self.error_logs,
                    'warnings': self.warning_logs,
                    'error_count': len(self.error_logs),
                    'warning_count': len(self.warning_logs)
                }
            
            def stop(self):
                self.running = False
        
        log_monitor = LogMonitor(main_process)
        
        print("\n5. 🔌 Waiting for WebSocket streams to connect...")
        
        # Wait for stream connections using same patterns as Phase 3
        connection_found = log_monitor.wait_for_pattern(
            r'subscribed to.*quotes.*BTC/USD', 
            timeout=30, 
            description="stream connections"
        )
        
        if connection_found:
            results['streams_connected'] = True
            print("   ✅ WebSocket streams connected successfully!")
        else:
            results['error_messages'].append("WebSocket streams failed to connect")
            print("   ❌ WebSocket streams failed to connect")
            return False
        
        print(f"\n6. 💰 Waiting for base order placement on ANY of {len(test_symbols)} symbols...")
        print(f"   Symbols: {', '.join(test_symbols)}")
        print(f"   🚀 Using AGGRESSIVE pricing (5% above ask) for faster fills!")
        
        # Wait for base order placement on ANY symbol
        placed_message = log_monitor.wait_for_base_order_any_symbol(
            test_symbols, 
            timeout=base_order_timeout
        )
        
        if placed_message:
            results['base_order_placed'] = True
            # Extract order ID from the message
            match = re.search(r'Order ID ([a-f0-9\-]+)', placed_message)
            if match:
                placed_order_id = match.group(1)
                placed_order_ids.append(placed_order_id)
                print(f"   ✅ Base order placed! Order ID: {placed_order_id}")
                
                # Extract symbol from message
                symbol_match = None
                for symbol in test_symbols:
                    if symbol in placed_message:
                        symbol_match = symbol
                        break
                
                if symbol_match:
                    print(f"   💎 Order placed for: {symbol_match}")
                    results['placed_orders'].append({'id': placed_order_id, 'symbol': symbol_match})
            else:
                print(f"   ✅ Base order placed (could not extract order ID)")
        else:
            results['error_messages'].append(f"Base order was not placed within {base_order_timeout}s")
            print(f"   ❌ No base order placed for any symbol within {base_order_timeout}s")
            
            # Show recent logs for debugging
            print("\n   📋 Recent logs (for debugging):")
            for log_line in log_monitor.get_recent_logs(15):
                print(f"      {log_line}")
            
            return False
        
        print("\n7. 🔍 Waiting for ORDER FILLS and DATABASE UPDATES...")
        print("   ⏰ Waiting up to 90 seconds for order fills (aggressive pricing should fill quickly)...")
        
        # Give more time for order processing with aggressive pricing
        fill_timeout = 90  # 90 seconds for fills
        fill_start_time = time.time()
        
        order_filled = False
        database_updated = False
        
        while time.time() - fill_start_time < fill_timeout and not (order_filled and database_updated):
            time.sleep(2)  # Check every 2 seconds
            
            # Method 1: Check for fills in recent logs
            if not order_filled:
                recent_logs = log_monitor.get_recent_logs(30)
                for log_line in recent_logs:
                    if "ORDER FILLED SUCCESSFULLY" in log_line and any(symbol in log_line for symbol in test_symbols):
                        order_filled = True
                        print(f"   ✅ ORDER FILL detected in logs!")
                        break
            
            # Method 2: Check database for cycle updates (this is the key test!)
            if order_filled and not database_updated:
                try:
                    for asset_id, symbol in test_asset_ids:
                        updated_cycle = get_latest_cycle(asset_id)
                        if updated_cycle and updated_cycle.quantity > Decimal('0'):
                            database_updated = True
                            print(f"   ✅ DATABASE UPDATE detected for {symbol}!")
                            print(f"      🔄 Cycle quantity: {updated_cycle.quantity}")
                            print(f"      💰 Avg purchase price: ${updated_cycle.average_purchase_price}")
                            print(f"      📊 Last fill price: ${updated_cycle.last_order_fill_price}")
                            break
                except Exception as e:
                    print(f"   ⚠️ Error checking database: {e}")
            
            # Show progress
            elapsed = time.time() - fill_start_time
            if int(elapsed) % 10 == 0:  # Every 10 seconds
                print(f"   ⏰ Elapsed: {elapsed:.0f}s - Fill: {'✅' if order_filled else '❌'} | DB Update: {'✅' if database_updated else '❌'}")
        
        # Evaluate results
        if order_filled and database_updated:
            results['order_found_in_alpaca'] = True
            print(f"   🎉 COMPLETE SUCCESS! Order filled AND database updated!")
        elif order_filled:
            print(f"   ⚠️ PARTIAL SUCCESS: Order filled but database not updated (Phase 7 functionality missing)")
            print(f"   📋 This indicates the database update logic needs to be implemented in main_app.py")
        else:
            # Fallback: Check open orders as before
            print(f"   ⏰ Fill timeout reached. Checking for open orders...")
            open_orders = get_open_orders(client)
            current_open_orders = []
            
            for order in open_orders:
                if order.symbol in test_symbols and order.side == 'buy':
                    current_open_orders.append(order)
                    if order.id not in placed_order_ids:
                        placed_order_ids.append(order.id)
            
            if current_open_orders:
                results['order_found_in_alpaca'] = True
                print(f"   ✅ Found {len(current_open_orders)} OPEN order(s) (unfilled but valid)!")
                for order in current_open_orders:
                    print(f"      📋 Order ID: {order.id} | Symbol: {order.symbol} | Price: ${order.limit_price}")
            else:
                results['error_messages'].append("No evidence of successful order execution found")
                print(f"   ❌ No evidence of order execution found")
                return False
        
        print("\n8. 🚨 Error/Warning Summary:")
        error_summary = log_monitor.get_error_summary()
        
        if error_summary['error_count'] > 0:
            print(f"   🚨 {error_summary['error_count']} ERROR(S) detected:")
            for error in error_summary['errors'][-5:]:  # Show last 5 errors
                print(f"      • {error}")
            results['error_messages'].extend(error_summary['errors'])
        else:
            print("   ✅ No errors detected")
        
        if error_summary['warning_count'] > 0:
            print(f"   ⚠️ {error_summary['warning_count']} WARNING(S) detected:")
            for warning in error_summary['warnings'][-5:]:  # Show last 5 warnings
                print(f"      • {warning}")
            results['warning_messages'].extend(error_summary['warnings'])
        else:
            print("   ✅ No warnings detected")
        
        print("\n9. 📋 Phase 4 Test Results:")
        print("="*50)
        
        # Calculate success
        critical_tests = [
            'test_assets_created',
            'test_cycles_created', 
            'process_started',
            'streams_connected',
            'base_order_placed',
            'order_found_in_alpaca'
        ]
        
        print(f"✅ Asset Setup: {results['test_assets_created']}/{len(test_symbols)} assets created")
        print(f"✅ Cycle Setup: {results['test_cycles_created']}/{len(test_symbols)} cycles created")
        print(f"✅ Process Started: {'✅ PASS' if results['process_started'] else '❌ FAIL'}")
        print(f"✅ Streams Connected: {'✅ PASS' if results['streams_connected'] else '❌ FAIL'}")
        print(f"✅ Base Order Placed: {'✅ PASS' if results['base_order_placed'] else '❌ FAIL'}")
        print(f"✅ Order in Alpaca: {'✅ PASS' if results['order_found_in_alpaca'] else '❌ FAIL'}")
        
        # Calculate critical success
        critical_passed = (
            results['test_assets_created'] >= len(test_symbols) // 2 and  # At least half the assets
            results['test_cycles_created'] >= len(test_symbols) // 2 and  # At least half the cycles
            results['process_started'] and
            results['streams_connected'] and
            results['base_order_placed'] and
            results['order_found_in_alpaca']
        )
        
        if results['error_messages']:
            print(f"\n❌ Errors encountered ({len(results['error_messages'])}):")
            for error in results['error_messages'][-3:]:  # Show last 3
                print(f"   • {error}")
        
        if results['warning_messages']:
            print(f"\n⚠️ Warnings encountered ({len(results['warning_messages'])}):")
            for warning in results['warning_messages'][-3:]:  # Show last 3
                print(f"   • {warning}")
        
        # Determine overall result
        if critical_passed:
            print(f"\n🎉 PHASE 4 TEST: ✅ PASSED")
            print(f"   MarketData stream successfully places base orders!")
            print(f"   Tested {len(test_symbols)} crypto pairs for maximum coverage!")
            return True
        else:
            print(f"\n❌ PHASE 4 TEST: ❌ FAILED") 
            print("   Base order placement logic is not working correctly")
            return False
            
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR in Phase 4 test: {e}")
        logger.exception("Phase 4 test failed with exception")
        return False
        
    finally:
        print(f"\n🧹 Cleaning up...")
        
        # Stop log monitoring
        if log_monitor:
            log_monitor.stop()
        
        # Stop main_app.py process
        if main_process and main_process.poll() is None:
            try:
                print("   Stopping main_app.py...")
                main_process.send_signal(signal.SIGINT)
                main_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("   Force killing process...")
                main_process.kill()
                main_process.wait()
            except Exception as e:
                print(f"   Error stopping process: {e}")
        
        # Cancel ALL test orders (both tracked and any untracked ones)
        if client:
            try:
                print("   🧹 Cancelling all test orders...")
                open_orders = get_open_orders(client)
                
                # Cancel all orders for our test symbols
                cancelled_count = 0
                for order in open_orders:
                    if order.symbol in test_symbols and order.side == 'buy':
                        try:
                            cancel_success = cancel_order(client, order.id)
                            if cancel_success:
                                cancelled_count += 1
                                print(f"   ✅ Cancelled order {order.id} for {order.symbol}")
                            else:
                                print(f"   ⚠️ Could not cancel order {order.id}")
                        except Exception as e:
                            print(f"   ⚠️ Error cancelling order {order.id}: {e}")
                
                print(f"   ✅ Cancelled {cancelled_count} test orders")
                
            except Exception as e:
                print(f"   ⚠️ Error during order cleanup: {e}")
        
        # Clean up ALL database entries
        try:
            print("   🧹 Cleaning up database entries...")
            
            # Delete all test cycles
            deleted_cycles = 0
            for cycle_id, symbol in test_cycle_ids:
                try:
                    delete_cycle_query = "DELETE FROM dca_cycles WHERE id = %s"
                    execute_query(delete_cycle_query, (cycle_id,), commit=True)
                    deleted_cycles += 1
                except Exception as e:
                    print(f"   ⚠️ Error deleting cycle {cycle_id}: {e}")
            
            print(f"   ✅ Deleted {deleted_cycles} test cycles")
            
            # Delete all test assets
            deleted_assets = 0
            for asset_id, symbol in test_asset_ids:
                try:
                    delete_asset_query = "DELETE FROM dca_assets WHERE id = %s"
                    execute_query(delete_asset_query, (asset_id,), commit=True)
                    deleted_assets += 1
                except Exception as e:
                    print(f"   ⚠️ Error deleting asset {asset_id}: {e}")
            
            print(f"   ✅ Deleted {deleted_assets} test assets")
            
            results['cleanup_completed'] = True
            print("   ✅ Database cleanup completed")
                
        except Exception as e:
            print(f"   ⚠️ Error during database cleanup: {e}")
        
        print("   ✅ Phase 4 cleanup completed")


def main():
    """Main integration test runner."""
    print("DCA Trading Bot - Integration Test Suite")
    print(f"Started at: {datetime.now()}")
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ ERROR: .env file not found. Please create it with database credentials.")
        print("Refer to README.md for required environment variables.")
        return
    
    # Parse command line arguments
    if len(sys.argv) > 1:
        phase_arg = sys.argv[1].lower()
        if phase_arg == 'phase1':
            print("\n🎯 Running ONLY Phase 1 tests...")
            phase1_success = test_phase1_asset_and_cycle_crud()
            if phase1_success:
                print("\n🎉 Phase 1: ✅ PASSED")
            else:
                print("\n❌ Phase 1: ❌ FAILED")
                sys.exit(1)
            return
        elif phase_arg == 'phase2':
            print("\n🎯 Running ONLY Phase 2 tests...")
            phase2_success = test_phase2_alpaca_rest_api_order_cycle()
            if phase2_success:
                print("\n🎉 Phase 2: ✅ PASSED")
            else:
                print("\n❌ Phase 2: ❌ FAILED")
                sys.exit(1)
            return
        elif phase_arg == 'phase3':
            print("\n🎯 Running ONLY Phase 3 tests...")
            phase3_success = test_phase3_websocket_connection_and_data_receipt()
            if phase3_success:
                print("\n🎉 Phase 3: ✅ PASSED")
            else:
                print("\n❌ Phase 3: ❌ FAILED")
                sys.exit(1)
            return
        elif phase_arg == 'phase4':
            print("\n🎯 Running ONLY Phase 4 tests...")
            phase4_success = test_phase4_marketdata_places_base_order()
            if phase4_success:
                print("\n🎉 Phase 4: ✅ PASSED")
            else:
                print("\n❌ Phase 4: ❌ FAILED")
                sys.exit(1)
            return
        elif phase_arg in ['help', '--help', '-h']:
            print_help()
            return
        else:
            print(f"❌ ERROR: Unknown argument '{sys.argv[1]}'")
            print_help()
            sys.exit(1)
    
    # Run all phases if no specific phase requested
    print("\n🎯 Running ALL integration tests...")
    
    # Track test results
    phase1_success = False
    phase2_success = False
    phase3_success = False
    phase4_success = False
    
    # Run Phase 1 tests
    print("\nRunning Phase 1 tests...")
    phase1_success = test_phase1_asset_and_cycle_crud()
    
    # Run Phase 2 tests
    print("\nRunning Phase 2 tests...")
    phase2_success = test_phase2_alpaca_rest_api_order_cycle()
    
    # Run Phase 3 tests (manual verification)
    print("\nRunning Phase 3 tests...")
    phase3_success = test_phase3_websocket_connection_and_data_receipt()
    
    # Run Phase 4 tests (manual verification)
    print("\nRunning Phase 4 tests...")
    phase4_success = test_phase4_marketdata_places_base_order()
    
    # Final results
    print("\n" + "="*60)
    print("INTEGRATION TEST RESULTS SUMMARY")
    print("="*60)
    
    print(f"Phase 1 (Database CRUD): {'✅ PASSED' if phase1_success else '❌ FAILED'}")
    print(f"Phase 2 (Alpaca REST API): {'✅ PASSED' if phase2_success else '❌ FAILED'}")
    print(f"Phase 3 (WebSocket Streams): {'✅ READY FOR MANUAL TEST' if phase3_success else '❌ PREREQUISITES FAILED'}")
    print(f"Phase 4 (MarketData Places Base Order): {'✅ READY FOR MANUAL TEST' if phase4_success else '❌ PREREQUISITES FAILED'}")
    
    if phase1_success and phase2_success and phase3_success and phase4_success:
        print("\n🎉 ALL AUTOMATED TESTS PASSED!")
        print("Phase 4 requires manual verification - follow the instructions above.")
        print("The DCA Trading Bot Phase 1, 2, & 4 functionality is ready for testing!")
    else:
        print("\n❌ SOME TESTS FAILED!")
        print("Please review the errors above and fix any issues.")
        sys.exit(1)


def print_help():
    """Print help information for the integration test script."""
    print("\nUSAGE:")
    print("  python integration_test.py                 # Run all phases")
    print("  python integration_test.py phase1          # Run only Phase 1 (Database CRUD)")
    print("  python integration_test.py phase2          # Run only Phase 2 (Alpaca REST API)")
    print("  python integration_test.py phase3          # Run only Phase 3 (WebSocket Streams)")
    print("  python integration_test.py phase4          # Run only Phase 4 (MarketData Places Base Order)")
    print("  python integration_test.py help            # Show this help")
    print("\nPHASE DESCRIPTIONS:")
    print("  Phase 1: Tests database CRUD operations (dca_assets, dca_cycles tables)")
    print("  Phase 2: Tests Alpaca REST API integration (orders, account, positions)")
    print("  Phase 3: Tests WebSocket connections and trade updates")
    print("  Phase 4: Tests complete flow from market data to base order placement")
    print("")


if __name__ == '__main__':
    main() 