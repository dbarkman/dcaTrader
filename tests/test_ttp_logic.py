"""
Tests for Trailing Take Profit (TTP) Logic

This module tests the TTP functionality that activates trailing take-profit
when the initial profit target is met, tracks the highest price, and triggers
a sell when the price deviates from the peak.
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

from main_app import check_and_place_take_profit_order


class TestTTPActivation:
    """Test TTP activation logic"""
    
    def setup_method(self):
        """Set up test data"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'BTC/USD'
        self.mock_quote.ask_price = 101500.0  # Above take-profit trigger
        self.mock_quote.bid_price = 101500.0  # Above take-profit trigger
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 1
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('1.0')  # 1%
        self.mock_asset_config.ttp_enabled = True  # TTP enabled
        self.mock_asset_config.ttp_deviation_percent = Decimal('0.5')  # 0.5%
        self.mock_asset_config.safety_order_deviation = Decimal('2.5')
        self.mock_asset_config.max_safety_orders = 5
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 100
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'  # Ready for TTP activation
        self.mock_cycle.quantity = Decimal('0.01')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('100000.0')  # $100k average
        self.mock_cycle.highest_trailing_price = None  # Not yet set
        self.mock_cycle.safety_orders = 2
        self.mock_cycle.last_order_fill_price = Decimal('99000.0')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.update_cycle')
    @patch('main_app.recent_orders', {})
    def test_ttp_activation(self, mock_update_cycle, mock_get_cycle, mock_get_asset):
        """Test TTP activation when price hits take_profit_percent"""
        
        # Setup: TTP enabled, cycle 'watching', price hits 1% gain
        # Take-profit trigger: $100,000 * 1.01 = $101,000
        # Current bid: $101,500 > $101,000 ✓ SHOULD ACTIVATE TTP
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_update_cycle.return_value = True
        
        # Execute
        check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: Cycle status updated to 'trailing' and highest_trailing_price set
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == self.mock_cycle.id
        assert updates['status'] == 'trailing'
        assert updates['highest_trailing_price'] == Decimal('101500.0')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.recent_orders', {})
    def test_ttp_activation_no_sell_order_placed(self, mock_place_order, mock_get_cycle, mock_get_asset):
        """Test that no sell order is placed during TTP activation"""
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.update_cycle', return_value=True):
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No sell order was placed during activation
        mock_place_order.assert_not_called()


class TestTTPNewPeakUpdate:
    """Test TTP new peak tracking"""
    
    def setup_method(self):
        """Set up test data for trailing cycle"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'ETH/USD'
        self.mock_quote.ask_price = 3200.0  # New peak
        self.mock_quote.bid_price = 3200.0  # New peak
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 2
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('1.5')  # 1.5%
        self.mock_asset_config.ttp_enabled = True
        self.mock_asset_config.ttp_deviation_percent = Decimal('0.8')  # 0.8%
        self.mock_asset_config.safety_order_deviation = Decimal('2.0')
        self.mock_asset_config.max_safety_orders = 3
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 200
        self.mock_cycle.asset_id = 2
        self.mock_cycle.status = 'trailing'  # TTP already active
        self.mock_cycle.quantity = Decimal('1.0')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('3000.0')  # $3k average
        self.mock_cycle.highest_trailing_price = Decimal('3150.0')  # Previous peak
        self.mock_cycle.safety_orders = 1
        self.mock_cycle.last_order_fill_price = Decimal('2950.0')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.update_cycle')
    @patch('main_app.recent_orders', {})
    def test_ttp_new_peak_update(self, mock_update_cycle, mock_get_cycle, mock_get_asset):
        """Test TTP new peak update when price exceeds highest_trailing_price"""
        
        # Setup: TTP active, current bid ($3,200) > previous peak ($3,150)
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_update_cycle.return_value = True
        
        # Execute
        check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: highest_trailing_price updated to new peak
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == self.mock_cycle.id
        assert updates['highest_trailing_price'] == Decimal('3200.0')
        assert 'status' not in updates  # Status should remain 'trailing'

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.recent_orders', {})
    def test_ttp_new_peak_no_sell_order_placed(self, mock_place_order, mock_get_cycle, mock_get_asset):
        """Test that no sell order is placed when updating peak"""
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.update_cycle', return_value=True):
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No sell order was placed during peak update
        mock_place_order.assert_not_called()


class TestTTPSellTrigger:
    """Test TTP sell trigger logic"""
    
    def setup_method(self):
        """Set up test data for TTP sell trigger"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'SOL/USD'
        self.mock_quote.ask_price = 195.0  # Below sell trigger
        self.mock_quote.bid_price = 195.0  # Below sell trigger
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 3
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('2.0')  # 2%
        self.mock_asset_config.ttp_enabled = True
        self.mock_asset_config.ttp_deviation_percent = Decimal('1.0')  # 1%
        self.mock_asset_config.safety_order_deviation = Decimal('3.0')
        self.mock_asset_config.max_safety_orders = 4
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 300
        self.mock_cycle.asset_id = 3
        self.mock_cycle.status = 'trailing'  # TTP active
        self.mock_cycle.quantity = Decimal('5.0')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('180.0')  # $180 average
        self.mock_cycle.highest_trailing_price = Decimal('200.0')  # Peak at $200
        self.mock_cycle.safety_orders = 0
        self.mock_cycle.last_order_fill_price = Decimal('175.0')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    @patch('main_app.recent_orders', {})
    def test_ttp_sell_trigger(self, mock_update_cycle, mock_place_order, mock_get_position, 
                             mock_get_client, mock_get_cycle, mock_get_asset):
        """Test TTP sell trigger when price drops below deviation threshold"""
        
        # Setup: TTP active, peak $200, deviation 1%, sell trigger $198
        # Current bid: $195 < $198 ✓ SHOULD TRIGGER SELL
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock Alpaca position
        mock_position = Mock()
        mock_position.qty = '5.0'
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'ttp_sell_order_123'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = True
        
        # Execute
        check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: Market sell order was placed
        mock_place_order.assert_called_once_with(
            client=mock_client,
            symbol='SOL/USD',
            qty=5.0,  # Full position quantity
            time_in_force='gtc'
        )
        
        # Verify: Database was updated with selling status
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == self.mock_cycle.id
        assert updates['status'] == 'selling'
        assert updates['latest_order_id'] == 'ttp_sell_order_123'
        assert 'latest_order_created_at' in updates

    @pytest.mark.unit
    def test_ttp_sell_trigger_calculation(self):
        """Test TTP sell trigger price calculation"""
        
        # Test case: Peak $200, deviation 1%
        peak_price = Decimal('200.0')
        deviation_percent = Decimal('1.0')
        
        deviation_decimal = deviation_percent / Decimal('100')  # 0.01
        sell_trigger = peak_price * (Decimal('1') - deviation_decimal)
        
        # Expected: $200 * (1 - 0.01) = $200 * 0.99 = $198
        expected_trigger = Decimal('198.0')
        
        assert sell_trigger == expected_trigger
        
        # Test different values
        peak_price_2 = Decimal('150.0')
        deviation_percent_2 = Decimal('0.5')  # 0.5%
        
        deviation_decimal_2 = deviation_percent_2 / Decimal('100')  # 0.005
        sell_trigger_2 = peak_price_2 * (Decimal('1') - deviation_decimal_2)
        
        # Expected: $150 * (1 - 0.005) = $150 * 0.995 = $149.25
        expected_trigger_2 = Decimal('149.25')
        
        assert sell_trigger_2 == expected_trigger_2


