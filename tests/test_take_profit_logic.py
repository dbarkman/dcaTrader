"""
Tests for Phase 6: Take-Profit Logic

This module tests the take-profit functionality that places market SELL orders
when an asset's price rises above the take-profit threshold based on the
cycle's average purchase price.
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


class TestTakeProfitConditions:
    """Test take-profit condition validation"""
    
    def setup_method(self):
        """Set up test data"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'BTC/USD'
        self.mock_quote.ask_price = 52000.0
        self.mock_quote.bid_price = 51950.0
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 1
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('1.0')  # 1%
        self.mock_asset_config.safety_order_deviation = Decimal('2.5')  # 2.5%
        self.mock_asset_config.max_safety_orders = 5
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 100
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0.5')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('50000.0')  # $50k average
        self.mock_cycle.safety_orders = 2
        self.mock_cycle.last_order_fill_price = Decimal('49000.0')

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    def test_take_profit_updates_database_on_order_placement(self, mock_update_cycle, mock_place_order, 
                                                           mock_get_position, mock_get_client, mock_get_cycle, mock_get_asset):
        """Test that database is updated when take-profit order is placed"""
        
        # Setup: All conditions met for take-profit
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock Alpaca position
        mock_position = Mock()
        mock_position.qty = '0.5'
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'sell_order_123'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = True
        
        # Execute
        with patch('main_app.recent_orders', {}):
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: Market sell order was placed
        mock_place_order.assert_called_once()
        
        # Verify: Database was updated with selling status
        mock_update_cycle.assert_called_once()
        cycle_id, updates = mock_update_cycle.call_args[0]
        
        assert cycle_id == self.mock_cycle.id
        assert updates['status'] == 'selling'
        assert updates['latest_order_id'] == 'sell_order_123'
        assert 'latest_order_created_at' in updates
        
        # Verify the timestamp is recent (within last 5 seconds)
        from datetime import datetime, timezone
        timestamp = updates['latest_order_created_at']
        now = datetime.now(timezone.utc)
        time_diff = (now - timestamp).total_seconds()
        assert time_diff < 5, f"Timestamp should be recent, but was {time_diff} seconds ago"

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    def test_take_profit_conditions_met(self, mock_update_cycle, mock_place_order, mock_get_position, mock_get_client, 
                                       mock_get_cycle, mock_get_asset):
        """Test that take-profit order is placed when all conditions are met"""
        
        # Setup: Price has risen above take-profit threshold
        # Average price: $50,000, take-profit: 1%, trigger: $50,500
        # Current bid: $51,950 > $50,500 ✓
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock Alpaca position
        mock_position = Mock()
        mock_position.qty = '0.5'
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'order_123'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = True
        
        # Execute
        with patch('main_app.recent_orders', {}):
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: Market sell order was placed
        mock_place_order.assert_called_once_with(
            client=mock_client,
            symbol='BTC/USD',
            qty=0.5,  # Full position quantity
            time_in_force='gtc'
        )

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_conditions_not_met_price_not_high_enough(self, mock_get_cycle, mock_get_asset):
        """Test that no order is placed when bid price is below take-profit threshold"""
        
        # Setup: Price below take-profit threshold
        # Average price: $50,000, take-profit: 1%, trigger: $50,500
        # Current bid: $50,000 < $50,500 ✗
        
        self.mock_quote.bid_price = 50000.0  # Below threshold
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No order was placed
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_skipped_when_safety_order_would_trigger(self, mock_get_cycle, mock_get_asset):
        """Test that take-profit is skipped when safety order conditions are met"""
        
        # Setup: Both take-profit AND safety order conditions met
        # Safety order triggers at: $49,000 * (1 - 2.5%) = $47,775
        # Ask price: $47,500 < $47,775 (safety order would trigger)
        # But bid price might be above take-profit trigger
        
        self.mock_quote.ask_price = 47500.0  # Would trigger safety order
        self.mock_quote.bid_price = 51000.0  # Would trigger take-profit
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No take-profit order placed (safety order takes precedence)
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_skipped_no_position(self, mock_get_cycle, mock_get_asset):
        """Test that take-profit is skipped when cycle has no position"""
        
        # Setup: No position (quantity = 0)
        self.mock_cycle.quantity = Decimal('0')
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No order was placed
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_skipped_wrong_status(self, mock_get_cycle, mock_get_asset):
        """Test that take-profit is skipped when cycle status is not 'watching'"""
        
        # Setup: Cycle in 'buying' status
        self.mock_cycle.status = 'buying'
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No order was placed
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_skipped_no_average_price(self, mock_get_cycle, mock_get_asset):
        """Test that take-profit is skipped when average_purchase_price is None"""
        
        # Setup: No average purchase price
        self.mock_cycle.average_purchase_price = None
        
        mock_get_asset.return_value = self.mock_asset_config
        mock_get_cycle.return_value = self.mock_cycle
        
        # Execute
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(self.mock_quote)
        
        # Verify: No order was placed
        mock_place_order.assert_not_called()


