"""
Tests for Phase 6: Take-Profit Logic

This module tests the pure strategy logic for take-profit decisions including
standard take-profit and Trailing Take Profit (TTP) functionality.
"""

import pytest
import logging
from decimal import Decimal
from unittest.mock import Mock, patch
from datetime import datetime, timezone

# Add src to path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from strategy_logic import decide_take_profit_action
from models.backtest_structs import MarketTickInput, OrderSide, OrderType


class TestTakeProfitConditions:
    """Test take-profit condition validation"""
    
    def setup_method(self):
        """Set up test data"""
        self.market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('51950.0')
        )
        
        self.mock_asset_config = Mock()
        self.mock_asset_config.id = 1
        self.mock_asset_config.is_enabled = True
        self.mock_asset_config.take_profit_percent = Decimal('1.0')  # 1%
        self.mock_asset_config.safety_order_deviation = Decimal('2.5')  # 2.5%
        self.mock_asset_config.max_safety_orders = 5
        self.mock_asset_config.ttp_enabled = False  # TTP disabled for standard tests
        self.mock_asset_config.ttp_deviation_percent = None
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 100
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0.5')  # Has position
        self.mock_cycle.average_purchase_price = Decimal('50000.0')  # $50k average
        self.mock_cycle.safety_orders = 2
        self.mock_cycle.last_order_fill_price = Decimal('49000.0')

    @pytest.mark.unit
    def test_take_profit_skipped_if_asset_disabled(self):
        """Test that take-profit is skipped if asset is disabled"""
        disabled_asset = Mock()
        disabled_asset.is_enabled = False
        
        result = decide_take_profit_action(
            self.market_input, disabled_asset, self.mock_cycle
        )
        
        assert result is None

    @pytest.mark.unit
    def test_take_profit_conditions_met(self):
        """Test that take-profit action is returned when all conditions are met"""
        # Average price: $50,000, take-profit: 1%, trigger: $50,500
        # Current bid: $51,950 > $50,500 ✓
        
        result = decide_take_profit_action(
            self.market_input, self.mock_asset_config, self.mock_cycle
        )
        
        assert result is not None
        assert result.order_intent is not None
        
        order_intent = result.order_intent
        assert order_intent.symbol == 'BTC/USD'
        assert order_intent.side == OrderSide.SELL
        assert order_intent.order_type == OrderType.MARKET
        assert order_intent.quantity == Decimal('0.5')  # Full position

    @pytest.mark.unit
    def test_take_profit_conditions_not_met_price_not_high_enough(self):
        """Test that no action is returned when bid price is below take-profit threshold"""
        # Price below take-profit threshold
        low_price_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50000.0'),
            current_bid_price=Decimal('50000.0')  # Below threshold
        )
        
        result = decide_take_profit_action(
            low_price_input, self.mock_asset_config, self.mock_cycle
        )
        
        assert result is None

    @pytest.mark.unit
    def test_take_profit_skipped_when_safety_order_would_trigger(self):
        """Test that take-profit is skipped when safety order conditions are met"""
        # Safety order triggers at: $49,000 * (1 - 2.5%) = $47,775
        # Ask price: $47,500 < $47,775 (safety order would trigger)
        safety_trigger_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('47500.0'),  # Would trigger safety order
            current_bid_price=Decimal('51000.0')   # Would trigger take-profit
        )
        
        result = decide_take_profit_action(
            safety_trigger_input, self.mock_asset_config, self.mock_cycle
        )
        
        # Should be None because safety order takes precedence
        assert result is None

    @pytest.mark.unit
    def test_take_profit_skipped_no_position(self):
        """Test that take-profit is skipped when cycle has no position"""
        empty_cycle = Mock()
        empty_cycle.status = 'watching'
        empty_cycle.quantity = Decimal('0')  # No position
        empty_cycle.average_purchase_price = Decimal('50000.0')
        
        result = decide_take_profit_action(
            self.market_input, self.mock_asset_config, empty_cycle
        )
        
        assert result is None

    @pytest.mark.unit
    def test_take_profit_skipped_wrong_status(self):
        """Test that take-profit is skipped when cycle status is not valid"""
        wrong_status_cycle = Mock()
        wrong_status_cycle.status = 'buying'  # Wrong status
        wrong_status_cycle.quantity = Decimal('0.5')
        wrong_status_cycle.average_purchase_price = Decimal('50000.0')
        
        result = decide_take_profit_action(
            self.market_input, self.mock_asset_config, wrong_status_cycle
        )
        
        assert result is None

    @pytest.mark.unit
    def test_take_profit_skipped_no_average_price(self):
        """Test that take-profit is skipped when no average purchase price exists"""
        no_avg_cycle = Mock()
        no_avg_cycle.status = 'watching'
        no_avg_cycle.quantity = Decimal('0.5')
        no_avg_cycle.average_purchase_price = None  # No average price
        
        result = decide_take_profit_action(
            self.market_input, self.mock_asset_config, no_avg_cycle
        )
        
        assert result is None


