"""
Unit tests for market data handler functionality (Phase 4 & 5)

Tests the logic for monitoring crypto prices and placing base orders and safety orders
when conditions are met.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from datetime import datetime, timezone

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from strategy_logic import decide_base_order_action, decide_safety_order_action
from models.backtest_structs import MarketTickInput, OrderSide, OrderType


class TestBaseOrderLogic:
    """Test base order placement logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50000.0'),
            current_bid_price=Decimal('49950.0')
        )
        
        self.mock_asset = Mock()
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.is_enabled = True
        self.mock_asset.base_order_amount = Decimal('100.00')
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 1
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0')
    
    @pytest.mark.unit
    def test_base_order_skipped_if_asset_disabled(self):
        """Test that base order is skipped if asset is disabled"""
        disabled_asset = Mock()
        disabled_asset.is_enabled = False
        
        result = decide_base_order_action(
            self.market_input, disabled_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_base_order_skipped_if_cycle_not_watching(self):
        """Test that base order is skipped if cycle status is not 'watching'"""
        buying_cycle = Mock()
        buying_cycle.status = 'buying'
        buying_cycle.quantity = Decimal('0')
        
        result = decide_base_order_action(
            self.market_input, self.mock_asset, buying_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_base_order_skipped_if_cycle_has_quantity(self):
        """Test that base order is skipped if cycle already has quantity"""
        active_cycle = Mock()
        active_cycle.status = 'watching'
        active_cycle.quantity = Decimal('0.1')  # Already has quantity
        
        result = decide_base_order_action(
            self.market_input, self.mock_asset, active_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_base_order_skipped_if_position_exists(self):
        """Test that base order is skipped if Alpaca position already exists"""
        # Mock existing position
        existing_position = Mock()
        existing_position.qty = '0.1'
        existing_position.avg_entry_price = '48000.0'
        
        result = decide_base_order_action(
            self.market_input, self.mock_asset, self.mock_cycle, existing_position
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_base_order_conditions_met(self):
        """Test that base order action is returned when all conditions are met"""
        result = decide_base_order_action(
            self.market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is not None
        assert result.order_intent is not None
        
        order_intent = result.order_intent
        assert order_intent.symbol == 'BTC/USD'
        assert order_intent.side == OrderSide.BUY
        assert order_intent.order_type == OrderType.LIMIT
        
        # Verify quantity calculation: $100 / $50,000 = 0.002 BTC
        expected_quantity = Decimal('100.0') / Decimal('50000.0')
        assert order_intent.quantity == expected_quantity
        assert order_intent.limit_price == Decimal('50000.0')
    
    @pytest.mark.unit
    def test_base_order_usd_to_qty_conversion(self):
        """Test USD to crypto quantity conversion"""
        base_order_usd = 100.0
        ask_price = 50000.0
        
        expected_quantity = base_order_usd / ask_price
        assert expected_quantity == 0.002
        
        # Test different prices
        ask_price_2 = 25000.0
        expected_quantity_2 = base_order_usd / ask_price_2
        assert expected_quantity_2 == 0.004
    
    @pytest.mark.unit
    def test_base_order_invalid_ask_price(self):
        """Test that base order is skipped with invalid ask price"""
        # Test with zero ask price
        invalid_market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('0.0'),
            current_bid_price=Decimal('49950.0')
        )
        
        result = decide_base_order_action(
            invalid_market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    @patch.dict(os.environ, {'TESTING_MODE': 'true'})
    def test_base_order_testing_mode_pricing(self):
        """Test that testing mode uses aggressive pricing (5% above ask)"""
        result = decide_base_order_action(
            self.market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is not None
        order_intent = result.order_intent
        
        # In testing mode, limit price should be 5% above ask
        expected_limit_price = Decimal('50000.0') * Decimal('1.05')
        assert order_intent.limit_price == expected_limit_price


class TestSafetyOrderLogic:
    """Test safety order placement logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('45000.0'),  # Lower price for safety order trigger
            current_bid_price=Decimal('44950.0')
        )
        
        self.mock_asset = Mock()
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.is_enabled = True
        self.mock_asset.safety_order_amount = Decimal('200.00')
        self.mock_asset.safety_order_deviation = Decimal('5.0')  # 5%
        self.mock_asset.max_safety_orders = 3
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 1
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0.002')  # Has existing position
        self.mock_cycle.safety_orders = 0
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
    def test_safety_order_skipped_if_no_quantity(self):
        """Test that safety order is skipped if cycle has no quantity"""
        empty_cycle = Mock()
        empty_cycle.status = 'watching'
        empty_cycle.quantity = Decimal('0')
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, empty_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_skipped_if_max_reached(self):
        """Test that safety order is skipped if max safety orders reached"""
        max_cycle = Mock()
        max_cycle.status = 'watching'
        max_cycle.quantity = Decimal('0.002')
        max_cycle.safety_orders = 3  # At max
        max_cycle.last_order_fill_price = Decimal('50000.0')
        
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, max_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_skipped_if_price_not_dropped_enough(self):
        """Test that safety order is skipped if price hasn't dropped enough"""
        # Current ask is $48k, last fill was $50k = 4% drop
        # But safety order deviation is 5%, so shouldn't trigger
        higher_price_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('48000.0'),  # Only 4% drop
            current_bid_price=Decimal('47950.0')
        )
        
        result = decide_safety_order_action(
            higher_price_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is None
    
    @pytest.mark.unit
    def test_safety_order_conditions_met(self):
        """Test that safety order action is returned when all conditions are met"""
        # Current ask is $45k, last fill was $50k = 10% drop
        # Safety order deviation is 5%, so should trigger
        result = decide_safety_order_action(
            self.market_input, self.mock_asset, self.mock_cycle
        )
        
        assert result is not None
        assert result.order_intent is not None
        
        order_intent = result.order_intent
        assert order_intent.symbol == 'BTC/USD'
        assert order_intent.side == OrderSide.BUY
        assert order_intent.order_type == OrderType.LIMIT
        
        # Verify quantity calculation: $200 / $45,000 ≈ 0.00444 BTC
        expected_quantity = Decimal('200.0') / Decimal('45000.0')
        assert order_intent.quantity == expected_quantity
        assert order_intent.limit_price == Decimal('45000.0')


class TestMarketDataIntegration:
    """Test market data integration scenarios"""
    
    @pytest.mark.unit
    def test_market_tick_input_structure(self):
        """Test MarketTickInput object structure"""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50000.0'),
            current_bid_price=Decimal('49950.0')
        )
        
        assert market_input.symbol == 'BTC/USD'
        assert market_input.current_ask_price == Decimal('50000.0')
        assert market_input.current_bid_price == Decimal('49950.0')
        assert isinstance(market_input.timestamp, datetime)
    
    @pytest.mark.unit
    def test_position_filtering_logic(self):
        """Test position filtering logic for tiny positions"""
        # Test that tiny positions below minimum order size are ignored
        tiny_position = Mock()
        tiny_position.qty = '0.000000001'  # Below minimum
        tiny_position.avg_entry_price = '50000.0'
        
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('50000.0'),
            current_bid_price=Decimal('49950.0')
        )
        
        mock_asset = Mock()
        mock_asset.is_enabled = True
        mock_asset.base_order_amount = Decimal('100.00')
        
        mock_cycle = Mock()
        mock_cycle.status = 'watching'
        mock_cycle.quantity = Decimal('0')
        
        # Should not be blocked by tiny position
        result = decide_base_order_action(
            market_input, mock_asset, mock_cycle, tiny_position
        )
        
        assert result is not None  # Order should be allowed despite tiny position 