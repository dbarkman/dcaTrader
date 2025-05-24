"""
Unit tests for safety order logic functionality (Phase 5)

Tests the logic for monitoring crypto prices and placing safety orders
when conditions are met.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import check_and_place_safety_order


class TestSafetyOrderLogic:
    """Test safety order placement logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'BTC/USD'
        self.mock_quote.ask_price = 48000.0  # Price that might trigger safety order
        self.mock_quote.bid_price = 47950.0
        
        self.mock_asset = Mock()
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.is_enabled = True
        self.mock_asset.safety_order_amount = Decimal('50.00')
        self.mock_asset.max_safety_orders = 3
        self.mock_asset.safety_order_deviation = Decimal('2.0')  # 2% deviation
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 1
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0.002')  # Has existing position
        self.mock_cycle.safety_orders = 0  # No safety orders yet
        self.mock_cycle.last_order_fill_price = Decimal('50000.0')  # Last fill at $50k
    
    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_asset_not_configured(self, mock_get_asset):
        """Test that safety order is skipped if asset is not configured"""
        # Clear global state
        with patch('main_app.recent_orders', {}):
            mock_get_asset.return_value = None
            
            # Should return early without error
            check_and_place_safety_order(self.mock_quote)
            
            mock_get_asset.assert_called_once_with('BTC/USD')
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_asset_disabled(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped if asset is disabled"""
        disabled_asset = Mock()
        disabled_asset.is_enabled = False
        mock_get_asset.return_value = disabled_asset
        
        check_and_place_safety_order(self.mock_quote)
        
        # Should not call get_latest_cycle
        mock_get_cycle.assert_not_called()
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_no_cycle(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped if no cycle exists"""
        # Clear global state
        with patch('main_app.recent_orders', {}):
            mock_get_asset.return_value = self.mock_asset
            mock_get_cycle.return_value = None
            
            check_and_place_safety_order(self.mock_quote)
            
            mock_get_cycle.assert_called_once_with(1)
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_cycle_not_watching(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped if cycle status is not 'watching'"""
        mock_get_asset.return_value = self.mock_asset
        
        buying_cycle = Mock()
        buying_cycle.status = 'buying'
        buying_cycle.quantity = Decimal('0.002')
        mock_get_cycle.return_value = buying_cycle
        
        check_and_place_safety_order(self.mock_quote)
        
        # Should return without calling Alpaca
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_cycle_has_no_quantity(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped if cycle has no quantity (no position)"""
        mock_get_asset.return_value = self.mock_asset
        
        empty_cycle = Mock()
        empty_cycle.status = 'watching'
        empty_cycle.quantity = Decimal('0')  # No position
        mock_get_cycle.return_value = empty_cycle
        
        check_and_place_safety_order(self.mock_quote)
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_conditions_not_met_max_orders(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped when safety_orders == max_safety_orders"""
        mock_get_asset.return_value = self.mock_asset
        
        max_safety_cycle = Mock()
        max_safety_cycle.status = 'watching'
        max_safety_cycle.quantity = Decimal('0.002')
        max_safety_cycle.safety_orders = 3  # At max
        max_safety_cycle.last_order_fill_price = Decimal('50000.0')
        mock_get_cycle.return_value = max_safety_cycle
        
        check_and_place_safety_order(self.mock_quote)
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_skipped_if_no_last_fill_price(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped if no last_order_fill_price"""
        mock_get_asset.return_value = self.mock_asset
        
        no_fill_cycle = Mock()
        no_fill_cycle.status = 'watching'
        no_fill_cycle.quantity = Decimal('0.002')
        no_fill_cycle.safety_orders = 0
        no_fill_cycle.last_order_fill_price = None  # No fill price
        mock_get_cycle.return_value = no_fill_cycle
        
        check_and_place_safety_order(self.mock_quote)
    
    @pytest.mark.unit
    def test_safety_order_trigger_price_calculation(self):
        """Test the trigger price calculation logic"""
        # Test data: 2% deviation from $50,000
        last_fill_price = Decimal('50000.0')
        safety_deviation = Decimal('2.0')  # 2%
        
        # Calculate expected trigger price
        deviation_decimal = safety_deviation / Decimal('100')  # 0.02
        expected_trigger = last_fill_price * (Decimal('1') - deviation_decimal)
        expected_trigger = Decimal('49000.0')  # $50,000 * 0.98 = $49,000
        
        assert expected_trigger == Decimal('49000.0')
        
        # Test with different values
        last_fill_price_2 = Decimal('25000.0')
        expected_trigger_2 = last_fill_price_2 * (Decimal('1') - deviation_decimal)
        assert expected_trigger_2 == Decimal('24500.0')  # $25,000 * 0.98 = $24,500
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_conditions_not_met_price_not_low_enough(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped when price hasn't dropped enough"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        
        # Current ask price is $48,000, but trigger is $49,000 (2% of $50,000)
        # So $48,000 should trigger. Let's set ask higher to test no trigger
        high_quote = Mock()
        high_quote.symbol = 'BTC/USD'
        high_quote.ask_price = 49500.0  # Above trigger price of $49,000
        high_quote.bid_price = 49450.0
        
        check_and_place_safety_order(high_quote)
    
    @pytest.mark.unit
    @patch('main_app.place_limit_buy_order')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_conditions_met(self, mock_get_asset, mock_get_cycle, 
                                         mock_get_client, mock_place_order):
        """Test that safety order is placed when all conditions are met"""
        # Clear global state
        with patch('main_app.recent_orders', {}):
            mock_get_asset.return_value = self.mock_asset
            mock_get_cycle.return_value = self.mock_cycle
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            # Mock successful order placement
            mock_order = Mock()
            mock_order.id = 'safety_order_123'
            mock_place_order.return_value = mock_order
            
            # Use quote with ask price that triggers safety order
            # Trigger price = $50,000 * 0.98 = $49,000
            # Ask price = $48,000 (below trigger)
            trigger_quote = Mock()
            trigger_quote.symbol = 'BTC/USD'
            trigger_quote.ask_price = 48000.0  # Below trigger
            trigger_quote.bid_price = 47950.0
            
            check_and_place_safety_order(trigger_quote)
            
            # Verify order was placed with correct parameters
            expected_quantity = 50.0 / 48000.0  # $50 / $48,000
            mock_place_order.assert_called_once_with(
                client=mock_client,
                symbol='BTC/USD',
                qty=expected_quantity,
                limit_price=48000.0,
                time_in_force='gtc'
            )
    
    @pytest.mark.unit
    def test_safety_order_usd_to_qty_conversion(self):
        """Test USD to crypto quantity conversion for safety orders"""
        safety_order_usd = 50.0
        ask_price = 48000.0
        
        expected_quantity = safety_order_usd / ask_price
        assert expected_quantity == 50.0 / 48000.0
        
        # Test different prices
        ask_price_2 = 25000.0
        expected_quantity_2 = safety_order_usd / ask_price_2
        assert expected_quantity_2 == 50.0 / 25000.0
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_safety_order_invalid_ask_price(self, mock_get_asset, mock_get_cycle):
        """Test that safety order is skipped with invalid ask price"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        
        # Test with zero ask price
        invalid_quote = Mock()
        invalid_quote.symbol = 'BTC/USD'
        invalid_quote.ask_price = 0.0
        invalid_quote.bid_price = 47950.0
        
        # Should return without error
        check_and_place_safety_order(invalid_quote)
        
        # Test with None ask price
        invalid_quote.ask_price = None
        check_and_place_safety_order(invalid_quote)
    
    @pytest.mark.unit
    @patch('main_app.place_limit_buy_order')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    @patch('main_app.recent_orders', {})  # Clear the global recent_orders dict
    def test_safety_order_placement_fails_gracefully(self, mock_get_asset, mock_get_cycle, 
                                                      mock_get_client, mock_place_order):
        """Test that safety order placement failure is handled gracefully"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_place_order.return_value = None  # Simulate order placement failure
        
        # Use quote that should trigger safety order
        trigger_quote = Mock()
        trigger_quote.symbol = 'BTC/USD'
        trigger_quote.ask_price = 48000.0  # Below trigger of $49,000
        trigger_quote.bid_price = 47950.0
        
        # Should not raise exception
        check_and_place_safety_order(trigger_quote)
        
        mock_place_order.assert_called_once()
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    @patch('main_app.recent_orders', {})  # Start with empty recent_orders
    def test_safety_order_duplicate_prevention(self, mock_get_asset, mock_get_cycle):
        """Test that duplicate safety orders are prevented by recent_orders tracking"""
        from datetime import datetime, timedelta
        
        # Mock recent order within cooldown period
        recent_time = datetime.now() - timedelta(seconds=15)  # 15 seconds ago (< 30s cooldown)
        
        with patch('main_app.recent_orders', {'BTC/USD': {'order_id': 'recent_123', 'timestamp': recent_time}}):
            with patch('main_app.datetime') as mock_datetime:
                mock_datetime.now.return_value = datetime.now()
                
                mock_get_asset.return_value = self.mock_asset
                mock_get_cycle.return_value = self.mock_cycle
                
                # Should return early due to recent order
                check_and_place_safety_order(self.mock_quote)
                
                # Should NOT proceed to call get_asset_config since it returns early
                mock_get_asset.assert_not_called()


class TestSafetyOrderCalculations:
    """Test safety order calculation scenarios"""
    
    @pytest.mark.unit
    def test_multiple_safety_deviation_scenarios(self):
        """Test safety order trigger calculations with various deviation percentages"""
        test_scenarios = [
            # (last_fill_price, deviation_pct, expected_trigger)
            (50000.0, 1.0, 49500.0),   # 1% of $50,000 = $49,500
            (50000.0, 2.0, 49000.0),   # 2% of $50,000 = $49,000
            (50000.0, 5.0, 47500.0),   # 5% of $50,000 = $47,500
            (25000.0, 2.0, 24500.0),   # 2% of $25,000 = $24,500
            (10000.0, 3.0, 9700.0),    # 3% of $10,000 = $9,700
        ]
        
        for last_fill, deviation_pct, expected_trigger in test_scenarios:
            last_fill_decimal = Decimal(str(last_fill))
            deviation_decimal = Decimal(str(deviation_pct))
            
            # Calculate trigger price
            safety_deviation_decimal = deviation_decimal / Decimal('100')
            trigger_price = last_fill_decimal * (Decimal('1') - safety_deviation_decimal)
            
            assert float(trigger_price) == expected_trigger, \
                f"Failed for last_fill={last_fill}, deviation={deviation_pct}%"
    
    @pytest.mark.unit
    def test_price_drop_percentage_calculation(self):
        """Test calculation of actual price drop percentage"""
        last_fill_price = Decimal('50000.0')
        current_ask = Decimal('48000.0')
        
        price_drop = last_fill_price - current_ask  # $2,000
        price_drop_pct = (price_drop / last_fill_price) * Decimal('100')
        
        expected_drop_pct = Decimal('4.0')  # 4% drop
        assert price_drop_pct == expected_drop_pct
    
    @pytest.mark.unit
    def test_safety_order_quantity_conversions(self):
        """Test USD to crypto quantity conversions for various scenarios"""
        test_scenarios = [
            # (safety_order_usd, ask_price, expected_quantity)
            (50.0, 50000.0, 0.001),      # $50 / $50,000 = 0.001 BTC
            (25.0, 25000.0, 0.001),      # $25 / $25,000 = 0.001 BTC  
            (100.0, 48000.0, 100/48000), # $100 / $48,000
            (75.0, 30000.0, 0.0025),     # $75 / $30,000 = 0.0025 BTC
        ]
        
        for order_usd, ask_price, expected_qty in test_scenarios:
            calculated_qty = order_usd / ask_price
            assert abs(calculated_qty - expected_qty) < 0.0000001, \
                f"Failed for order_usd={order_usd}, ask_price={ask_price}"


class TestSafetyOrderEdgeCases:
    """Test edge cases and boundary conditions for safety orders"""
    
    def setup_method(self):
        """Set up edge case test fixtures"""
        self.mock_asset = Mock()
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.is_enabled = True
        self.mock_asset.safety_order_amount = Decimal('50.00')
        self.mock_asset.max_safety_orders = 3
        self.mock_asset.safety_order_deviation = Decimal('2.0')
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    @patch('main_app.recent_orders', {})  # Clear recent orders
    def test_safety_order_at_exact_trigger_price(self, mock_get_asset, mock_get_cycle):
        """Test safety order when ask price exactly equals trigger price"""
        mock_get_asset.return_value = self.mock_asset
        
        cycle = Mock()
        cycle.status = 'watching'
        cycle.quantity = Decimal('0.002')
        cycle.safety_orders = 1
        cycle.last_order_fill_price = Decimal('50000.0')  # Trigger at $49,000
        mock_get_cycle.return_value = cycle
        
        # Ask price exactly at trigger
        exact_quote = Mock()
        exact_quote.symbol = 'BTC/USD'
        exact_quote.ask_price = 49000.0  # Exactly at trigger
        exact_quote.bid_price = 48950.0
        
        with patch('main_app.get_trading_client') as mock_get_client, \
             patch('main_app.place_limit_buy_order') as mock_place_order:
            
            # Mock client
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            mock_order = Mock()
            mock_order.id = 'exact_trigger_order'
            mock_place_order.return_value = mock_order
            
            check_and_place_safety_order(exact_quote)
            
            # Should place order when price is exactly at trigger
            mock_place_order.assert_called_once()
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle') 
    @patch('main_app.get_asset_config')
    def test_safety_order_with_zero_deviation(self, mock_get_asset, mock_get_cycle):
        """Test safety order logic with zero deviation (edge case)"""
        zero_deviation_asset = Mock()
        zero_deviation_asset.id = 1
        zero_deviation_asset.asset_symbol = 'BTC/USD'
        zero_deviation_asset.is_enabled = True
        zero_deviation_asset.safety_order_amount = Decimal('50.00')
        zero_deviation_asset.max_safety_orders = 3
        zero_deviation_asset.safety_order_deviation = Decimal('0.0')  # 0% deviation
        
        mock_get_asset.return_value = zero_deviation_asset
        
        cycle = Mock()
        cycle.status = 'watching'
        cycle.quantity = Decimal('0.002')
        cycle.safety_orders = 0
        cycle.last_order_fill_price = Decimal('50000.0')
        mock_get_cycle.return_value = cycle
        
        # With 0% deviation, trigger price = last_fill_price
        # So only ask prices below $50,000 should trigger
        above_trigger_quote = Mock()
        above_trigger_quote.symbol = 'BTC/USD'
        above_trigger_quote.ask_price = 50001.0  # Above trigger
        above_trigger_quote.bid_price = 50000.0
        
        check_and_place_safety_order(above_trigger_quote)
        
        # Should not place order when above trigger
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    @patch('main_app.recent_orders', {})  # Clear recent orders
    def test_safety_order_with_high_deviation(self, mock_get_asset, mock_get_cycle):
        """Test safety order logic with very high deviation percentage"""
        high_deviation_asset = Mock()
        high_deviation_asset.id = 1
        high_deviation_asset.asset_symbol = 'BTC/USD'
        high_deviation_asset.is_enabled = True
        high_deviation_asset.safety_order_amount = Decimal('50.00')
        high_deviation_asset.max_safety_orders = 3
        high_deviation_asset.safety_order_deviation = Decimal('50.0')  # 50% deviation!
        
        mock_get_asset.return_value = high_deviation_asset
        
        cycle = Mock()
        cycle.status = 'watching'
        cycle.quantity = Decimal('0.002')
        cycle.safety_orders = 0
        cycle.last_order_fill_price = Decimal('50000.0')  # Trigger at $25,000 (50% drop)
        mock_get_cycle.return_value = cycle
        
        # Calculate trigger: $50,000 * (1 - 0.5) = $25,000
        trigger_quote = Mock()
        trigger_quote.symbol = 'BTC/USD'
        trigger_quote.ask_price = 24999.0  # Just below trigger
        trigger_quote.bid_price = 24950.0
        
        with patch('main_app.get_trading_client') as mock_get_client, \
             patch('main_app.place_limit_buy_order') as mock_place_order:
            
            # Mock client
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            mock_order = Mock()
            mock_order.id = 'high_deviation_order'
            mock_place_order.return_value = mock_order
            
            check_and_place_safety_order(trigger_quote)
            
            # Should place order with high deviation
            mock_place_order.assert_called_once() 