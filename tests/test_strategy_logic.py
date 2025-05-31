#!/usr/bin/env python3
"""
Tests for strategy_logic.py - pure strategy decision functions.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch
from datetime import datetime, timezone
from decimal import Decimal

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from strategy_logic import (
    decide_base_order_action,
    decide_safety_order_action,
    decide_take_profit_action
)
from models.backtest_structs import (
    MarketTickInput, StrategyAction, OrderIntent, CycleStateUpdateIntent,
    TTPStateUpdateIntent, OrderSide, OrderType
)


class MockAssetConfig:
    """Mock DcaAsset for testing."""
    def __init__(self, **kwargs):
        self.is_enabled = kwargs.get('is_enabled', True)
        self.base_order_amount = kwargs.get('base_order_amount', Decimal('10.0'))
        self.safety_order_amount = kwargs.get('safety_order_amount', Decimal('20.0'))
        self.max_safety_orders = kwargs.get('max_safety_orders', 3)
        self.safety_order_deviation = kwargs.get('safety_order_deviation', Decimal('2.0'))
        self.take_profit_percent = kwargs.get('take_profit_percent', Decimal('3.0'))
        self.ttp_enabled = kwargs.get('ttp_enabled', False)
        self.ttp_deviation_percent = kwargs.get('ttp_deviation_percent', Decimal('1.0'))


class MockCycle:
    """Mock DcaCycle for testing."""
    def __init__(self, **kwargs):
        self.id = kwargs.get('id', 1)
        self.status = kwargs.get('status', 'watching')
        self.quantity = kwargs.get('quantity', Decimal('0'))
        self.average_purchase_price = kwargs.get('average_purchase_price', None)
        self.safety_orders = kwargs.get('safety_orders', 0)
        self.last_order_fill_price = kwargs.get('last_order_fill_price', None)
        self.highest_trailing_price = kwargs.get('highest_trailing_price', None)


class MockAlpacaPosition:
    """Mock Alpaca position for testing."""
    def __init__(self, qty="0", avg_entry_price="0"):
        self.qty = qty
        self.avg_entry_price = avg_entry_price


class TestDecideBaseOrderAction:
    """Test decide_base_order_action function."""
    
    @pytest.mark.unit
    def test_disabled_asset_returns_none(self):
        """Test that disabled assets return None."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('100.0'),
            current_bid_price=Decimal('99.0'),
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(is_enabled=False)
        cycle = MockCycle(status='watching', quantity=Decimal('0'))
        
        result = decide_base_order_action(market_input, asset_config, cycle)
        assert result is None
    
    @pytest.mark.unit
    def test_valid_base_order_action(self):
        """Test valid base order action creation."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('100.0'),
            current_bid_price=Decimal('99.0'),
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(base_order_amount=Decimal('10.0'))
        cycle = MockCycle(status='watching', quantity=Decimal('0'))
        
        result = decide_base_order_action(market_input, asset_config, cycle)
        
        assert result is not None
        assert result.order_intent is not None
        assert result.order_intent.side == OrderSide.BUY
        assert result.order_intent.order_type == OrderType.LIMIT
        assert result.order_intent.symbol == 'BTC/USD'
        assert result.order_intent.quantity == Decimal('0.1')  # $10 / $100
        assert result.order_intent.limit_price == Decimal('100.0')
        
        assert result.cycle_update_intent is not None
        assert result.cycle_update_intent.new_status == 'buying'


class TestDecideSafetyOrderAction:
    """Test decide_safety_order_action function."""
    
    @pytest.mark.unit
    def test_disabled_asset_returns_none(self):
        """Test that disabled assets return None."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('90.0'),
            current_bid_price=Decimal('89.0'),
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(is_enabled=False)
        cycle = MockCycle(status='watching', quantity=Decimal('1.0'), last_order_fill_price=Decimal('100.0'))
        
        result = decide_safety_order_action(market_input, asset_config, cycle)
        assert result is None
    
    @pytest.mark.unit
    def test_valid_safety_order_action(self):
        """Test valid safety order action creation."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('98.0'),  # 2% drop from $100
            current_bid_price=Decimal('97.0'),
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(
            safety_order_deviation=Decimal('2.0'),
            safety_order_amount=Decimal('20.0')
        )
        cycle = MockCycle(status='watching', quantity=Decimal('1.0'), last_order_fill_price=Decimal('100.0'))
        
        result = decide_safety_order_action(market_input, asset_config, cycle)
        
        assert result is not None
        assert result.order_intent is not None
        assert result.order_intent.side == OrderSide.BUY
        assert result.order_intent.order_type == OrderType.LIMIT
        assert result.order_intent.symbol == 'BTC/USD'
        # Approximate quantity check ($20 / $98)
        expected_qty = Decimal('20.0') / Decimal('98.0')
        assert abs(result.order_intent.quantity - expected_qty) < Decimal('0.000001')
        assert result.order_intent.limit_price == Decimal('98.0')
        
        assert result.cycle_update_intent is not None
        assert result.cycle_update_intent.new_status == 'buying'


class TestDecideTakeProfitAction:
    """Test decide_take_profit_action function."""
    
    @pytest.mark.unit
    def test_disabled_asset_returns_none(self):
        """Test that disabled assets return None."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('103.0'),
            current_bid_price=Decimal('103.1'),
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(is_enabled=False)
        cycle = MockCycle(status='watching', quantity=Decimal('1.0'), average_purchase_price=Decimal('100.0'))
        
        result = decide_take_profit_action(market_input, asset_config, cycle)
        assert result is None
    
    @pytest.mark.unit
    def test_standard_take_profit_triggered(self):
        """Test valid standard take profit action."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('105.0'),
            current_bid_price=Decimal('103.1'),  # Above 3% take profit
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(ttp_enabled=False, take_profit_percent=Decimal('3.0'))
        cycle = MockCycle(status='watching', quantity=Decimal('1.0'), average_purchase_price=Decimal('100.0'))
        
        result = decide_take_profit_action(market_input, asset_config, cycle)
        
        assert result is not None
        assert result.order_intent is not None
        assert result.order_intent.side == OrderSide.SELL
        assert result.order_intent.order_type == OrderType.MARKET
        assert result.order_intent.symbol == 'BTC/USD'
        assert result.order_intent.quantity == Decimal('1.0')
        
        assert result.cycle_update_intent is not None
        assert result.cycle_update_intent.new_status == 'selling'
    
    @pytest.mark.unit
    def test_ttp_activation(self):
        """Test TTP activation action."""
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            current_ask_price=Decimal('105.0'),
            current_bid_price=Decimal('103.1'),  # Above 3% take profit
            symbol='BTC/USD'
        )
        asset_config = MockAssetConfig(ttp_enabled=True, take_profit_percent=Decimal('3.0'))
        cycle = MockCycle(status='watching', quantity=Decimal('1.0'), average_purchase_price=Decimal('100.0'))
        
        result = decide_take_profit_action(market_input, asset_config, cycle)
        
        assert result is not None
        assert result.order_intent is None  # No order, just TTP activation
        assert result.ttp_update_intent is not None
        assert result.ttp_update_intent.new_status == 'trailing'
        assert result.ttp_update_intent.new_highest_trailing_price == Decimal('103.1') 