class TestTakeProfitCalculations:
    """Test take-profit price calculations"""
    
    @pytest.mark.unit
    def test_take_profit_trigger_price_calculation(self):
        """Test accurate calculation of take-profit trigger price"""
        
        test_cases = [
            # (avg_price, take_profit_percent, expected_trigger)
            (Decimal('50000'), Decimal('1.0'), Decimal('50500.0')),    # 1% of $50k = $50.5k
            (Decimal('25000'), Decimal('2.0'), Decimal('25500.0')),    # 2% of $25k = $25.5k
            (Decimal('100000'), Decimal('0.5'), Decimal('100500.0')),  # 0.5% of $100k = $100.5k
            (Decimal('3000'), Decimal('5.0'), Decimal('3150.0')),      # 5% of $3k = $3.15k
        ]
        
        for avg_price, take_profit_pct, expected_trigger in test_cases:
            # Calculate trigger price using the same formula as the code
            take_profit_percent_decimal = take_profit_pct / Decimal('100')
            calculated_trigger = avg_price * (Decimal('1') + take_profit_percent_decimal)
            
            assert calculated_trigger == expected_trigger, (
                f"Take-profit calculation failed for avg_price={avg_price}, "
                f"take_profit_percent={take_profit_pct}%. "
                f"Expected {expected_trigger}, got {calculated_trigger}"
            )

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    def test_take_profit_quantity_uses_full_position(self, mock_update_cycle, mock_place_order, mock_get_position, mock_get_client,
                                                    mock_get_cycle, mock_get_asset):
        """Test that take-profit sells the entire position quantity"""
        
        # Setup with specific position size
        mock_quote = Mock()
        mock_quote.symbol = 'ETH/USD'
        mock_quote.ask_price = 3900.0
        mock_quote.bid_price = 3850.0
        
        mock_asset_config = Mock()
        mock_asset_config.id = 2
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.5')
        mock_asset_config.safety_order_deviation = Decimal('2.0')
        mock_asset_config.max_safety_orders = 3
        
        mock_cycle = Mock()
        mock_cycle.id = 200  # Add explicit ID
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('2.75')  # Specific quantity
        mock_cycle.average_purchase_price = Decimal('3700.0')  # $3,700 avg
        mock_cycle.safety_orders = 1
        mock_cycle.last_order_fill_price = Decimal('3650.0')
        
        # Take-profit trigger: $3,700 * 1.015 = $3,755.50
        # Current bid: $3,850 > $3,755.50 ✓
        
        mock_get_asset.return_value = mock_asset_config
        mock_get_cycle.return_value = mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock Alpaca position with the expected quantity
        mock_position = Mock()
        mock_position.qty = '2.75'  # Match the expected quantity
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'order_456'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = True
        
        # Execute
        with patch('main_app.recent_orders', {}):
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: Sold entire position (2.75 ETH)
        mock_place_order.assert_called_once_with(
            client=mock_client,
            symbol='ETH/USD',
            qty=2.75,  # Full position quantity
            time_in_force='gtc'
        )

    @pytest.mark.unit
    def test_safety_order_conflict_detection(self):
        """Test accurate detection of safety order conflicts"""
        
        # Test case: Safety order would trigger, should block take-profit
        last_fill_price = Decimal('49000')
        safety_deviation = Decimal('2.5')  # 2.5%
        safety_trigger = last_fill_price * (Decimal('1') - safety_deviation / Decimal('100'))
        
        # Expected: $49,000 * (1 - 0.025) = $49,000 * 0.975 = $47,775
        expected_safety_trigger = Decimal('47775.0')
        
        assert safety_trigger == expected_safety_trigger
        
        # If ask price is $47,500, it should trigger safety order
        ask_price = Decimal('47500')
        assert ask_price <= safety_trigger  # Safety order would trigger
        
        # If ask price is $48,000, it should NOT trigger safety order
        ask_price_high = Decimal('48000')
        assert ask_price_high > safety_trigger  # Safety order would NOT trigger


