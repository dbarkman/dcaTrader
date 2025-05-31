"""
Unit tests for the BacktestSimulation class from the Phase 3 backtesting engine.

Tests the in-memory cycle state management and strategy action processing.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import sys
import os

# Add src and scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from run_backtest import BacktestSimulation
from models.asset_config import DcaAsset
from models.backtest_structs import (
    StrategyAction, OrderIntent, CycleStateUpdateIntent, TTPStateUpdateIntent,
    OrderSide, OrderType
)


class TestBacktestSimulation:
    """Test the BacktestSimulation class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create mock asset config
        self.mock_asset = Mock(spec=DcaAsset)
        self.mock_asset.id = 1
        self.mock_asset.symbol = 'BTC/USD'
        self.mock_asset.base_order_amount = Decimal('100.0')
        self.mock_asset.safety_order_amount = Decimal('50.0')
        self.mock_asset.max_safety_orders = 3
        self.mock_asset.take_profit_percent = Decimal('2.0')
        self.mock_asset.ttp_enabled = True
        self.mock_asset.ttp_deviation_percent = Decimal('1.0')
        
        self.simulation = BacktestSimulation(self.mock_asset)
        self.test_timestamp = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    
    @pytest.mark.unit
    def test_initialization(self):
        """Test that BacktestSimulation initializes correctly."""
        assert self.simulation.asset_config == self.mock_asset
        assert self.simulation.current_cycle.id == 0
        assert self.simulation.current_cycle.asset_id == 1
        assert self.simulation.current_cycle.status == 'watching'
        assert self.simulation.current_cycle.quantity == Decimal('0')
        assert self.simulation.current_cycle.average_purchase_price == Decimal('0')
        assert self.simulation.current_cycle.safety_orders == 0
        assert self.simulation.current_alpaca_position is None
        assert self.simulation.order_counter == 0
    
    @pytest.mark.unit
    def test_get_next_order_id(self):
        """Test that get_next_order_id generates unique IDs."""
        id1 = self.simulation.get_next_order_id()
        id2 = self.simulation.get_next_order_id()
        id3 = self.simulation.get_next_order_id()
        
        assert id1 == "sim_order_1"
        assert id2 == "sim_order_2"
        assert id3 == "sim_order_3"
        assert self.simulation.order_counter == 3
    
    @pytest.mark.unit
    def test_process_strategy_action_with_empty_action(self):
        """Test processing an empty or None strategy action."""
        # Test with None
        self.simulation.process_strategy_action(None, self.test_timestamp)
        assert self.simulation.current_cycle.status == 'watching'  # No change
        
        # Test with empty action
        empty_action = StrategyAction()
        self.simulation.process_strategy_action(empty_action, self.test_timestamp)
        assert self.simulation.current_cycle.status == 'watching'  # No change
    
    @pytest.mark.unit
    def test_process_order_intent_logging(self):
        """Test that order intents are logged correctly."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.001'),
            limit_price=Decimal('45000.0')
        )
        
        action = StrategyAction(order_intent=order_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify logging was called
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "📋 ORDER INTENT: BUY LIMIT" in log_call
            assert "Symbol: BTC/USD" in log_call
            assert "Quantity: 0.001" in log_call
            assert "Price: 45000.0" in log_call
            assert "sim_order_1" in log_call
    
    @pytest.mark.unit
    def test_process_order_intent_market_order(self):
        """Test processing a market order intent."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.002')
        )
        
        action = StrategyAction(order_intent=order_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            log_call = mock_log.call_args[0][0]
            assert "📋 ORDER INTENT: SELL MARKET" in log_call
            assert "Price: MARKET" in log_call
    
    @pytest.mark.unit
    def test_process_cycle_update_intent_status_change(self):
        """Test processing cycle state update with status change."""
        update_intent = CycleStateUpdateIntent(new_status='buying')
        action = StrategyAction(cycle_update_intent=update_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify status was updated
            assert self.simulation.current_cycle.status == 'buying'
            
            # Verify logging
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "🔄 CYCLE STATUS: watching → buying" in log_call
    
    @pytest.mark.unit
    def test_process_cycle_update_intent_quantity_change(self):
        """Test processing cycle state update with quantity change."""
        new_quantity = Decimal('0.002')
        update_intent = CycleStateUpdateIntent(new_quantity=new_quantity)
        action = StrategyAction(cycle_update_intent=update_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify quantity was updated
            assert self.simulation.current_cycle.quantity == new_quantity
            
            # Verify logging
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "📊 QUANTITY: 0.002" in log_call
    
    @pytest.mark.unit
    def test_process_cycle_update_intent_price_changes(self):
        """Test processing cycle state update with price changes."""
        avg_price = Decimal('45000.0')
        last_fill_price = Decimal('44800.0')
        
        update_intent = CycleStateUpdateIntent(
            new_average_purchase_price=avg_price,
            new_last_order_fill_price=last_fill_price
        )
        action = StrategyAction(cycle_update_intent=update_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify prices were updated
            assert self.simulation.current_cycle.average_purchase_price == avg_price
            assert self.simulation.current_cycle.last_order_fill_price == last_fill_price
            
            # Verify logging (should have multiple calls)
            assert mock_log.call_count == 2
    
    @pytest.mark.unit
    def test_process_cycle_update_intent_safety_orders(self):
        """Test processing cycle state update with safety orders change."""
        update_intent = CycleStateUpdateIntent(new_safety_orders=2)
        action = StrategyAction(cycle_update_intent=update_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify safety orders were updated
            assert self.simulation.current_cycle.safety_orders == 2
            
            # Verify logging
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "🛡️ SAFETY ORDERS: 2" in log_call
    
    @pytest.mark.unit
    def test_process_cycle_update_intent_order_tracking(self):
        """Test processing cycle state update with order ID tracking."""
        update_intent = CycleStateUpdateIntent(new_latest_order_id="existing_order_123")
        action = StrategyAction(cycle_update_intent=update_intent)
        
        self.simulation.process_strategy_action(action, self.test_timestamp)
        
        # When there's an explicit order ID, it should generate a new simulated one
        assert self.simulation.current_cycle.latest_order_id == "sim_order_1"
        assert self.simulation.current_cycle.latest_order_created_at == self.test_timestamp
    
    @pytest.mark.unit
    def test_process_ttp_update_intent_status_change(self):
        """Test processing TTP state update with status change."""
        ttp_intent = TTPStateUpdateIntent(new_status='trailing')
        action = StrategyAction(ttp_update_intent=ttp_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify status was updated
            assert self.simulation.current_cycle.status == 'trailing'
            
            # Verify logging
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "🎯 TTP STATUS: watching → trailing" in log_call
    
    @pytest.mark.unit
    def test_process_ttp_update_intent_peak_price(self):
        """Test processing TTP state update with peak price change."""
        peak_price = Decimal('46000.0')
        ttp_intent = TTPStateUpdateIntent(new_highest_trailing_price=peak_price)
        action = StrategyAction(ttp_update_intent=ttp_intent)
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify peak price was updated
            assert self.simulation.current_cycle.highest_trailing_price == peak_price
            
            # Verify logging
            mock_log.assert_called()
            log_call = mock_log.call_args[0][0]
            assert "⬆️ TTP PEAK: $46000.0" in log_call
    
    @pytest.mark.unit
    def test_process_combined_action(self):
        """Test processing a strategy action with multiple intents."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.001'),
            limit_price=Decimal('45000.0')
        )
        
        cycle_intent = CycleStateUpdateIntent(
            new_status='buying',
            new_quantity=Decimal('0.001')
        )
        
        ttp_intent = TTPStateUpdateIntent(new_status='trailing')
        
        action = StrategyAction(
            order_intent=order_intent,
            cycle_update_intent=cycle_intent,
            ttp_update_intent=ttp_intent
        )
        
        with patch.object(self.simulation.logger, 'info') as mock_log:
            self.simulation.process_strategy_action(action, self.test_timestamp)
            
            # Verify all updates were applied
            assert self.simulation.current_cycle.status == 'trailing'  # TTP takes precedence
            assert self.simulation.current_cycle.quantity == Decimal('0.001')
            assert self.simulation.current_cycle.latest_order_id == 'sim_order_2'  # Gets incremented twice
            
            # Verify multiple log calls were made
            assert mock_log.call_count >= 3
    
    @pytest.mark.unit
    def test_log_cycle_state(self):
        """Test the log_cycle_state method."""
        # Set up some state
        self.simulation.current_cycle.status = 'watching'
        self.simulation.current_cycle.quantity = Decimal('0.001')
        self.simulation.current_cycle.average_purchase_price = Decimal('45000.0')
        self.simulation.current_cycle.safety_orders = 2
        self.simulation.current_cycle.highest_trailing_price = Decimal('46000.0')
        
        with patch.object(self.simulation.logger, 'debug') as mock_log:
            self.simulation.log_cycle_state()
            
            mock_log.assert_called_once()
            log_call = mock_log.call_args[0][0]
            assert "💾 CYCLE STATE:" in log_call
            assert "Status=watching" in log_call
            assert "Qty=0.001" in log_call
            assert "AvgPrice=$45000.0" in log_call
            assert "SafetyOrders=2" in log_call
            assert "TTPPeak=$46000.0" in log_call
    
    @pytest.mark.unit
    def test_order_counter_increments_with_action_processing(self):
        """Test that order counter increments when processing actions with order intents."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.001')
        )
        
        # Process first action
        action1 = StrategyAction(order_intent=order_intent)
        self.simulation.process_strategy_action(action1, self.test_timestamp)
        assert self.simulation.order_counter == 1
        
        # Process second action
        action2 = StrategyAction(order_intent=order_intent)
        self.simulation.process_strategy_action(action2, self.test_timestamp)
        assert self.simulation.order_counter == 2
        
        # Process action without order intent (should not increment)
        cycle_intent = CycleStateUpdateIntent(new_status='selling')
        action3 = StrategyAction(cycle_update_intent=cycle_intent)
        self.simulation.process_strategy_action(action3, self.test_timestamp)
        assert self.simulation.order_counter == 2  # No increment
    
    @pytest.mark.unit
    def test_multiple_status_updates_precedence(self):
        """Test that TTP status updates take precedence over cycle status updates."""
        cycle_intent = CycleStateUpdateIntent(new_status='buying')
        ttp_intent = TTPStateUpdateIntent(new_status='trailing')
        
        action = StrategyAction(
            cycle_update_intent=cycle_intent,
            ttp_update_intent=ttp_intent
        )
        
        self.simulation.process_strategy_action(action, self.test_timestamp)
        
        # TTP status should take precedence
        assert self.simulation.current_cycle.status == 'trailing' 