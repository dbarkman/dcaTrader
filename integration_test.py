#!/usr/bin/env python3
"""
Integration test script for the DCA trading bot.
This script tests end-to-end scenarios against a real database.

Phase 1: Basic CRUD operations for dca_assets and dca_cycles.
"""

import os
import sys
import logging
from datetime import datetime
from decimal import Decimal

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db_utils import execute_query, check_connection
from models.asset_config import get_asset_config, update_asset_config
from models.cycle_data import create_cycle, get_latest_cycle, update_cycle

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


def main():
    """Main integration test runner."""
    print("DCA Trading Bot - Integration Test Suite")
    print(f"Started at: {datetime.now()}")
    
    # Check if .env file exists
    if not os.path.exists('.env'):
        print("❌ ERROR: .env file not found. Please create it with database credentials.")
        print("Refer to README.md for required environment variables.")
        return
    
    # Run Phase 1 tests
    success = test_phase1_asset_and_cycle_crud()
    
    if success:
        print("\n🎉 ALL INTEGRATION TESTS PASSED!")
    else:
        print("\n❌ SOME INTEGRATION TESTS FAILED!")
        sys.exit(1)


if __name__ == '__main__':
    main() 