class TestTTPDisabledUsesStandardTP:
    """Test that TTP disabled uses standard take-profit logic"""
    
    def setup_method(self):
        """Set up test data for standard take-profit"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'DOGE/USD'
        self.mock_quote.ask_price = 0.08  # Above take-profit trigger
        self.mock_quote.bid_price = 0.08  # Above take-profit trigger
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 4
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('2.5')  # 2.5%
        self.mock_asset_config.ttp_enabled = False  # TTP disabled
        self.mock_asset_config.ttp_deviation_percent = Decimal('1.0')  # Should be ignored
        self.mock_asset_config.safety_order_deviation = Decimal('5.0')
        self.mock_asset_config.max_safety_orders = 10
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 400
        self.mock_cycle.asset_id = 4
        self.mock_cycle.status = 'watching'  # Standard status
        self.mock_cycle.quantity = Decimal('1000.0')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('0.075')  # $0.075 average
        self.mock_cycle.highest_trailing_price = None  # Should remain None
        self.mock_cycle.safety_orders = 3
        self.mock_cycle.last_order_fill_price = Decimal('0.070')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    @patch('main_app.recent_orders', {})
    def test_ttp_disabled_uses_standard_tp(self, mock_update_cycle, mock_place_order, mock_get_position,
                                          mock_get_client, mock_get_cycle, mock_get_asset):
        """Test that standard take-profit SELL order is placed when TTP is disabled"""
        
        # Setup: TTP disabled, price above standard take-profit threshold
        # Take-profit trigger: $0.075 * 1.025 = $0.076875
        # Current bid: $0.08 > $0.076875 ✓ SHOULD TRIGGER STANDARD TP
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock Alpaca position
        mock_position = Mock()
        mock_position.qty = '1000.0'
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'standard_tp_order_456'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = True
        
        # Execute
        check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: Standard market sell order was placed
        mock_place_order.assert_called_once_with(
            client=mock_client,
            symbol='DOGE/USD',
            qty=1000.0,  # Full position quantity
            time_in_force='gtc'
        )
        
        # Verify: Database was updated with selling status (standard TP behavior)
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == self.mock_cycle.id
        assert updates['status'] == 'selling'
        assert updates['latest_order_id'] == 'standard_tp_order_456'
        assert 'latest_order_created_at' in updates

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.update_cycle')
    @patch('main_app.recent_orders', {})
    def test_ttp_disabled_no_trailing_status_change(self, mock_update_cycle, mock_get_cycle, mock_get_asset):
        """Test that cycle status never changes to 'trailing' when TTP is disabled"""
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute with various price levels
        with patch('main_app.get_trading_client', return_value=None):  # Force early return
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: update_cycle was never called to set 'trailing' status
        # (It should only be called for 'selling' status if order placement succeeds)
        for call in mock_update_cycle.call_args_list:
            if call:
                cycle_id, updates = call[0]
                assert updates.get('status') != 'trailing'


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 