class TestTakeProfitErrorHandling:
    """Test error handling in take-profit logic"""
    
    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    def test_take_profit_handles_no_asset_config(self, mock_get_asset):
        """Test graceful handling when asset is not configured"""
        
        mock_quote = Mock()
        mock_quote.symbol = 'UNKNOWN/USD'
        
        mock_get_asset.return_value = None  # Asset not configured
        
        # Execute - should not raise exception
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: No order attempted
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    def test_take_profit_handles_no_cycle(self, mock_get_cycle, mock_get_asset):
        """Test graceful handling when no cycle exists"""
        
        mock_quote = Mock()
        mock_quote.symbol = 'BTC/USD'
        
        mock_asset_config = Mock()
        mock_asset_config.is_enabled = True
        mock_get_asset.return_value = mock_asset_config
        
        mock_get_cycle.return_value = None  # No cycle found
        
        # Execute - should not raise exception
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: No order attempted
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    def test_take_profit_handles_client_failure(self, mock_get_client, mock_get_cycle, mock_get_asset):
        """Test graceful handling when Alpaca client fails"""
        
        mock_quote = Mock()
        mock_quote.symbol = 'BTC/USD'
        mock_quote.bid_price = 52000.0
        
        mock_asset_config = Mock()
        mock_asset_config.id = 1
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.safety_order_deviation = Decimal('2.5')
        mock_asset_config.max_safety_orders = 5
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.5')
        mock_cycle.average_purchase_price = Decimal('50000.0')
        mock_cycle.safety_orders = 2
        mock_cycle.last_order_fill_price = Decimal('49000.0')
        
        mock_get_asset.return_value = mock_asset_config
        mock_get_cycle.return_value = mock_cycle
        mock_get_client.return_value = None  # Client initialization failed
        
        # Execute - should not raise exception
        with patch('main_app.place_market_sell_order') as mock_place_order:
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: No order attempted
        mock_place_order.assert_not_called()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    def test_take_profit_handles_order_failure(self, mock_place_order, mock_get_position, mock_get_client,
                                              mock_get_cycle, mock_get_asset):
        """Test graceful handling when order placement fails"""
        
        mock_quote = Mock()
        mock_quote.symbol = 'BTC/USD'
        mock_quote.ask_price = 52000.0  # Need to set ask_price for decimal conversion
        mock_quote.bid_price = 52000.0
        
        mock_asset_config = Mock()
        mock_asset_config.id = 1
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.safety_order_deviation = Decimal('2.5')
        mock_asset_config.max_safety_orders = 5
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.5')
        mock_cycle.average_purchase_price = Decimal('50000.0')
        mock_cycle.safety_orders = 2
        mock_cycle.last_order_fill_price = Decimal('49000.0')
        
        mock_get_asset.return_value = mock_asset_config
        mock_get_cycle.return_value = mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock position exists
        mock_position = Mock()
        mock_position.qty = '0.5'
        mock_get_position.return_value = mock_position
        
        mock_place_order.return_value = None  # Order placement failed
        
        # Execute - should not raise exception
        with patch('main_app.recent_orders', {}):
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: Order was attempted but failed gracefully
        mock_place_order.assert_called_once()

    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_alpaca_position_by_symbol')
    @patch('main_app.place_market_sell_order')
    @patch('main_app.update_cycle')
    @patch('main_app.logger')
    def test_take_profit_handles_database_update_failure(self, mock_logger, mock_update_cycle, mock_place_order,
                                                        mock_get_position, mock_get_client, mock_get_cycle, mock_get_asset):
        """Test graceful handling when database update fails after order placement"""
        
        mock_quote = Mock()
        mock_quote.symbol = 'BTC/USD'
        mock_quote.ask_price = 52000.0
        mock_quote.bid_price = 52000.0
        
        mock_asset_config = Mock()
        mock_asset_config.id = 1
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.safety_order_deviation = Decimal('2.5')
        mock_asset_config.max_safety_orders = 5
        
        mock_cycle = Mock()
        mock_cycle.id = 100
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.5')
        mock_cycle.average_purchase_price = Decimal('50000.0')
        mock_cycle.safety_orders = 2
        mock_cycle.last_order_fill_price = Decimal('49000.0')
        
        mock_get_asset.return_value = mock_asset_config
        mock_get_cycle.return_value = mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock position exists
        mock_position = Mock()
        mock_position.qty = '0.5'
        mock_get_position.return_value = mock_position
        
        mock_order = Mock()
        mock_order.id = 'sell_order_456'
        mock_place_order.return_value = mock_order
        mock_update_cycle.return_value = False  # Database update fails
        
        # Execute - should not raise exception
        with patch('main_app.recent_orders', {}):
            check_and_place_take_profit_order(mock_quote)
        
        # Verify: Order was placed successfully
        mock_place_order.assert_called_once()
        
        # Verify: Database update was attempted
        mock_update_cycle.assert_called_once()
        
        # Verify: Error was logged when database update failed
        error_logged = any(
            call for call in mock_logger.error.call_args_list
            if 'Failed to update cycle' in str(call) and 'sell_order_456' in str(call)
        )
        assert error_logged, "Should log error when database update fails"


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 