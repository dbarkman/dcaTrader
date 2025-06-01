"""
Unit tests for Phase 5 backtesting engine features.
Tests cooldown management, stale order cancellation, and performance reporting.
"""

import pytest
import pytest_asyncio
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone, timedelta
import sys
import os

# Add src and scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from run_backtest import (
    BacktestSimulation, BrokerSimulator, SimulatedPortfolio, CompletedTrade, 
    PerformanceMetrics, calculate_performance_metrics, STALE_ORDER_THRESHOLD_MINUTES,
    STUCK_MARKET_SELL_TIMEOUT_SECONDS
)
from models.asset_config import DcaAsset
from models.cycle_data import DcaCycle


class TestCooldownManagement:
    """Test suite for cooldown period management."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.mock_asset = Mock(spec=DcaAsset)
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.cooldown_period = 300  # 5 minutes
        
        self.portfolio = SimulatedPortfolio(starting_cash=Decimal('10000.0'))
        self.broker = BrokerSimulator(self.portfolio)
        self.simulation = BacktestSimulation(self.mock_asset, self.portfolio, self.broker)
        
        # Set cycle to cooldown status with completion time
        self.simulation.current_cycle.status = 'cooldown'
        self.simulation.current_cycle.completed_at = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        
    @pytest.mark.unit
    def test_cooldown_not_expired(self):
        """Test that cooldown doesn't expire before the cooldown period."""
        # Check cooldown 2 minutes after completion (should not expire)
        current_time = datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc)
        
        self.simulation.check_cooldown_expiry(current_time)
        
        # Should still be in cooldown
        assert self.simulation.current_cycle.status == 'cooldown'
        assert self.simulation.current_cycle.completed_at is not None
        
    @pytest.mark.unit
    def test_cooldown_expired(self):
        """Test that cooldown expires after the cooldown period."""
        # Check cooldown 6 minutes after completion (should expire)
        current_time = datetime(2024, 1, 1, 12, 6, tzinfo=timezone.utc)
        
        self.simulation.check_cooldown_expiry(current_time)
        
        # Should transition to watching
        assert self.simulation.current_cycle.status == 'watching'
        assert self.simulation.current_cycle.completed_at is None
        
    @pytest.mark.unit
    def test_cooldown_exact_expiry_time(self):
        """Test cooldown expiry at exactly the cooldown period."""
        # Check cooldown exactly 5 minutes after completion
        current_time = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        
        self.simulation.check_cooldown_expiry(current_time)
        
        # Should transition to watching
        assert self.simulation.current_cycle.status == 'watching'
        
    @pytest.mark.unit
    def test_cooldown_expiry_resets_cycle(self):
        """Test that cooldown expiry resets cycle for new trading."""
        # Set some cycle data before expiry
        self.simulation.current_cycle.quantity = Decimal('0.1')
        self.simulation.current_cycle.safety_orders = 2
        
        # Expire cooldown
        current_time = datetime(2024, 1, 1, 12, 6, tzinfo=timezone.utc)
        self.simulation.check_cooldown_expiry(current_time)
        
        # Verify cycle is reset
        assert self.simulation.current_cycle.quantity == Decimal('0')
        assert self.simulation.current_cycle.safety_orders == 0
        assert self.simulation.cycle_entry_timestamp is None
        
    @pytest.mark.unit
    def test_no_cooldown_check_when_not_in_cooldown(self):
        """Test that cooldown check doesn't affect non-cooldown cycles."""
        self.simulation.current_cycle.status = 'watching'
        self.simulation.current_cycle.completed_at = None
        
        current_time = datetime(2024, 1, 1, 12, 6, tzinfo=timezone.utc)
        self.simulation.check_cooldown_expiry(current_time)
        
        # Should remain watching
        assert self.simulation.current_cycle.status == 'watching'