class TestTakeProfitCalculations:
    """Test take-profit calculation scenarios"""

    @pytest.mark.unit
    def test_take_profit_trigger_price_calculation(self):
        """Test take-profit trigger price calculations"""
        # Test various scenarios
        test_cases = [
            # (average_price, take_profit_percent, expected_trigger)
            (Decimal('50000.0'), Decimal('1.0'), Decimal('50500.0')),    # 1% of $50k = $50.5k
            (Decimal('25000.0'), Decimal('2.0'), Decimal('25500.0')),    # 2% of $25k = $25.5k
            (Decimal('100000.0'), Decimal('0.5'), Decimal('100500.0')),  # 0.5% of $100k = $100.5k
        ]
        
        for avg_price, tp_percent, expected_trigger in test_cases:
            tp_decimal = tp_percent / Decimal('100')
            calculated_trigger = avg_price * (Decimal('1') + tp_decimal)
            assert calculated_trigger == expected_trigger

    @pytest.mark.unit
    def test_take_profit_quantity_uses_alpaca_position(self):
        """Test that take-profit uses Alpaca position quantity when available"""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('51950.0')
        )
        
        mock_asset_config = Mock()
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.safety_order_deviation = Decimal('2.5')
        mock_asset_config.max_safety_orders = 5
        mock_asset_config.ttp_enabled = False
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.5')  # Cycle shows 0.5
        mock_cycle.average_purchase_price = Decimal('50000.0')
        mock_cycle.safety_orders = 2
        mock_cycle.last_order_fill_price = Decimal('49000.0')
        
        # Mock Alpaca position with different quantity
        mock_alpaca_position = Mock()
        mock_alpaca_position.qty = '0.75'  # Alpaca shows 0.75
        
        result = decide_take_profit_action(
            market_input, mock_asset_config, mock_cycle, mock_alpaca_position
        )
        
        assert result is not None
        order_intent = result.order_intent
        # Should use Alpaca position quantity
        assert order_intent.quantity == Decimal('0.75')

    @pytest.mark.unit
    def test_safety_order_conflict_detection(self):
        """Test safety order conflict detection logic"""
        # Test when safety order would trigger (should block take-profit)
        last_fill = Decimal('50000.0')
        deviation = Decimal('5.0')  # 5%
        
        safety_trigger = last_fill * (Decimal('1') - deviation / Decimal('100'))
        expected_trigger = Decimal('47500.0')  # 50k * 0.95
        
        assert safety_trigger == expected_trigger


