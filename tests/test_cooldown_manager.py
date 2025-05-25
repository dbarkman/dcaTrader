#!/usr/bin/env python3
"""
Unit Tests for Cooldown Manager Caretaker Script

Tests the cooldown_manager.py functionality for managing cooldown period expiration
and transitioning cycles from 'cooldown' to 'watching' status.
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone, timedelta
import sys
import os

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'scripts'))

# Import the cooldown manager functions
from cooldown_manager import (
    get_cooldown_cycles,
    get_previous_completed_cycle,
    is_cooldown_expired,
    process_cooldown_cycle,
    get_current_utc_time
)

# Import models for testing
from models.cycle_data import DcaCycle
from models.asset_config import DcaAsset


class TestCooldownManager(unittest.TestCase):
    """Test cases for cooldown manager functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.current_time = datetime.now(timezone.utc)
        self.old_time = self.current_time - timedelta(minutes=10)  # 10 minutes ago
        self.recent_time = self.current_time - timedelta(minutes=2)  # 2 minutes ago
        
    def create_mock_cycle(self, cycle_id, asset_id, status, created_at=None, completed_at=None):
        """Create a mock DcaCycle object."""
        cycle = Mock(spec=DcaCycle)
        cycle.id = cycle_id
        cycle.asset_id = asset_id
        cycle.status = status
        cycle.created_at = created_at or self.current_time
        cycle.completed_at = completed_at
        cycle.quantity = 0.0
        cycle.average_purchase_price = 0.0
        cycle.safety_orders = 0
        cycle.latest_order_id = None
        cycle.last_order_fill_price = None
        return cycle
    
    def create_mock_asset(self, asset_id, symbol, cooldown_period):
        """Create a mock DcaAsset object."""
        asset = Mock(spec=DcaAsset)
        asset.id = asset_id
        asset.asset_symbol = symbol
        asset.cooldown_period = cooldown_period
        asset.enabled = True
        asset.base_order_amount = 100.0
        asset.safety_order_amount = 150.0
        asset.safety_order_deviation = 2.5
        asset.max_safety_orders = 3
        asset.take_profit_percentage = 1.0
        asset.last_sell_price = None
        return asset
    
    @patch('cooldown_manager.execute_query')
    def test_get_cooldown_cycles(self, mock_execute_query):
        """Test fetching cycles in cooldown status."""
        # Mock database response
        mock_execute_query.return_value = [
            {
                'id': 1,
                'asset_id': 100,
                'status': 'cooldown',
                'created_at': self.current_time,
                'updated_at': self.current_time,
                'completed_at': None,
                'quantity': 0.0,
                'average_purchase_price': 0.0,
                'safety_orders': 0,
                'latest_order_id': None,
                'last_order_fill_price': None
            },
            {
                'id': 2,
                'asset_id': 101,
                'status': 'cooldown',
                'created_at': self.recent_time,
                'updated_at': self.recent_time,
                'completed_at': None,
                'quantity': 0.0,
                'average_purchase_price': 0.0,
                'safety_orders': 0,
                'latest_order_id': None,
                'last_order_fill_price': None
            }
        ]
        
        cycles = get_cooldown_cycles()
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        self.assertIn("status = 'cooldown'", call_args[0][0])
        
        # Verify results
        self.assertEqual(len(cycles), 2, "Should return 2 cooldown cycles")
        self.assertEqual(cycles[0].id, 1, "First cycle should have ID 1")
        self.assertEqual(cycles[1].id, 2, "Second cycle should have ID 2")
    
    @patch('cooldown_manager.execute_query')
    def test_get_cooldown_cycles_empty_result(self, mock_execute_query):
        """Test handling of no cooldown cycles found."""
        mock_execute_query.return_value = []
        
        cycles = get_cooldown_cycles()
        
        self.assertEqual(cycles, [], "Should return empty list when no cooldown cycles found")
    
    @patch('cooldown_manager.execute_query')
    def test_get_previous_completed_cycle(self, mock_execute_query):
        """Test fetching previous completed cycle."""
        completed_time = self.current_time - timedelta(hours=1)
        
        # Mock database response
        mock_execute_query.return_value = {
            'id': 10,
            'asset_id': 100,
            'status': 'complete',
            'created_at': self.old_time,
            'updated_at': self.old_time,
            'completed_at': completed_time,
            'quantity': 0.01,
            'average_purchase_price': 50000.0,
            'safety_orders': 1,
            'latest_order_id': None,
            'last_order_fill_price': 51000.0
        }
        
        cooldown_created_at = self.current_time - timedelta(minutes=30)
        previous_cycle = get_previous_completed_cycle(100, cooldown_created_at)
        
        # Verify correct query was called
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        query = call_args[0][0]
        params = call_args[0][1]
        
        self.assertIn("status IN ('complete', 'error')", query)
        self.assertIn("completed_at IS NOT NULL", query)
        self.assertIn("created_at < %s", query)
        self.assertIn("ORDER BY completed_at DESC", query)
        self.assertIn("LIMIT 1", query)
        self.assertEqual(params, (100, cooldown_created_at))
        
        # Verify results
        self.assertIsNotNone(previous_cycle, "Should return a previous cycle")
        self.assertEqual(previous_cycle.id, 10, "Should return cycle with ID 10")
        self.assertEqual(previous_cycle.status, 'complete', "Should return completed cycle")
    
    @patch('cooldown_manager.execute_query')
    def test_get_previous_completed_cycle_not_found(self, mock_execute_query):
        """Test handling when no previous completed cycle is found."""
        mock_execute_query.return_value = None
        
        cooldown_created_at = self.current_time
        previous_cycle = get_previous_completed_cycle(100, cooldown_created_at)
        
        self.assertIsNone(previous_cycle, "Should return None when no previous cycle found")
    
    def test_cooldown_expired(self):
        """
        Test cooldown expiration detection.
        
        Mock 'cooldown' cycle, previous 'complete' cycle with completed_at, 
        asset config with cooldown_period. Current time is past expiry. 
        Assert update to 'watching' is triggered.
        """
        # Create mock previous cycle that completed 70 seconds ago
        completed_time = self.current_time - timedelta(seconds=70)
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=completed_time
        )
        
        # Create mock asset with 60-second cooldown period
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60  # 60 seconds
        )
        
        # Test cooldown expiration
        expired = is_cooldown_expired(previous_cycle, asset_config, self.current_time)
        
        # Should be expired (70 seconds > 60 seconds)
        self.assertTrue(expired, "Cooldown should be expired when current time > expiry time")
    
    def test_cooldown_not_expired(self):
        """
        Test cooldown not yet expired.
        
        Same setup as test_cooldown_expired, but current time is before expiry. 
        Assert no update.
        """
        # Create mock previous cycle that completed 30 seconds ago
        completed_time = self.current_time - timedelta(seconds=30)
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=completed_time
        )
        
        # Create mock asset with 60-second cooldown period
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60  # 60 seconds
        )
        
        # Test cooldown expiration
        expired = is_cooldown_expired(previous_cycle, asset_config, self.current_time)
        
        # Should NOT be expired (30 seconds < 60 seconds)
        self.assertFalse(expired, "Cooldown should not be expired when current time < expiry time")
    
    def test_cooldown_no_valid_previous_cycle(self):
        """
        Test handling when no valid previous cycle exists.
        
        Mock 'cooldown' cycle, but no suitable previous 'complete' cycle. 
        Assert no update.
        """
        # Create mock previous cycle with no completed_at timestamp
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=None  # No completion timestamp
        )
        
        # Create mock asset
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60
        )
        
        # Test cooldown expiration
        expired = is_cooldown_expired(previous_cycle, asset_config, self.current_time)
        
        # Should NOT be expired due to missing completed_at
        self.assertFalse(expired, "Cooldown should not be expired when previous cycle has no completed_at")
    
    def test_cooldown_exact_expiry_time(self):
        """Test cooldown expiration at exact expiry time."""
        # Create mock previous cycle that completed exactly 60 seconds ago
        completed_time = self.current_time - timedelta(seconds=60)
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=completed_time
        )
        
        # Create mock asset with 60-second cooldown period
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60
        )
        
        # Test cooldown expiration
        expired = is_cooldown_expired(previous_cycle, asset_config, self.current_time)
        
        # Should be expired (current_time >= expiry_time)
        self.assertTrue(expired, "Cooldown should be expired at exact expiry time")
    
    @patch('cooldown_manager.get_asset_config_by_id')
    @patch('cooldown_manager.get_previous_completed_cycle')
    @patch('cooldown_manager.update_cycle')
    def test_process_cooldown_cycle_success(self, mock_update_cycle, 
                                          mock_get_previous_cycle, mock_get_asset_config_by_id):
        """Test successful processing of an expired cooldown cycle."""
        # Setup mocks
        mock_update_cycle.return_value = True
        
        # Create mock cooldown cycle
        cooldown_cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='cooldown',
            created_at=self.current_time - timedelta(minutes=5)
        )
        
        # Create mock asset config
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60
        )
        mock_get_asset_config_by_id.return_value = asset_config
        
        # Create mock previous completed cycle (expired)
        completed_time = self.current_time - timedelta(seconds=70)
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=completed_time
        )
        mock_get_previous_cycle.return_value = previous_cycle
        
        # Test processing
        result = process_cooldown_cycle(cooldown_cycle, self.current_time)
        
        # Verify calls
        mock_get_asset_config_by_id.assert_called_once_with(100)
        mock_get_previous_cycle.assert_called_once_with(100, cooldown_cycle.created_at)
        mock_update_cycle.assert_called_once_with(20, {'status': 'watching'})
        
        # Should return True for successful update
        self.assertTrue(result, "Should return True when cycle is successfully updated")
    
    @patch('cooldown_manager.get_asset_config_by_id')
    @patch('cooldown_manager.get_previous_completed_cycle')
    def test_process_cooldown_cycle_not_expired(self, mock_get_previous_cycle, mock_get_asset_config_by_id):
        """Test processing of a cooldown cycle that hasn't expired yet."""
        # Create mock cooldown cycle
        cooldown_cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='cooldown'
        )
        
        # Create mock asset config
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60
        )
        mock_get_asset_config_by_id.return_value = asset_config
        
        # Create mock previous completed cycle (not yet expired)
        completed_time = self.current_time - timedelta(seconds=30)
        previous_cycle = self.create_mock_cycle(
            cycle_id=10,
            asset_id=100,
            status='complete',
            completed_at=completed_time
        )
        mock_get_previous_cycle.return_value = previous_cycle
        
        # Test processing
        result = process_cooldown_cycle(cooldown_cycle, self.current_time)
        
        # Should return False (no update needed)
        self.assertFalse(result, "Should return False when cooldown has not expired")
    
    @patch('cooldown_manager.get_asset_config_by_id')
    def test_process_cooldown_cycle_no_asset_config(self, mock_get_asset_config_by_id):
        """Test processing when asset configuration is not found."""
        mock_get_asset_config_by_id.return_value = None
        
        # Create mock cooldown cycle
        cooldown_cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='cooldown'
        )
        
        # Test processing
        result = process_cooldown_cycle(cooldown_cycle, self.current_time)
        
        # Should return False due to missing asset config
        self.assertFalse(result, "Should return False when asset configuration is not found")
    
    @patch('cooldown_manager.get_asset_config_by_id')
    @patch('cooldown_manager.get_previous_completed_cycle')
    def test_process_cooldown_cycle_no_previous_cycle(self, mock_get_previous_cycle, mock_get_asset_config_by_id):
        """Test processing when no previous completed cycle is found."""
        # Create mock asset config
        asset_config = self.create_mock_asset(
            asset_id=100,
            symbol='BTC/USD',
            cooldown_period=60
        )
        mock_get_asset_config_by_id.return_value = asset_config
        mock_get_previous_cycle.return_value = None
        
        # Create mock cooldown cycle
        cooldown_cycle = self.create_mock_cycle(
            cycle_id=20,
            asset_id=100,
            status='cooldown'
        )
        
        # Test processing
        result = process_cooldown_cycle(cooldown_cycle, self.current_time)
        
        # Should return False due to missing previous cycle
        self.assertFalse(result, "Should return False when no previous completed cycle is found")
    
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