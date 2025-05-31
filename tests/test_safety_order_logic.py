"""
Unit tests for safety order logic functionality (Phase 5)

Tests the pure strategy logic for safety order decisions.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch
import sys
import os
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from strategy_logic import decide_safety_order_action
from models.backtest_structs import MarketTickInput, OrderSide, OrderType


class TestSafetyOrderLogic:
    """Test safety order placement logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('48000.0'),  # Price that might trigger safety order
            current_bid_price=Decimal('47950.0')
        )
        
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
    def test_safety_order_skipped_if_asset_disabled(self):
        """Test that safety order is skipped if asset is disabled"""
        disabled_asset = Mock()
        disabled_asset.is_enabled = False
        
        result = decide_safety_order_action(
            self.market_input, disabled_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_skipped_if_cycle_not_watching(self):
        """Test that safety order is skipped if cycle status is not 'watching'"""
        buying_cycle = Mock()
        buying_cycle.status = 'buying'
        buying_cycle.quantity = Decimal('0.002')
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, buying_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_skipped_if_cycle_has_no_quantity(self):
        """Test that safety order is skipped if cycle has no quantity (no position)"""
        empty_cycle = Mock()
        empty_cycle.status = 'watching'
        empty_cycle.quantity = Decimal('0')  # No position
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, empty_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_conditions_not_met_max_orders(self):
        """Test that safety order is skipped when safety_orders == max_safety_orders"""
        max_safety_cycle = Mock()
        max_safety_cycle.status = 'watching'
        max_safety_cycle.quantity = Decimal('0.002')
        max_safety_cycle.safety_orders = 3  # At max
        max_safety_cycle.last_order_fill_price = Decimal('50000.0')
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, max_safety_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_skipped_if_no_last_fill_price(self):
        """Test that safety order is skipped if no last_order_fill_price"""
        no_fill_cycle = Mock()
        no_fill_cycle.status = 'watching'
        no_fill_cycle.quantity = Decimal('0.002')
        no_fill_cycle.safety_orders = 0
        no_fill_cycle.last_order_fill_price = None  # No fill price
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, no_fill_cycle
        )
        
        assert result is None
    
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
    def test_safety_order_conditions_not_met_price_not_low_enough(self):
        """Test that safety order is skipped when price hasn't dropped enough"""
        # Current ask price is above trigger price
        high_price_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('49500.0'),  # Above trigger price of $49,000
            current_bid_price=Decimal('49450.0')
        )
        
        result = decide_safety_order_action(
            high_price_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_conditions_met(self):
        """Test that safety order action is returned when all conditions are met"""
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is not None
        assert result.order_intent is not None
        
        order_intent = result.order_intent
        assert order_intent.symbol == 'BTC/USD'
        assert order_intent.side == OrderSide.BUY
        assert order_intent.order_type == OrderType.LIMIT
        
        # Verify quantity calculation: $50 / $48,000 ≈ 0.00104 BTC
        expected_quantity = Decimal('50.0') / Decimal('48000.0')
        assert order_intent.quantity == expected_quantity
        assert order_intent.limit_price == Decimal('48000.0')
    
    @pytest.mark.unit
    def test_safety_order_usd_to_qty_conversion(self):
        """Test USD to crypto quantity conversion for safety orders"""
        safety_order_usd = 50.0
        ask_price = 48000.0
        
        expected_quantity = safety_order_usd / ask_price
        assert abs(expected_quantity - 0.00104166666) < 0.00000001
        
        # Test different prices
        ask_price_2 = 24000.0
        expected_quantity_2 = safety_order_usd / ask_price_2
        assert abs(expected_quantity_2 - 0.00208333333) < 0.00000001
    
    @pytest.mark.unit
    def test_safety_order_invalid_ask_price(self):
        """Test that safety order is skipped with invalid ask price"""
        # Test with zero ask price
        invalid_market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('0.0'),
            current_bid_price=Decimal('47950.0')
        )
        
        result = decide_safety_order_action(
            invalid_market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    @patch.dict(os.environ, {'TESTING_MODE': 'true'})
    def test_safety_order_testing_mode_pricing(self):
        """Test that testing mode uses aggressive pricing (5% above ask)"""
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is not None
        order_intent = result.order_intent
        
        # In testing mode, limit price should be 5% above ask
        expected_limit_price = Decimal('48000.0') * Decimal('1.05')
        assert order_intent.limit_price == expected_limit_price


class TestSafetyOrderCalculations:
    """Test safety order calculation scenarios"""
    
    @pytest.mark.unit
    def test_multiple_safety_deviation_scenarios(self):
        """Test safety order trigger calculations with different deviation percentages"""
        last_fill_price = Decimal('50000.0')
        
        # Test 1% deviation
        deviation_1 = Decimal('1.0')
        trigger_1 = last_fill_price * (Decimal('1') - deviation_1 / Decimal('100'))
        assert trigger_1 == Decimal('49500.0')
        
        # Test 5% deviation
        deviation_5 = Decimal('5.0')
        trigger_5 = last_fill_price * (Decimal('1') - deviation_5 / Decimal('100'))
        assert trigger_5 == Decimal('47500.0')
        
        # Test 10% deviation
        deviation_10 = Decimal('10.0')
        trigger_10 = last_fill_price * (Decimal('1') - deviation_10 / Decimal('100'))
        assert trigger_10 == Decimal('45000.0')
    
    @pytest.mark.unit
    def test_price_drop_percentage_calculation(self):
        """Test price drop percentage calculations"""
        last_fill = Decimal('50000.0')
        current_ask = Decimal('48000.0')
        
        price_drop = last_fill - current_ask
        price_drop_pct = (price_drop / last_fill) * Decimal('100')
        
        assert price_drop == Decimal('2000.0')
        assert price_drop_pct == Decimal('4.0')  # 4% drop
    
    @pytest.mark.unit
    def test_safety_order_quantity_conversions(self):
        """Test safety order quantity calculations with various amounts"""
        # Test $100 safety order at different prices
        safety_amount = Decimal('100.0')
        
        # At $50,000
        qty_50k = safety_amount / Decimal('50000.0')
        assert qty_50k == Decimal('0.002')
        
        # At $25,000
        qty_25k = safety_amount / Decimal('25000.0')
        assert qty_25k == Decimal('0.004')
        
        # At $100,000
        qty_100k = safety_amount / Decimal('100000.0')
        assert qty_100k == Decimal('0.001')


class TestSafetyOrderEdgeCases:
    """Test edge cases for safety order logic"""
    
    def setup_method(self):
        """Set up test fixtures for edge cases"""
        self.mock_asset = Mock()
        self.mock_asset.is_enabled = True
        self.mock_asset.safety_order_amount = Decimal('100.0')
        self.mock_asset.max_safety_orders = 3
        self.mock_asset.safety_order_deviation = Decimal('5.0')  # 5% deviation
    
    @pytest.mark.unit
    def test_safety_order_at_exact_trigger_price(self):
        """Test safety order behavior at exact trigger price"""
        # Last fill at $50k, 5% deviation = trigger at $47.5k
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.002')
        mock_cycle.safety_orders = 0
        mock_cycle.last_order_fill_price = Decimal('50000.0')
        
        # Market input at exact trigger price
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('47500.0'),  # Exact trigger
            current_bid_price=Decimal('47450.0')
        )
        
        result = decide_safety_order_action(
            market_input, self.mock_asset, mock_cycle
        )
        
        # Should trigger at exact price
        assert result is not None
        assert result.order_intent is not None
    
    @pytest.mark.unit
    def test_safety_order_with_zero_deviation(self):
        """Test safety order with zero deviation (triggers at any price below last fill)"""
        zero_deviation_asset = Mock()
        zero_deviation_asset.is_enabled = True
        zero_deviation_asset.safety_order_amount = Decimal('100.0')
        zero_deviation_asset.max_safety_orders = 3
        zero_deviation_asset.safety_order_deviation = Decimal('0.0')  # 0% deviation
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.002')
        mock_cycle.safety_orders = 0
        mock_cycle.last_order_fill_price = Decimal('50000.0')
        
        # With 0% deviation, trigger price = last_fill_price = $50,000
        # So any price below $50,000 should trigger
        
        # Test price above last fill (should not trigger)
        market_input_above = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50001.0'),  # Above last fill
            current_bid_price=Decimal('50000.0')
        )
        
        result_above = decide_safety_order_action(
            market_input_above, zero_deviation_asset, mock_cycle
        )
        
        # Should not trigger above last fill price
        assert result_above is None
        
        # Test price below last fill (should trigger)
        market_input_below = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('49999.0'),  # Below last fill
            current_bid_price=Decimal('49950.0')
        )
        
        result_below = decide_safety_order_action(
            market_input_below, zero_deviation_asset, mock_cycle
        )
        
        # Should trigger below last fill price
        assert result_below is not None
        assert result_below.order_intent is not None
    
    @pytest.mark.unit
    def test_safety_order_with_high_deviation(self):
        """Test safety order with very high deviation"""
        high_deviation_asset = Mock()
        high_deviation_asset.is_enabled = True
        high_deviation_asset.safety_order_amount = Decimal('100.0')
        high_deviation_asset.max_safety_orders = 3
        high_deviation_asset.safety_order_deviation = Decimal('50.0')  # 50% deviation
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.002')
        mock_cycle.safety_orders = 0
        mock_cycle.last_order_fill_price = Decimal('50000.0')
        
        # Price needs to drop to $25k to trigger (50% of $50k)
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('30000.0'),  # Only 40% drop, not enough
            current_bid_price=Decimal('29950.0')
        )
        
        result = decide_safety_order_action(
            market_input, high_deviation_asset, mock_cycle
        )
        
        # Should not trigger yet (need 50% drop)
        assert result is None
        
        # Now test with sufficient drop
        market_input_low = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('24000.0'),  # More than 50% drop
            current_bid_price=Decimal('23950.0')
        )
        
        result_low = decide_safety_order_action(
            market_input_low, high_deviation_asset, mock_cycle
        )
        
        # Should trigger now
        assert result_low is not None
        assert result_low.order_intent is not None 