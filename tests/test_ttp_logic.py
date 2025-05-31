"""
Tests for Trailing Take Profit (TTP) Logic

This module contains additional TTP integration tests.
Most TTP logic is covered in test_take_profit_logic.py.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock
from datetime import datetime, timezone

# Add src to path
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from strategy_logic import decide_take_profit_action
from models.backtest_structs import MarketTickInput


class TestTTPIntegration:
    """Test TTP integration scenarios"""
    
    def setup_method(self):
        """Set up TTP test data"""
        self.ttp_asset_config = Mock()
        self.ttp_asset_config.is_enabled = True
        self.ttp_asset_config.take_profit_percent = Decimal('2.0')  # 2%
        self.ttp_asset_config.safety_order_deviation = Decimal('3.0')
        self.ttp_asset_config.max_safety_orders = 3
        self.ttp_asset_config.ttp_enabled = True  # TTP enabled
        self.ttp_asset_config.ttp_deviation_percent = Decimal('1.0')  # 1% TTP deviation

    @pytest.mark.unit
    def test_ttp_cycle_progression(self):
        """Test complete TTP cycle: activation -> peak tracking -> sell"""
        # This test demonstrates the complete TTP flow
        
        # Stage 1: TTP Activation
        watching_cycle = Mock()
        watching_cycle.status = 'watching'
        watching_cycle.quantity = Decimal('0.01')
        watching_cycle.average_purchase_price = Decimal('100000.0')  # $100k
        watching_cycle.safety_orders = 0
        watching_cycle.last_order_fill_price = Decimal('100000.0')
        watching_cycle.highest_trailing_price = None
        
        activation_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('102500.0'),
            current_bid_price=Decimal('102500.0')  # Above $102k threshold
        )
        
        result1 = decide_take_profit_action(
            activation_input, self.ttp_asset_config, watching_cycle
        )
        
        # Should activate TTP
        assert result1 is not None
        assert result1.ttp_update_intent is not None
        assert result1.ttp_update_intent.new_status == 'trailing'
        assert result1.ttp_update_intent.new_highest_trailing_price == Decimal('102500.0')
        
        # Stage 2: Peak Tracking
        trailing_cycle = Mock()
        trailing_cycle.status = 'trailing'
        trailing_cycle.quantity = Decimal('0.01')
        trailing_cycle.average_purchase_price = Decimal('100000.0')
        trailing_cycle.safety_orders = 0
        trailing_cycle.last_order_fill_price = Decimal('100000.0')
        trailing_cycle.highest_trailing_price = Decimal('102500.0')  # Previous peak
        
        new_peak_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('105000.0'),
            current_bid_price=Decimal('105000.0')  # New peak
        )
        
        result2 = decide_take_profit_action(
            new_peak_input, self.ttp_asset_config, trailing_cycle
        )
        
        # Should update peak
        assert result2 is not None
        assert result2.ttp_update_intent is not None
        assert result2.ttp_update_intent.new_highest_trailing_price == Decimal('105000.0')
        
        # Stage 3: Sell Trigger
        trailing_cycle_peak = Mock()
        trailing_cycle_peak.status = 'trailing'
        trailing_cycle_peak.quantity = Decimal('0.01')
        trailing_cycle_peak.average_purchase_price = Decimal('100000.0')
        trailing_cycle_peak.safety_orders = 0
        trailing_cycle_peak.last_order_fill_price = Decimal('100000.0')
        trailing_cycle_peak.highest_trailing_price = Decimal('105000.0')  # Peak at $105k
        
        # Price drops 1.5% from peak: $105k * 0.985 = $103.425k
        sell_trigger_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('103000.0'),
            current_bid_price=Decimal('103000.0')  # Below $103.95k trigger
        )
        
        result3 = decide_take_profit_action(
            sell_trigger_input, self.ttp_asset_config, trailing_cycle_peak
        )
        
        # Should trigger sell
        assert result3 is not None
        assert result3.order_intent is not None
        assert result3.order_intent.side.value == 'sell'

    @pytest.mark.unit 
    def test_ttp_vs_standard_tp_comparison(self):
        """Test that TTP enabled vs disabled produces different behaviors"""
        cycle = Mock()
        cycle.status = 'watching'
        cycle.quantity = Decimal('0.5')
        cycle.average_purchase_price = Decimal('50000.0')
        cycle.safety_orders = 0
        cycle.last_order_fill_price = Decimal('50000.0')
        cycle.highest_trailing_price = None
        
        market_input = MarketTickInput(
            timestamp=datetime.now(timezone.utc),
            symbol='BTC/USD',
            current_ask_price=Decimal('51500.0'),
            current_bid_price=Decimal('51500.0')  # 3% gain
        )
        
        # Standard TP (TTP disabled) - should sell immediately
        standard_tp_config = Mock()
        standard_tp_config.is_enabled = True
        standard_tp_config.take_profit_percent = Decimal('2.0')  # 2% threshold
        standard_tp_config.safety_order_deviation = Decimal('3.0')
        standard_tp_config.max_safety_orders = 3
        standard_tp_config.ttp_enabled = False  # TTP disabled
        
        result_standard = decide_take_profit_action(
            market_input, standard_tp_config, cycle
        )
        
        # Should sell immediately with standard TP
        assert result_standard is not None
        assert result_standard.order_intent is not None
        assert result_standard.order_intent.side.value == 'sell'
        
        # TTP enabled - should activate trailing instead of selling
        ttp_config = Mock()
        ttp_config.is_enabled = True
        ttp_config.take_profit_percent = Decimal('2.0')  # 2% threshold
        ttp_config.safety_order_deviation = Decimal('3.0')
        ttp_config.max_safety_orders = 3
        ttp_config.ttp_enabled = True  # TTP enabled
        ttp_config.ttp_deviation_percent = Decimal('1.0')
        
        result_ttp = decide_take_profit_action(
            market_input, ttp_config, cycle
        )
        
        # Should activate TTP instead of selling
        assert result_ttp is not None
        assert result_ttp.ttp_update_intent is not None
        assert result_ttp.ttp_update_intent.new_status == 'trailing'
        assert result_ttp.order_intent is None  # No immediate sell


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 