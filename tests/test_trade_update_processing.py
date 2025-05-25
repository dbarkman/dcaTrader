"""
Tests for Phase 7: TradingStream BUY Fill Processing

This module tests the trade update processing functionality that updates
dca_cycles when BUY orders (base or safety) are filled.
"""

import pytest
import logging
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime

# Add src to path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import update_cycle_on_buy_fill


class TestBuyFillProcessing:
    """Test BUY order fill processing and cycle updates"""
    
    def setup_method(self):
        """Set up test data"""
        self.mock_order = Mock()
        self.mock_order.id = 'test_order_123'
        self.mock_order.symbol = 'BTC/USD'
        self.mock_order.side = 'buy'
        self.mock_order.filled_qty = '0.001'
        self.mock_order.filled_avg_price = '50000.00'
        
        self.mock_trade_update = Mock()
        self.mock_trade_update.event = 'fill'
        self.mock_trade_update.order = self.mock_order
    
    @pytest.mark.unit
    @pytest.mark.asyncio
    @patch('main_app.execute_query')
    @patch('main_app.update_cycle')
    @patch('main_app.logger')
    async def test_buy_fill_updates_cycle_base_order(self, mock_logger, mock_update_cycle, mock_execute_query):
        """Test that a base order fill correctly updates the cycle"""
        
        # Mock cycle lookup by latest_order_id
        mock_cycle_data = {
            'id': 1,
            'asset_id': 1,
            'status': 'buying',
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'latest_order_id': 'test_order_123',
            'latest_order_created_at': datetime.now(),
            'last_order_fill_price': None,
            'completed_at': None,
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        # Mock asset config lookup
        mock_asset_data = {
            'asset_symbol': 'BTC/USD',
            'take_profit_percent': Decimal('1.0')
        }
        
        # Configure execute_query to return cycle then asset data
        mock_execute_query.side_effect = [mock_cycle_data, mock_asset_data]
        mock_update_cycle.return_value = True
        
        # Execute the function
        await update_cycle_on_buy_fill(self.mock_order, self.mock_trade_update)
        
        # Verify cycle was found by latest_order_id
        assert mock_execute_query.call_count == 2
        cycle_query_call = mock_execute_query.call_args_list[0]
        assert 'latest_order_id = %s' in cycle_query_call[0][0]
        assert cycle_query_call[0][1] == ('test_order_123',)
        
        # Verify update_cycle was called with correct values
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == 1
        assert updates['quantity'] == Decimal('0.001')  # filled_qty
        assert updates['average_purchase_price'] == Decimal('50000.00')  # First purchase = fill price
        assert updates['last_order_fill_price'] == Decimal('50000.00')
        assert updates['status'] == 'watching'
        assert updates['latest_order_id'] is None
        assert 'safety_orders' not in updates  # Base order doesn't increment safety_orders
    
    @pytest.mark.unit
    def test_average_purchase_price_recalculation_logic(self):
        """Test the weighted average purchase price calculation logic independently"""
        
        # Test case 1: First purchase (base order)
        current_qty = Decimal('0')
        current_avg_price = Decimal('0')
        fill_qty = Decimal('0.001')
        fill_price = Decimal('50000.00')
        
        new_total_qty = current_qty + fill_qty
        if current_qty == 0:
            new_avg_price = fill_price
        else:
            total_cost = (current_avg_price * current_qty) + (fill_price * fill_qty)
            new_avg_price = total_cost / new_total_qty
        
        assert new_avg_price == Decimal('50000.00')
        
        # Test case 2: Safety order (weighted average)
        current_qty = Decimal('0.001')
        current_avg_price = Decimal('50000.00')
        fill_qty = Decimal('0.0015')
        fill_price = Decimal('48000.00')
        
        new_total_qty = current_qty + fill_qty
        total_cost = (current_avg_price * current_qty) + (fill_price * fill_qty)
        new_avg_price = total_cost / new_total_qty
        
        # (50000 * 0.001) + (48000 * 0.0015) = 50 + 72 = 122
        # 122 / 0.0025 = 48800
        expected_avg = Decimal('48800.00')
        assert new_avg_price == expected_avg


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 