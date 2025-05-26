#!/usr/bin/env python3
"""
Unit Tests for Order Manager Caretaker Script

Tests the order_manager.py functionality for identifying and managing
stale and orphaned orders.
"""

import unittest
from unittest.mock import Mock, patch
from datetime import datetime, timezone, timedelta
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))

# Import the order manager functions
from order_manager import (
    identify_stale_buy_orders,
    identify_orphaned_orders,
    identify_stuck_sell_orders,
    handle_stuck_sell_orders,
    calculate_order_age,
    get_active_cycle_order_ids,
    STALE_ORDER_THRESHOLD,
    STUCK_MARKET_SELL_TIMEOUT_SECONDS
)


class TestOrderManager(unittest.TestCase):
    """Test cases for order manager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.current_time = datetime.now(timezone.utc)
        self.old_time = self.current_time - timedelta(minutes=10)  # 10 minutes ago
        self.recent_time = self.current_time - timedelta(minutes=2)  # 2 minutes ago
        
    def create_mock_order(self, order_id, symbol, side, order_type, created_at, limit_price=None, qty="0.001"):
        """Create a mock Alpaca order object."""
        mock_order = Mock()
        mock_order.id = order_id
        mock_order.symbol = symbol
        mock_order.side = Mock()
        mock_order.side.value = side
        mock_order.order_type = Mock()
        mock_order.order_type.value = order_type
        mock_order.created_at = created_at
        mock_order.limit_price = limit_price
        mock_order.qty = qty
        return mock_order
    
    def test_identify_stale_buy_orders(self):
        """
        Test identification of stale BUY limit orders.
        
        Given a list of mock Alpaca order objects (with varying created_at, side, type),
        assert correct ones are identified as stale.
        """
        # Create mock orders with different characteristics
        orders = [
            # Stale BUY limit order (should be identified)
            self.create_mock_order(
                order_id="stale_buy_1",
                symbol="BTC/USD",
                side="buy",
                order_type="limit",
                created_at=self.old_time,
                limit_price=50000.0
            ),
            
            # Recent BUY limit order (should NOT be identified - too new)
            self.create_mock_order(
                order_id="recent_buy_1",
                symbol="ETH/USD", 
                side="buy",
                order_type="limit",
                created_at=self.recent_time,
                limit_price=3000.0
            ),
            
            # Stale SELL order (should NOT be identified - wrong side)
            self.create_mock_order(
                order_id="stale_sell_1",
                symbol="BTC/USD",
                side="sell",
                order_type="limit",
                created_at=self.old_time,
                limit_price=60000.0
            ),
            
            # Stale BUY market order (should NOT be identified - wrong type)
            self.create_mock_order(
                order_id="stale_buy_market",
                symbol="ADA/USD",
                side="buy", 
                order_type="market",
                created_at=self.old_time
            ),
            
            # Another stale BUY limit order (should be identified)
            self.create_mock_order(
                order_id="stale_buy_2",
                symbol="SOL/USD",
                side="buy",
                order_type="limit", 
                created_at=self.old_time,
                limit_price=100.0
            )
        ]
        
        # Active order IDs (orders tracked in database)
        active_order_ids = {"recent_buy_1"}  # This order is actively tracked
        
        # Test the function
        stale_orders = identify_stale_buy_orders(orders, active_order_ids, self.current_time)
        
        # Assertions
        self.assertEqual(len(stale_orders), 2, "Should identify exactly 2 stale BUY orders")
        
        stale_order_ids = [order.id for order in stale_orders]
        self.assertIn("stale_buy_1", stale_order_ids, "Should identify stale_buy_1")
        self.assertIn("stale_buy_2", stale_order_ids, "Should identify stale_buy_2")
        self.assertNotIn("recent_buy_1", stale_order_ids, "Should NOT identify recent_buy_1 (too new)")
        self.assertNotIn("stale_sell_1", stale_order_ids, "Should NOT identify stale_sell_1 (wrong side)")
        self.assertNotIn("stale_buy_market", stale_order_ids, "Should NOT identify stale_buy_market (wrong type)")
        
        # Verify order characteristics
        for order in stale_orders:
            self.assertEqual(order.side.value, "buy", "All stale orders should be BUY orders")
            self.assertEqual(order.order_type.value, "limit", "All stale orders should be LIMIT orders")
            age = calculate_order_age(order.created_at, self.current_time)
            self.assertGreater(age, STALE_ORDER_THRESHOLD, "All stale orders should be older than threshold")
    
    def test_identify_stale_buy_orders_with_tracked_orders(self):
        """Test that actively tracked orders are preserved and NOT identified as stale."""
        # Create a stale BUY order that is tracked in database
        tracked_order = self.create_mock_order(
            order_id="tracked_stale_buy",
            symbol="BTC/USD",
            side="buy",
            order_type="limit",
            created_at=self.old_time,
            limit_price=50000.0
        )
        
        orders = [tracked_order]
        active_order_ids = {"tracked_stale_buy"}  # This order is actively tracked
        
        stale_orders = identify_stale_buy_orders(orders, active_order_ids, self.current_time)
        
        # Should NOT identify tracked orders as stale - they should be preserved
        self.assertEqual(len(stale_orders), 0, "Should preserve tracked orders even when old")
        
        # Test with mixed tracked and untracked orders
        untracked_order = self.create_mock_order(
            order_id="untracked_stale_buy",
            symbol="ETH/USD",
            side="buy",
            order_type="limit",
            created_at=self.old_time,
            limit_price=3000.0
        )
        
        mixed_orders = [tracked_order, untracked_order]
        stale_orders_mixed = identify_stale_buy_orders(mixed_orders, active_order_ids, self.current_time)
        
        # Should only identify untracked order as stale
        self.assertEqual(len(stale_orders_mixed), 1, "Should identify only untracked stale orders")
        self.assertEqual(stale_orders_mixed[0].id, "untracked_stale_buy", "Should identify the untracked order")
    
    def test_identify_orphaned_orders(self):
        """
        Test identification of orphaned orders.
        
        Given mock Alpaca orders and mock dca_cycles data, 
        assert correct orders are identified as orphans.
        """
        # Create mock orders
        orders = [
            # Old BUY order not tracked (should be identified as orphaned)
            self.create_mock_order(
                order_id="orphan_buy_1",
                symbol="BTC/USD",
                side="buy",
                order_type="limit",
                created_at=self.old_time,
                limit_price=50000.0
            ),
            
            # Old SELL order not tracked (should be identified as orphaned)
            self.create_mock_order(
                order_id="orphan_sell_1", 
                symbol="ETH/USD",
                side="sell",
                order_type="limit",
                created_at=self.old_time,
                limit_price=4000.0
            ),
            
            # Recent order not tracked (should NOT be identified - too new)
            self.create_mock_order(
                order_id="recent_orphan",
                symbol="ADA/USD",
                side="buy",
                order_type="limit", 
                created_at=self.recent_time,
                limit_price=1.0
            ),
            
            # Old order that IS tracked (should NOT be identified - actively tracked)
            self.create_mock_order(
                order_id="tracked_old_order",
                symbol="SOL/USD",
                side="buy",
                order_type="limit",
                created_at=self.old_time,
                limit_price=100.0
            ),
            
            # Old market order not tracked (should be identified as orphaned)
            self.create_mock_order(
                order_id="orphan_market_1",
                symbol="MATIC/USD", 
                side="sell",
                order_type="market",
                created_at=self.old_time
            )
        ]
        
        # Mock active cycle data - only one order is actively tracked
        active_order_ids = {"tracked_old_order"}
        
        # Test the function
        orphaned_orders = identify_orphaned_orders(orders, active_order_ids, self.current_time)
        
        # Assertions
        self.assertEqual(len(orphaned_orders), 3, "Should identify exactly 3 orphaned orders")
        
        orphaned_order_ids = [order.id for order in orphaned_orders]
        self.assertIn("orphan_buy_1", orphaned_order_ids, "Should identify orphan_buy_1")
        self.assertIn("orphan_sell_1", orphaned_order_ids, "Should identify orphan_sell_1") 
        self.assertIn("orphan_market_1", orphaned_order_ids, "Should identify orphan_market_1")
        self.assertNotIn("recent_orphan", orphaned_order_ids, "Should NOT identify recent_orphan (too new)")
        self.assertNotIn("tracked_old_order", orphaned_order_ids, "Should NOT identify tracked_old_order (actively tracked)")
        
        # Verify all orphaned orders are old enough
        for order in orphaned_orders:
            age = calculate_order_age(order.created_at, self.current_time)
            self.assertGreater(age, STALE_ORDER_THRESHOLD, "All orphaned orders should be older than threshold")
    
    def test_identify_orphaned_orders_empty_active_set(self):
        """Test orphaned order identification when no orders are actively tracked."""
        # Create old orders
        orders = [
            self.create_mock_order(
                order_id="orphan_1",
                symbol="BTC/USD", 
                side="buy",
                order_type="limit",
                created_at=self.old_time,
                limit_price=50000.0
            ),
            self.create_mock_order(
                order_id="orphan_2",
                symbol="ETH/USD",
                side="sell", 
                order_type="market",
                created_at=self.old_time
            )
        ]
        
        # No active orders
        active_order_ids = set()
        
        orphaned_orders = identify_orphaned_orders(orders, active_order_ids, self.current_time)
        
        # All old orders should be identified as orphaned
        self.assertEqual(len(orphaned_orders), 2, "Should identify all old orders as orphaned when none are tracked")
    
    def test_calculate_order_age(self):
        """Test order age calculation with timezone handling."""
        # Test with timezone-aware timestamps
        order_time = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        current_time = datetime(2023, 1, 1, 12, 10, 0, tzinfo=timezone.utc)  # 10 minutes later
        
        age = calculate_order_age(order_time, current_time)
        self.assertEqual(age, timedelta(minutes=10), "Should calculate correct age")
        
        # Test with naive timestamps (should assume UTC)
        order_time_naive = datetime(2023, 1, 1, 12, 0, 0)  # No timezone
        current_time_naive = datetime(2023, 1, 1, 12, 5, 0)  # No timezone
        
        age_naive = calculate_order_age(order_time_naive, current_time_naive)
        self.assertEqual(age_naive, timedelta(minutes=5), "Should handle naive timestamps")
    
    @patch('order_manager.execute_query')
    def test_get_active_cycle_order_ids(self, mock_execute_query):
        """Test fetching active cycle order IDs from database."""
        # Mock database response
        mock_execute_query.return_value = [
            {'latest_order_id': 'order_123'},
            {'latest_order_id': 'order_456'},
            {'latest_order_id': 'order_789'},
            {'latest_order_id': None}  # Should be filtered out
        ]
        
        active_ids = get_active_cycle_order_ids()
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        self.assertIn('dca_cycles', call_args[0][0])  # Query should reference dca_cycles table
        self.assertIn("status IN ('buying', 'selling')", call_args[0][0])  # Should filter by status
        
        # Verify results
        expected_ids = {'order_123', 'order_456', 'order_789'}
        self.assertEqual(active_ids, expected_ids, "Should return correct set of active order IDs")
    
    @patch('order_manager.execute_query')
    def test_get_active_cycle_order_ids_empty_result(self, mock_execute_query):
        """Test handling of empty database result."""
        mock_execute_query.return_value = []
        
        active_ids = get_active_cycle_order_ids()
        
        self.assertEqual(active_ids, set(), "Should return empty set when no active cycles found")
    
    @patch('order_manager.execute_query')
    def test_get_active_cycle_order_ids_database_error(self, mock_execute_query):
        """Test handling of database errors."""
        mock_execute_query.side_effect = Exception("Database connection failed")
        
        active_ids = get_active_cycle_order_ids()
        
        self.assertEqual(active_ids, set(), "Should return empty set on database error")
    
    @patch('order_manager.execute_query')
    def test_identify_stuck_sell_orders(self, mock_execute_query):
        """Test identification of stuck market SELL orders."""
        from models.cycle_data import DcaCycle
        from decimal import Decimal
        
        # Create mock cycle data - one stuck, one recent
        stuck_time = self.current_time - timedelta(seconds=STUCK_MARKET_SELL_TIMEOUT_SECONDS + 10)
        recent_time = self.current_time - timedelta(seconds=30)  # Not stuck yet
        
        mock_execute_query.return_value = [
            {
                'id': 1, 'asset_id': 1, 'status': 'selling',
                'quantity': Decimal('1.0'), 'average_purchase_price': Decimal('50000.0'),
                'safety_orders': 0, 'latest_order_id': 'stuck_order_123',
                'latest_order_created_at': stuck_time, 'last_order_fill_price': None,
                'completed_at': None, 'created_at': self.current_time, 'updated_at': self.current_time
            },
            {
                'id': 2, 'asset_id': 1, 'status': 'selling',
                'quantity': Decimal('0.5'), 'average_purchase_price': Decimal('3000.0'),
                'safety_orders': 1, 'latest_order_id': 'recent_order_456',
                'latest_order_created_at': recent_time, 'last_order_fill_price': None,
                'completed_at': None, 'created_at': self.current_time, 'updated_at': self.current_time
            }
        ]
        
        stuck_cycles = identify_stuck_sell_orders(self.current_time)
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        self.assertIn("status = 'selling'", call_args[0][0])
        self.assertIn("latest_order_id IS NOT NULL", call_args[0][0])
        self.assertIn("latest_order_created_at IS NOT NULL", call_args[0][0])
        
        # Should identify only the stuck order
        self.assertEqual(len(stuck_cycles), 1, "Should identify exactly 1 stuck SELL order")
        self.assertEqual(stuck_cycles[0].id, 1, "Should identify the stuck cycle")
        self.assertEqual(stuck_cycles[0].latest_order_id, 'stuck_order_123', "Should have correct order ID")
    
    @patch('order_manager.execute_query')
    def test_identify_stuck_sell_orders_empty_result(self, mock_execute_query):
        """Test handling when no cycles are in selling status."""
        mock_execute_query.return_value = []
        
        stuck_cycles = identify_stuck_sell_orders(self.current_time)
        
        self.assertEqual(len(stuck_cycles), 0, "Should return empty list when no selling cycles found")
    
    @patch('order_manager.execute_query')
    def test_identify_stuck_sell_orders_database_error(self, mock_execute_query):
        """Test handling of database errors."""
        mock_execute_query.side_effect = Exception("Database connection failed")
        
        stuck_cycles = identify_stuck_sell_orders(self.current_time)
        
        self.assertEqual(len(stuck_cycles), 0, "Should return empty list on database error")
    
    @patch('order_manager.get_order')
    @patch('order_manager.cancel_order')
    def test_handle_stuck_sell_orders_active_order(self, mock_cancel_order, mock_get_order):
        """Test handling stuck SELL order when Alpaca order is still active."""
        from models.cycle_data import DcaCycle
        from decimal import Decimal
        
        # Create mock stuck cycle
        stuck_cycle = DcaCycle(
            id=1, asset_id=1, status='selling',
            quantity=Decimal('1.0'), average_purchase_price=Decimal('50000.0'),
            safety_orders=0, latest_order_id='stuck_order_123',
            latest_order_created_at=self.current_time - timedelta(seconds=100),
            last_order_fill_price=None, completed_at=None,
            created_at=self.current_time, updated_at=self.current_time
        )
        
        # Mock Alpaca order in active state
        mock_alpaca_order = Mock()
        mock_alpaca_order.status = Mock()
        mock_alpaca_order.status.value = 'accepted'
        mock_get_order.return_value = mock_alpaca_order
        
        # Mock successful cancellation
        mock_cancel_order.return_value = True
        
        # Mock client
        mock_client = Mock()
        
        # Test the function
        canceled_count = handle_stuck_sell_orders(mock_client, [stuck_cycle])
        
        # Verify calls
        mock_get_order.assert_called_once_with(mock_client, 'stuck_order_123')
        mock_cancel_order.assert_called_once_with(mock_client, 'stuck_order_123')
        
        # Should have canceled 1 order
        self.assertEqual(canceled_count, 1, "Should cancel 1 stuck order")
    
    @patch('order_manager.get_order')
    @patch('order_manager.cancel_order')
    def test_handle_stuck_sell_orders_terminal_state(self, mock_cancel_order, mock_get_order):
        """Test handling stuck SELL order when Alpaca order is already in terminal state."""
        from models.cycle_data import DcaCycle
        from decimal import Decimal
        
        # Create mock stuck cycle
        stuck_cycle = DcaCycle(
            id=1, asset_id=1, status='selling',
            quantity=Decimal('1.0'), average_purchase_price=Decimal('50000.0'),
            safety_orders=0, latest_order_id='filled_order_123',
            latest_order_created_at=self.current_time - timedelta(seconds=100),
            last_order_fill_price=None, completed_at=None,
            created_at=self.current_time, updated_at=self.current_time
        )
        
        # Mock Alpaca order in terminal state
        mock_alpaca_order = Mock()
        mock_alpaca_order.status = Mock()
        mock_alpaca_order.status.value = 'filled'
        mock_get_order.return_value = mock_alpaca_order
        
        # Mock client
        mock_client = Mock()
        
        # Test the function
        canceled_count = handle_stuck_sell_orders(mock_client, [stuck_cycle])
        
        # Verify calls
        mock_get_order.assert_called_once_with(mock_client, 'filled_order_123')
        mock_cancel_order.assert_not_called()  # Should not attempt cancellation
        
        # Should not have canceled any orders
        self.assertEqual(canceled_count, 0, "Should not cancel orders in terminal state")
    
    @patch('order_manager.get_order')
    @patch('order_manager.cancel_order')
    def test_handle_stuck_sell_orders_order_not_found(self, mock_cancel_order, mock_get_order):
        """Test handling stuck SELL order when Alpaca order is not found."""
        from models.cycle_data import DcaCycle
        from decimal import Decimal
        
        # Create mock stuck cycle
        stuck_cycle = DcaCycle(
            id=1, asset_id=1, status='selling',
            quantity=Decimal('1.0'), average_purchase_price=Decimal('50000.0'),
            safety_orders=0, latest_order_id='missing_order_123',
            latest_order_created_at=self.current_time - timedelta(seconds=100),
            last_order_fill_price=None, completed_at=None,
            created_at=self.current_time, updated_at=self.current_time
        )
        
        # Mock order not found
        mock_get_order.return_value = None
        
        # Mock client
        mock_client = Mock()
        
        # Test the function
        canceled_count = handle_stuck_sell_orders(mock_client, [stuck_cycle])
        
        # Verify calls
        mock_get_order.assert_called_once_with(mock_client, 'missing_order_123')
        mock_cancel_order.assert_not_called()  # Should not attempt cancellation
        
        # Should not have canceled any orders
        self.assertEqual(canceled_count, 0, "Should not cancel orders that are not found")


if __name__ == '__main__':
    unittest.main() 