class TestTTPLogic:
    """Test Trailing Take Profit logic"""
    
    def setup_method(self):
        """Set up TTP test data"""
        self.market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('51950.0')
        )
        
        self.ttp_asset_config = Mock()
        self.ttp_asset_config.is_enabled = True
        self.ttp_asset_config.take_profit_percent = Decimal('2.0')  # 2%
        self.ttp_asset_config.safety_order_deviation = Decimal('3.0')
        self.ttp_asset_config.max_safety_orders = 3
        self.ttp_asset_config.ttp_enabled = True  # TTP enabled
        self.ttp_asset_config.ttp_deviation_percent = Decimal('1.0')  # 1% TTP deviation

    @pytest.mark.unit
    def test_ttp_activation(self):
        """Test TTP activation when price reaches take-profit threshold"""
        watching_cycle = Mock()
        watching_cycle.status = 'watching'  # Not yet trailing
        watching_cycle.quantity = Decimal('0.5')
        watching_cycle.average_purchase_price = Decimal('50000.0')  # $50k average
        watching_cycle.safety_orders = 0
        watching_cycle.last_order_fill_price = Decimal('50000.0')
        watching_cycle.highest_trailing_price = None
        
        # Price at TTP activation threshold: $50k * 1.02 = $51k
        # Current bid: $51,950 > $51k ✓ (should activate TTP)
        
        result = decide_take_profit_action(
            self.market_input, self.ttp_asset_config, watching_cycle
        )
        
        assert result is not None
        assert result.ttp_update_intent is not None
        assert result.ttp_update_intent.new_status == 'trailing'
        assert result.ttp_update_intent.new_highest_trailing_price == Decimal('51950.0')

    @pytest.mark.unit
    def test_ttp_new_peak_update(self):
        """Test TTP peak price update when new high is reached"""
        trailing_cycle = Mock()
        trailing_cycle.status = 'trailing'  # Already trailing
        trailing_cycle.quantity = Decimal('0.5')
        trailing_cycle.average_purchase_price = Decimal('50000.0')
        trailing_cycle.safety_orders = 0
        trailing_cycle.last_order_fill_price = Decimal('50000.0')
        trailing_cycle.highest_trailing_price = Decimal('51000.0')  # Previous peak
        
        # Current bid higher than previous peak
        result = decide_take_profit_action(
            self.market_input, self.ttp_asset_config, trailing_cycle
        )
        
        assert result is not None
        assert result.ttp_update_intent is not None
        assert result.ttp_update_intent.new_highest_trailing_price == Decimal('51950.0')

    @pytest.mark.unit
    def test_ttp_sell_trigger(self):
        """Test TTP sell trigger when price drops from peak"""
        trailing_cycle = Mock()
        trailing_cycle.status = 'trailing'
        trailing_cycle.quantity = Decimal('0.5')
        trailing_cycle.average_purchase_price = Decimal('50000.0')
        trailing_cycle.safety_orders = 0
        trailing_cycle.last_order_fill_price = Decimal('50000.0')
        trailing_cycle.highest_trailing_price = Decimal('53000.0')  # Peak at $53k
        
        # TTP deviation 1% from $53k = $52.47k trigger
        # Current bid: $52k < $52.47k (should trigger sell)
        low_price_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('52000.0')  # Below TTP trigger
        )
        
        result = decide_take_profit_action(
            low_price_input, self.ttp_asset_config, trailing_cycle
        )
        
        assert result is not None
        assert result.order_intent is not None
        
        order_intent = result.order_intent
        assert order_intent.symbol == 'BTC/USD'
        assert order_intent.side == OrderSide.SELL
        assert order_intent.order_type == OrderType.MARKET
        assert order_intent.quantity == Decimal('0.5')

    @pytest.mark.unit
    def test_ttp_not_activated_below_threshold(self):
        """Test that TTP is not activated when price is below threshold"""
        watching_cycle = Mock()
        watching_cycle.status = 'watching'
        watching_cycle.quantity = Decimal('0.5')
        watching_cycle.average_purchase_price = Decimal('50000.0')
        watching_cycle.safety_orders = 0
        watching_cycle.last_order_fill_price = Decimal('50000.0')
        watching_cycle.highest_trailing_price = None
        
        # Price below TTP activation: $50k * 1.02 = $51k
        # Current bid: $50.5k < $51k (should not activate)
        low_price_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50500.0'),
            current_bid_price=Decimal('50500.0')
        )
        
        result = decide_take_profit_action(
            low_price_input, self.ttp_asset_config, watching_cycle
        )
        
        assert result is None


class TestTakeProfitErrorHandling:
    """Test error handling in take-profit logic"""

    @pytest.mark.unit
    def test_take_profit_invalid_bid_price(self):
        """Test handling of invalid bid price"""
        invalid_market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('0.0')  # Invalid
        )
        
        mock_asset_config = Mock()
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.ttp_enabled = False
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0.5')
        mock_cycle.average_purchase_price = Decimal('50000.0')
        
        result = decide_take_profit_action(
            invalid_market_input, mock_asset_config, mock_cycle
        )
        
        assert result is None

    @pytest.mark.unit
    def test_take_profit_tiny_position_skip(self):
        """Test that tiny positions below minimum are skipped"""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('52000.0'),
            current_bid_price=Decimal('51950.0')
        )
        
        mock_asset_config = Mock()
        mock_asset_config.is_enabled = True
        mock_asset_config.take_profit_percent = Decimal('1.0')
        mock_asset_config.ttp_enabled = False
        
        tiny_cycle = Mock()
        tiny_cycle.status = 'watching'
        tiny_cycle.quantity = Decimal('0.000000001')  # Below minimum
        tiny_cycle.average_purchase_price = Decimal('50000.0')
        
        result = decide_take_profit_action(
            market_input, mock_asset_config, tiny_cycle
        )
        
        assert result is None 