class TestStaleOrderCancellation:
    """Test suite for stale/stuck order cancellation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.portfolio = SimulatedPortfolio()
        self.broker = BrokerSimulator(self.portfolio)
        
    @pytest.mark.unit
    def test_stale_buy_limit_order_cancellation(self):
        """Test cancellation of stale BUY limit orders."""
        # Create a BUY limit order that's been open too long
        created_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        current_time = datetime(2024, 1, 1, 12, 10, tzinfo=timezone.utc)  # 10 minutes later
        
        # Mock order intent for placing order
        order_intent = Mock()
        order_intent.symbol = 'BTC/USD'
        order_intent.side = Mock()
        order_intent.side.value = 'buy'
        order_intent.order_type = Mock()
        order_intent.order_type.value = 'limit'
        order_intent.quantity = Decimal('0.001')
        order_intent.limit_price = Decimal('45000.0')
        
        # Place order
        order_id = self.broker.place_order(order_intent, created_time)
        
        # Verify order is open
        assert len(self.broker.open_orders) == 1
        assert self.broker.open_orders[0].status == 'open'
        
        # Check for stale orders (should cancel the order)
        cancel_events = self.broker._check_stale_orders(current_time)
        
        # Verify cancellation
        assert len(cancel_events) == 1
        assert cancel_events[0]['cancel_reason'] == 'stale_buy_limit'
        assert self.broker.open_orders[0].status == 'canceled'
        
    @pytest.mark.unit
    def test_stuck_sell_market_order_cancellation(self):
        """Test cancellation of stuck SELL market orders."""
        # Create a SELL market order that's been open too long
        created_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        current_time = datetime(2024, 1, 1, 12, 3, tzinfo=timezone.utc)  # 3 minutes later
        
        # Mock order intent for placing order
        order_intent = Mock()
        order_intent.symbol = 'BTC/USD'
        order_intent.side = Mock()
        order_intent.side.value = 'sell'
        order_intent.order_type = Mock()
        order_intent.order_type.value = 'market'
        order_intent.quantity = Decimal('0.001')
        order_intent.limit_price = None
        
        # Place order
        order_id = self.broker.place_order(order_intent, created_time)
        
        # Check for stuck orders (should cancel the order)
        cancel_events = self.broker._check_stale_orders(current_time)
        
        # Verify cancellation
        assert len(cancel_events) == 1
        assert cancel_events[0]['cancel_reason'] == 'stuck_sell_market'
        
    @pytest.mark.unit
    def test_order_not_canceled_before_threshold(self):
        """Test that orders are not canceled before reaching threshold."""
        # Create a BUY limit order that hasn't been open long enough
        created_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        current_time = datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc)  # 2 minutes later
        
        # Mock order intent
        order_intent = Mock()
        order_intent.symbol = 'BTC/USD'
        order_intent.side = Mock()
        order_intent.side.value = 'buy'
        order_intent.order_type = Mock()
        order_intent.order_type.value = 'limit'
        order_intent.quantity = Decimal('0.001')
        order_intent.limit_price = Decimal('45000.0')
        
        # Place order
        self.broker.place_order(order_intent, created_time)
        
        # Check for stale orders (should not cancel)
        cancel_events = self.broker._check_stale_orders(current_time)
        
        # Verify no cancellation
        assert len(cancel_events) == 0
        assert self.broker.open_orders[0].status == 'open'
        
    @pytest.mark.unit
    def test_multiple_orders_cancellation_logic(self):
        """Test cancellation logic with multiple orders of different types."""
        created_time = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        current_time = datetime(2024, 1, 1, 12, 10, tzinfo=timezone.utc)
        
        # Create multiple orders
        orders = [
            {'side': 'buy', 'type': 'limit', 'should_cancel': True},
            {'side': 'sell', 'type': 'market', 'should_cancel': True},
            {'side': 'buy', 'type': 'market', 'should_cancel': False},  # Market buy orders aren't canceled for being stale
        ]
        
        for order_config in orders:
            order_intent = Mock()
            order_intent.symbol = 'BTC/USD'
            order_intent.side = Mock()
            order_intent.side.value = order_config['side']
            order_intent.order_type = Mock()
            order_intent.order_type.value = order_config['type']
            order_intent.quantity = Decimal('0.001')
            order_intent.limit_price = Decimal('45000.0') if order_config['type'] == 'limit' else None
            
            self.broker.place_order(order_intent, created_time)
        
        # Check for stale orders
        cancel_events = self.broker._check_stale_orders(current_time)
        
        # Should cancel 2 orders (stale buy limit and stuck sell market)
        assert len(cancel_events) == 2
        
        canceled_reasons = [event['cancel_reason'] for event in cancel_events]
        assert 'stale_buy_limit' in canceled_reasons
        assert 'stuck_sell_market' in canceled_reasons


class TestPerformanceReporting:
    """Test suite for performance metrics calculation and reporting."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.portfolio = SimulatedPortfolio(starting_cash=Decimal('10000.0'))
        
        # Add some realized P/L and fees
        self.portfolio.realized_pnl = Decimal('150.50')
        self.portfolio.total_fees = Decimal('5.25')
        
        # Create sample completed trades
        self.completed_trades = [
            CompletedTrade(
                asset_symbol='BTC/USD',
                entry_timestamp=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
                exit_timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                entry_price=Decimal('50000.0'),
                exit_price=Decimal('51000.0'),
                quantity=Decimal('0.1'),
                realized_pnl=Decimal('100.0'),
                trade_type='take_profit',
                safety_orders_used=1
            ),
            CompletedTrade(
                asset_symbol='BTC/USD',
                entry_timestamp=datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc),
                exit_timestamp=datetime(2024, 1, 1, 16, 0, tzinfo=timezone.utc),
                entry_price=Decimal('49000.0'),
                exit_price=Decimal('50500.0'),
                quantity=Decimal('0.05'),
                realized_pnl=Decimal('75.0'),
                trade_type='take_profit',
                safety_orders_used=2
            ),
            CompletedTrade(
                asset_symbol='BTC/USD',
                entry_timestamp=datetime(2024, 1, 1, 18, 0, tzinfo=timezone.utc),
                exit_timestamp=datetime(2024, 1, 1, 20, 0, tzinfo=timezone.utc),
                entry_price=Decimal('52000.0'),
                exit_price=Decimal('51500.0'),
                quantity=Decimal('0.02'),
                realized_pnl=Decimal('-10.0'),
                trade_type='take_profit',
                safety_orders_used=0
            )
        ]
        
    @pytest.mark.unit
    def test_performance_metrics_calculation(self):
        """Test calculation of performance metrics."""
        current_prices = {'BTC/USD': Decimal('50000.0')}
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 2, tzinfo=timezone.utc)
        
        metrics = calculate_performance_metrics(
            self.portfolio,
            self.completed_trades,
            current_prices,
            start_time,
            end_time
        )
        
        # Verify basic metrics
        assert metrics.total_realized_pnl == Decimal('150.50')
        assert metrics.total_trades == 3
        assert metrics.winning_trades == 2
        assert metrics.losing_trades == 1
        # Round win rate to 2 decimal places for comparison
        assert round(metrics.win_rate, 2) == Decimal('66.67')  # 2/3 * 100 rounded
        assert metrics.total_fees_paid == Decimal('5.25')
        
    @pytest.mark.unit
    def test_performance_metrics_with_no_trades(self):
        """Test performance metrics calculation with no completed trades."""
        current_prices = {'BTC/USD': Decimal('50000.0')}
        start_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        end_time = datetime(2024, 1, 2, tzinfo=timezone.utc)
        
        empty_portfolio = SimulatedPortfolio()
        
        metrics = calculate_performance_metrics(
            empty_portfolio,
            [],
            current_prices,
            start_time,
            end_time
        )
        
        # Verify zero trade metrics
        assert metrics.total_trades == 0
        assert metrics.winning_trades == 0
        assert metrics.losing_trades == 0
        assert metrics.win_rate == Decimal('0')
        assert metrics.average_pnl_per_trade == Decimal('0')
        
    @pytest.mark.unit
    def test_win_rate_calculation(self):
        """Test win rate calculation with different scenarios."""
        # All winning trades
        winning_trades = [
            CompletedTrade('BTC/USD', datetime.now(timezone.utc), datetime.now(timezone.utc),
                          Decimal('50000'), Decimal('51000'), Decimal('0.1'), Decimal('100'), 'take_profit', 0),
            CompletedTrade('BTC/USD', datetime.now(timezone.utc), datetime.now(timezone.utc),
                          Decimal('49000'), Decimal('50000'), Decimal('0.1'), Decimal('100'), 'take_profit', 0)
        ]
        
        metrics = calculate_performance_metrics(
            self.portfolio, winning_trades, {}, datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
        
        assert metrics.win_rate == Decimal('100.0')
        
        # All losing trades
        losing_trades = [
            CompletedTrade('BTC/USD', datetime.now(timezone.utc), datetime.now(timezone.utc),
                          Decimal('51000'), Decimal('50000'), Decimal('0.1'), Decimal('-100'), 'take_profit', 0),
            CompletedTrade('BTC/USD', datetime.now(timezone.utc), datetime.now(timezone.utc),
                          Decimal('50000'), Decimal('49000'), Decimal('0.1'), Decimal('-100'), 'take_profit', 0)
        ]
        
        metrics = calculate_performance_metrics(
            self.portfolio, losing_trades, {}, datetime.now(timezone.utc), datetime.now(timezone.utc)
        )
        
        assert metrics.win_rate == Decimal('0.0')


class TestCancellationEventProcessing:
    """Test suite for cancellation event processing in BacktestSimulation."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.mock_asset = Mock(spec=DcaAsset)
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.cooldown_period = 300
        
        self.portfolio = SimulatedPortfolio()
        self.broker = BrokerSimulator(self.portfolio)
        self.simulation = BacktestSimulation(self.mock_asset, self.portfolio, self.broker)
        
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cancellation_event_processing(self):
        """Test processing of order cancellation events."""
        # Set up cycle with pending order
        self.simulation.current_cycle.latest_order_id = 'sim_order_1'
        self.simulation.current_cycle.status = 'buying'
        
        # Create cancellation event
        cancel_event = {
            'event': 'order_canceled',
            'id': 'sim_order_1',
            'symbol': 'BTC/USD',
            'side': 'buy',
            'status': 'canceled',
            'cancel_reason': 'stale_buy_limit',
            'created_at': '2024-01-01T12:00:00Z',
            'canceled_at': '2024-01-01T12:05:00Z'
        }
        
        current_time = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        
        # Process cancellation event
        await self.simulation.process_cancellation_event(cancel_event, 'BTC/USD', current_time)
        
        # Verify cycle state was updated
        assert self.simulation.current_cycle.latest_order_id is None
        assert self.simulation.current_cycle.status == 'watching'
        
    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_cancellation_event_for_non_current_order(self):
        """Test cancellation event for an order that's not the current one."""
        # Set up cycle with different order
        self.simulation.current_cycle.latest_order_id = 'sim_order_2'
        self.simulation.current_cycle.status = 'buying'
        
        # Create cancellation event for different order
        cancel_event = {
            'event': 'order_canceled',
            'id': 'sim_order_1',
            'symbol': 'BTC/USD',
            'side': 'buy',
            'status': 'canceled',
            'cancel_reason': 'stale_buy_limit',
            'created_at': '2024-01-01T12:00:00Z',
            'canceled_at': '2024-01-01T12:05:00Z'
        }
        
        current_time = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        
        # Process cancellation event
        await self.simulation.process_cancellation_event(cancel_event, 'BTC/USD', current_time)
        
        # Verify cycle state was NOT changed (different order)
        assert self.simulation.current_cycle.latest_order_id == 'sim_order_2'
        assert self.simulation.current_cycle.status == 'buying'


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 