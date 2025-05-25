#!/usr/bin/env python3
"""
Unit Tests for Consistency Checker Caretaker Script

Tests the consistency_checker.py functionality for maintaining data consistency
between the database and Alpaca's live state.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))

# Import the consistency checker functions
from consistency_checker import (
    get_stuck_buying_cycles,
    get_watching_cycles_with_quantity,
    is_order_stale_or_terminal,
    process_stuck_buying_cycle,
    has_alpaca_position,
    process_orphaned_watching_cycle,
    get_current_utc_time
)

# Import models for testing
from models.cycle_data import DcaCycle
from models.asset_config import DcaAsset
from alpaca.common.exceptions import APIError


class TestConsistencyChecker(unittest.TestCase):
    """Test cases for consistency checker functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.current_time = datetime.now(timezone.utc)
        self.old_time = self.current_time - timedelta(minutes=10)  # 10 minutes ago
        self.recent_time = self.current_time - timedelta(minutes=2)  # 2 minutes ago
        
    def create_mock_cycle(self, cycle_id, asset_id, status, quantity=None, latest_order_id=None, created_at=None):
        """Create a mock DcaCycle object."""
        cycle = Mock(spec=DcaCycle)
        cycle.id = cycle_id
        cycle.asset_id = asset_id
        cycle.status = status
        cycle.quantity = quantity or Decimal('0')
        cycle.latest_order_id = latest_order_id
        cycle.created_at = created_at or self.current_time
        cycle.completed_at = None
        cycle.average_purchase_price = Decimal('0')
        cycle.safety_orders = 0
        cycle.last_order_fill_price = None
        return cycle
    
    def create_mock_asset(self, asset_id, symbol):
        """Create a mock DcaAsset object."""
        asset = Mock(spec=DcaAsset)
        asset.id = asset_id
        asset.asset_symbol = symbol
        asset.is_enabled = True
        asset.base_order_amount = Decimal('100.0')
        asset.safety_order_amount = Decimal('150.0')
        asset.safety_order_deviation = Decimal('2.5')
        asset.max_safety_orders = 3
        asset.take_profit_percent = Decimal('1.0')
        asset.cooldown_period = 60
        asset.buy_order_price_deviation_percent = Decimal('0.1')
        asset.last_sell_price = None
        return asset
    
    def create_mock_order(self, order_id, status, created_at=None):
        """Create a mock Alpaca order object."""
        order = Mock()
        order.id = order_id
        order.status = Mock()
        order.status.value = status
        order.created_at = created_at or self.current_time
        return order
    
    def create_mock_position(self, symbol, qty):
        """Create a mock Alpaca position object."""
        position = Mock()
        position.symbol = symbol
        position.qty = str(qty)
        return position
    
    @patch('consistency_checker.execute_query')
    def test_get_stuck_buying_cycles(self, mock_execute_query):
        """Test fetching cycles in buying status."""
        # Mock database response
        mock_execute_query.return_value = [
            {
                'id': 1,
                'asset_id': 100,
                'status': 'buying',
                'created_at': self.current_time,
                'updated_at': self.current_time,
                'completed_at': None,
                'quantity': Decimal('0.01'),
                'average_purchase_price': Decimal('50000.0'),
                'safety_orders': 0,
                'latest_order_id': 'order_123',
                'last_order_fill_price': None
            },
            {
                'id': 2,
                'asset_id': 101,
                'status': 'buying',
                'created_at': self.recent_time,
                'updated_at': self.recent_time,
                'completed_at': None,
                'quantity': Decimal('0'),
                'average_purchase_price': Decimal('0'),
                'safety_orders': 0,
                'latest_order_id': None,
                'last_order_fill_price': None
            }
        ]
        
        cycles = get_stuck_buying_cycles()
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        self.assertIn("status = 'buying'", call_args[0][0])
        
        # Verify results
        self.assertEqual(len(cycles), 2, "Should return 2 buying cycles")
        self.assertEqual(cycles[0].id, 1, "First cycle should have ID 1")
        self.assertEqual(cycles[1].id, 2, "Second cycle should have ID 2")
    
    @patch('consistency_checker.execute_query')
    def test_get_stuck_buying_cycles_empty_result(self, mock_execute_query):
        """Test handling of no buying cycles found."""
        mock_execute_query.return_value = []
        
        cycles = get_stuck_buying_cycles()
        
        self.assertEqual(cycles, [], "Should return empty list when no buying cycles found")
    
    @patch('consistency_checker.execute_query')
    def test_get_watching_cycles_with_quantity(self, mock_execute_query):
        """Test fetching watching cycles with quantity > 0."""
        # Mock database response
        mock_execute_query.return_value = [
            {
                'id': 10,
                'asset_id': 100,
                'status': 'watching',
                'created_at': self.old_time,
                'updated_at': self.old_time,
                'completed_at': None,
                'quantity': Decimal('0.01'),
                'average_purchase_price': Decimal('50000.0'),
                'safety_orders': 1,
                'latest_order_id': None,
                'last_order_fill_price': Decimal('51000.0')
            }
        ]
        
        cycles = get_watching_cycles_with_quantity()
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        query = call_args[0][0]
        self.assertIn("status = 'watching'", query)
        self.assertIn("quantity > 0", query)
        
        # Verify results
        self.assertEqual(len(cycles), 1, "Should return 1 watching cycle with quantity")
        self.assertEqual(cycles[0].id, 10, "Cycle should have ID 10")
        self.assertGreater(cycles[0].quantity, Decimal('0'), "Cycle should have quantity > 0")
    
    @patch('consistency_checker.execute_query')
    def test_get_watching_cycles_with_quantity_empty_result(self, mock_execute_query):
        """Test handling of no watching cycles with quantity found."""
        mock_execute_query.return_value = []
        
        cycles = get_watching_cycles_with_quantity()
        
        self.assertEqual(cycles, [], "Should return empty list when no watching cycles with quantity found")
    
    def test_is_order_stale_or_terminal_order_not_found(self):
        """Test order staleness check when order is not found."""
        mock_client = Mock()
        mock_client.get_order_by_id.side_effect = APIError("Order not found")
        
        result = is_order_stale_or_terminal(mock_client, "fake_order_id", self.current_time)
        
        self.assertTrue(result, "Should return True when order is not found")
        mock_client.get_order_by_id.assert_called_once_with("fake_order_id")
    
    def test_is_order_stale_or_terminal_order_filled(self):
        """Test order staleness check when order is filled."""
        mock_client = Mock()
        mock_order = self.create_mock_order("order_123", "filled")
        mock_client.get_order_by_id.return_value = mock_order
        
        result = is_order_stale_or_terminal(mock_client, "order_123", self.current_time)
        
        self.assertTrue(result, "Should return True when order is filled")
    
    def test_is_order_stale_or_terminal_order_canceled(self):
        """Test order staleness check when order is canceled."""
        mock_client = Mock()
        mock_order = self.create_mock_order("order_123", "canceled")
        mock_client.get_order_by_id.return_value = mock_order
        
        result = is_order_stale_or_terminal(mock_client, "order_123", self.current_time)
        
        self.assertTrue(result, "Should return True when order is canceled")
    
    def test_is_order_stale_or_terminal_order_stale(self):
        """Test order staleness check when order is old and open."""
        mock_client = Mock()
        old_order_time = self.current_time - timedelta(minutes=10)  # 10 minutes old
        mock_order = self.create_mock_order("order_123", "new", old_order_time)
        mock_client.get_order_by_id.return_value = mock_order
        
        result = is_order_stale_or_terminal(mock_client, "order_123", self.current_time)
        
        self.assertTrue(result, "Should return True when order is stale")
    
    def test_is_order_stale_or_terminal_order_active_recent(self):
        """Test order staleness check when order is active and recent."""
        mock_client = Mock()
        recent_order_time = self.current_time - timedelta(minutes=2)  # 2 minutes old
        mock_order = self.create_mock_order("order_123", "new", recent_order_time)
        mock_client.get_order_by_id.return_value = mock_order
        
        result = is_order_stale_or_terminal(mock_client, "order_123", self.current_time)
        
        self.assertFalse(result, "Should return False when order is active and recent")
    
    @patch('consistency_checker.update_cycle')
    def test_process_stuck_buying_cycle_no_order_id(self, mock_update_cycle):
        """Test processing stuck buying cycle with no order ID."""
        mock_update_cycle.return_value = True
        mock_client = Mock()
        
        # Create cycle with no order ID
        cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='buying',
            latest_order_id=None
        )
        
        result = process_stuck_buying_cycle(mock_client, cycle, self.current_time)
        
        # Verify update was called
        mock_update_cycle.assert_called_once_with(20, {'status': 'watching', 'latest_order_id': None})
        self.assertTrue(result, "Should return True when cycle is updated")
    
    @patch('consistency_checker.update_cycle')
    @patch('consistency_checker.is_order_stale_or_terminal')
    def test_process_stuck_buying_cycle_stale_order(self, mock_is_stale, mock_update_cycle):
        """Test processing stuck buying cycle with stale order."""
        mock_is_stale.return_value = True
        mock_update_cycle.return_value = True
        mock_client = Mock()
        
        # Create cycle with stale order
        cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='buying',
            latest_order_id='stale_order_123'
        )
        
        result = process_stuck_buying_cycle(mock_client, cycle, self.current_time)
        
        # Verify checks and update
        mock_is_stale.assert_called_once_with(mock_client, 'stale_order_123', self.current_time)
        mock_update_cycle.assert_called_once_with(20, {'status': 'watching', 'latest_order_id': None})
        self.assertTrue(result, "Should return True when cycle is updated")
    
    @patch('consistency_checker.is_order_stale_or_terminal')
    def test_process_stuck_buying_cycle_active_order(self, mock_is_stale):
        """Test processing stuck buying cycle with active order."""
        mock_is_stale.return_value = False
        mock_client = Mock()
        
        # Create cycle with active order
        cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='buying',
            latest_order_id='active_order_123'
        )
        
        result = process_stuck_buying_cycle(mock_client, cycle, self.current_time)
        
        # Verify no update needed
        mock_is_stale.assert_called_once_with(mock_client, 'active_order_123', self.current_time)
        self.assertFalse(result, "Should return False when no update needed")
    
    def test_has_alpaca_position_position_exists(self):
        """Test position check when position exists."""
        mock_client = Mock()
        mock_position = self.create_mock_position("BTC/USD", "0.01")
        mock_client.get_open_position.return_value = mock_position
        
        result = has_alpaca_position(mock_client, "BTC/USD")
        
        self.assertTrue(result, "Should return True when position exists")
        mock_client.get_open_position.assert_called_once_with("BTC/USD")
    
    def test_has_alpaca_position_no_position(self):
        """Test position check when no position exists."""
        mock_client = Mock()
        mock_client.get_open_position.side_effect = APIError("Position not found")
        
        result = has_alpaca_position(mock_client, "BTC/USD")
        
        self.assertFalse(result, "Should return False when no position exists")
    
    def test_has_alpaca_position_zero_quantity(self):
        """Test position check when position has zero quantity."""
        mock_client = Mock()
        mock_position = self.create_mock_position("BTC/USD", "0")
        mock_client.get_open_position.return_value = mock_position
        
        result = has_alpaca_position(mock_client, "BTC/USD")
        
        self.assertFalse(result, "Should return False when position has zero quantity")
    
    @patch('consistency_checker.create_cycle')
    @patch('consistency_checker.update_cycle')
    @patch('consistency_checker.get_asset_config_by_id')
    @patch('consistency_checker.has_alpaca_position')
    def test_process_orphaned_watching_cycle_no_position(self, mock_has_position, mock_get_asset, 
                                                        mock_update_cycle, mock_create_cycle):
        """Test processing orphaned watching cycle with no Alpaca position."""
        # Setup mocks
        mock_has_position.return_value = False
        mock_update_cycle.return_value = True
        mock_create_cycle.return_value = 999  # New cycle ID
        
        asset_config = self.create_mock_asset(100, "BTC/USD")
        mock_get_asset.return_value = asset_config
        
        # Create watching cycle with quantity
        cycle = self.create_mock_cycle(
            cycle_id=50,
            asset_id=100,
            status='watching',
            quantity=Decimal('0.01')
        )
        
        mock_client = Mock()
        result = process_orphaned_watching_cycle(mock_client, cycle, self.current_time)
        
        # Verify all calls
        mock_get_asset.assert_called_once_with(100)
        mock_has_position.assert_called_once_with(mock_client, "BTC/USD")
        mock_update_cycle.assert_called_once_with(50, {'status': 'error', 'completed_at': self.current_time})
        mock_create_cycle.assert_called_once_with(
            asset_id=100,
            status='watching',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            last_order_fill_price=None
        )
        
        self.assertTrue(result, "Should return True when cycle is processed")
    
    @patch('consistency_checker.get_asset_config_by_id')
    @patch('consistency_checker.has_alpaca_position')
    def test_process_orphaned_watching_cycle_position_exists(self, mock_has_position, mock_get_asset):
        """Test processing orphaned watching cycle when Alpaca position exists."""
        # Setup mocks
        mock_has_position.return_value = True
        
        asset_config = self.create_mock_asset(100, "BTC/USD")
        mock_get_asset.return_value = asset_config
        
        # Create watching cycle with quantity
        cycle = self.create_mock_cycle(
            cycle_id=50,
            asset_id=100,
            status='watching',
            quantity=Decimal('0.01')
        )
        
        mock_client = Mock()
        result = process_orphaned_watching_cycle(mock_client, cycle, self.current_time)
        
        # Verify checks but no action
        mock_get_asset.assert_called_once_with(100)
        mock_has_position.assert_called_once_with(mock_client, "BTC/USD")
        
        self.assertFalse(result, "Should return False when no action needed")
    
    @patch('consistency_checker.get_asset_config_by_id')
    def test_process_orphaned_watching_cycle_no_asset_config(self, mock_get_asset):
        """Test processing orphaned watching cycle when asset config not found."""
        mock_get_asset.return_value = None
        
        # Create watching cycle with quantity
        cycle = self.create_mock_cycle(
            cycle_id=50,
            asset_id=100,
            status='watching',
            quantity=Decimal('0.01')
        )
        
        mock_client = Mock()
        result = process_orphaned_watching_cycle(mock_client, cycle, self.current_time)
        
        # Verify error handling
        mock_get_asset.assert_called_once_with(100)
        self.assertFalse(result, "Should return False when asset config not found")
    
    def test_get_current_utc_time(self):
        """Test UTC time generation."""
        current_time = get_current_utc_time()
        
        # Should be timezone-aware UTC time
        self.assertIsNotNone(current_time.tzinfo, "Should return timezone-aware datetime")
        self.assertEqual(current_time.tzinfo, timezone.utc, "Should be UTC timezone")
        
        # Should be recent (within last few seconds)
        now = datetime.now(timezone.utc)
        time_diff = abs((now - current_time).total_seconds())
        self.assertLess(time_diff, 5, "Should return current time within 5 seconds")


if __name__ == '__main__':
    unittest.main() 