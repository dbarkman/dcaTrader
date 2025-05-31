#!/usr/bin/env python3
"""
Unit tests for Phase 4 backtesting: BrokerSimulator and SimulatedPortfolio.

These tests verify:
1. SimulatedPortfolio cash and position management
2. BrokerSimulator order placement and fill logic
3. Integration with historical bar data for realistic fills
4. P/L calculations and portfolio tracking
"""

import pytest
import sys
import os
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import Mock, patch

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from run_backtest import SimulatedPortfolio, BrokerSimulator, SimulatedOrder
from models.backtest_structs import OrderIntent, OrderSide, OrderType


class TestSimulatedPortfolio:
    """Test SimulatedPortfolio cash and position management."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.portfolio = SimulatedPortfolio(starting_cash=Decimal('10000.0'))
        
    @pytest.mark.unit
    def test_portfolio_initialization(self):
        """Test portfolio initializes with correct starting values."""
        assert self.portfolio.starting_cash == Decimal('10000.0')
        assert self.portfolio.cash == Decimal('10000.0')
        assert self.portfolio.positions == {}
        assert self.portfolio.total_fees_paid == Decimal('0.0')
        assert self.portfolio.realized_pnl == Decimal('0.0')
        
    @pytest.mark.unit
    def test_update_on_buy_first_purchase(self):
        """Test first buy updates portfolio correctly."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        price = Decimal('50000.0')
        fee = Decimal('5.0')
        
        self.portfolio.update_on_buy(symbol, quantity, price, fee)
        
        # Check cash reduction
        expected_cash = Decimal('10000.0') - (quantity * price + fee)
        assert self.portfolio.cash == expected_cash
        
        # Check position creation
        assert symbol in self.portfolio.positions
        assert self.portfolio.positions[symbol]['quantity'] == quantity
        assert self.portfolio.positions[symbol]['average_entry_price'] == price
        
        # Check fee tracking
        assert self.portfolio.total_fees_paid == fee
        
    @pytest.mark.unit
    def test_update_on_buy_additional_purchase(self):
        """Test additional buy calculates weighted average correctly."""
        symbol = 'BTC/USD'
        
        # First purchase
        first_qty = Decimal('0.1')
        first_price = Decimal('50000.0')
        self.portfolio.update_on_buy(symbol, first_qty, first_price)
        
        # Second purchase
        second_qty = Decimal('0.05')
        second_price = Decimal('48000.0')
        self.portfolio.update_on_buy(symbol, second_qty, second_price)
        
        # Verify weighted average calculation
        total_qty = first_qty + second_qty
        expected_avg = ((first_qty * first_price) + (second_qty * second_price)) / total_qty
        
        assert self.portfolio.positions[symbol]['quantity'] == total_qty
        assert self.portfolio.positions[symbol]['average_entry_price'] == expected_avg
        
    @pytest.mark.unit
    def test_update_on_buy_insufficient_cash(self):
        """Test buy with insufficient cash is rejected."""
        symbol = 'BTC/USD'
        quantity = Decimal('1.0')
        price = Decimal('100000.0')  # Would cost $100k, but only have $10k
        
        initial_cash = self.portfolio.cash
        
        self.portfolio.update_on_buy(symbol, quantity, price)
        
        # Should not have changed cash or created position
        assert self.portfolio.cash == initial_cash
        assert symbol not in self.portfolio.positions
        
    @pytest.mark.unit
    def test_update_on_sell_full_position(self):
        """Test selling full position calculates P/L correctly."""
        symbol = 'BTC/USD'
        
        # Setup position
        buy_qty = Decimal('0.1')
        buy_price = Decimal('50000.0')
        self.portfolio.update_on_buy(symbol, buy_qty, buy_price)
        
        initial_cash = self.portfolio.cash
        
        # Sell at profit
        sell_price = Decimal('55000.0')
        fee = Decimal('5.0')
        
        pnl = self.portfolio.update_on_sell(symbol, buy_qty, sell_price, fee)
        
        # Check P/L calculation
        expected_pnl = (sell_price - buy_price) * buy_qty - fee
        assert pnl == expected_pnl
        
        # Check cash increase
        expected_cash_increase = (buy_qty * sell_price) - fee
        assert self.portfolio.cash == initial_cash + expected_cash_increase
        
        # Check position removed
        assert symbol not in self.portfolio.positions
        
        # Check realized P/L tracking
        assert self.portfolio.realized_pnl == expected_pnl
        
    @pytest.mark.unit
    def test_update_on_sell_partial_position(self):
        """Test selling partial position maintains remaining position."""
        symbol = 'BTC/USD'
        
        # Setup position
        buy_qty = Decimal('0.1')
        buy_price = Decimal('50000.0')
        self.portfolio.update_on_buy(symbol, buy_qty, buy_price)
        
        # Sell half
        sell_qty = Decimal('0.05')
        sell_price = Decimal('55000.0')
        
        pnl = self.portfolio.update_on_sell(symbol, sell_qty, sell_price)
        
        # Check remaining position
        remaining_qty = buy_qty - sell_qty
        assert self.portfolio.positions[symbol]['quantity'] == remaining_qty
        assert self.portfolio.positions[symbol]['average_entry_price'] == buy_price  # Unchanged
        
        # Check P/L for partial sell
        expected_pnl = (sell_price - buy_price) * sell_qty
        assert pnl == expected_pnl
        
    @pytest.mark.unit
    def test_update_on_sell_insufficient_position(self):
        """Test selling more than owned is rejected."""
        symbol = 'BTC/USD'
        
        # Setup small position
        buy_qty = Decimal('0.05')
        buy_price = Decimal('50000.0')
        self.portfolio.update_on_buy(symbol, buy_qty, buy_price)
        
        initial_cash = self.portfolio.cash
        initial_position = self.portfolio.positions[symbol].copy()
        
        # Try to sell more than owned
        sell_qty = Decimal('0.1')  # More than the 0.05 owned
        sell_price = Decimal('55000.0')
        
        pnl = self.portfolio.update_on_sell(symbol, sell_qty, sell_price)
        
        # Should not have changed anything
        assert pnl == Decimal('0.0')
        assert self.portfolio.cash == initial_cash
        assert self.portfolio.positions[symbol] == initial_position
        
    @pytest.mark.unit
    def test_get_position_methods(self):
        """Test position getter methods."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        price = Decimal('50000.0')
        
        # Test with no position
        assert self.portfolio.get_position_qty(symbol) == Decimal('0')
        assert self.portfolio.get_position_avg_price(symbol) is None
        
        # Add position
        self.portfolio.update_on_buy(symbol, quantity, price)
        
        # Test with position
        assert self.portfolio.get_position_qty(symbol) == quantity
        assert self.portfolio.get_position_avg_price(symbol) == price
        
    @pytest.mark.unit
    def test_get_portfolio_value(self):
        """Test portfolio value calculation."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        buy_price = Decimal('50000.0')
        current_price = Decimal('55000.0')
        
        # Add position
        self.portfolio.update_on_buy(symbol, quantity, buy_price)
        
        # Calculate portfolio value
        current_prices = {symbol: current_price}
        total_value = self.portfolio.get_portfolio_value(current_prices)
        
        # Should be cash + position value
        position_value = quantity * current_price
        expected_total = self.portfolio.cash + position_value
        
        assert total_value == expected_total
        
    @pytest.mark.unit
    def test_get_unrealized_pnl(self):
        """Test unrealized P/L calculation."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        buy_price = Decimal('50000.0')
        current_price = Decimal('55000.0')
        
        # Add position
        self.portfolio.update_on_buy(symbol, quantity, buy_price)
        
        # Calculate unrealized P/L
        current_prices = {symbol: current_price}
        unrealized_pnl = self.portfolio.get_unrealized_pnl(current_prices)
        
        # Should be (current_price - buy_price) * quantity
        expected_pnl = (current_price - buy_price) * quantity
        assert unrealized_pnl == expected_pnl


class TestBrokerSimulator:
    """Test BrokerSimulator order placement and fill logic."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.portfolio = SimulatedPortfolio(starting_cash=Decimal('10000.0'))
        self.broker = BrokerSimulator(self.portfolio)
        
    @pytest.mark.unit
    def test_broker_initialization(self):
        """Test broker initializes correctly."""
        assert self.broker.portfolio == self.portfolio
        assert self.broker.slippage_pct == Decimal('0.05')
        assert self.broker.open_orders == []
        assert self.broker.order_counter == 0
        
    @pytest.mark.unit
    def test_place_order_market_buy(self):
        """Test placing a market buy order."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.1'),
            limit_price=None
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Verify order creation
        assert order_id == 'sim_order_1'
        assert len(self.broker.open_orders) == 1
        
        order = self.broker.open_orders[0]
        assert order.sim_order_id == order_id
        assert order.asset_symbol == 'BTC/USD'
        assert order.side == 'BUY'
        assert order.order_type == 'MARKET'
        assert order.quantity == Decimal('0.1')
        assert order.status == 'open'
        
    @pytest.mark.unit
    def test_place_order_limit_sell(self):
        """Test placing a limit sell order."""
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.05'),
            limit_price=Decimal('60000.0')
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Verify order creation
        order = self.broker.open_orders[0]
        assert order.side == 'SELL'
        assert order.order_type == 'LIMIT'
        assert order.limit_price == Decimal('60000.0')
        
    @pytest.mark.unit
    def test_market_buy_order_fill(self):
        """Test market buy order fills immediately with slippage."""
        # Place market buy order
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.1'),
            limit_price=None
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Create bar data
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('51000.0'),
            'low': Decimal('49000.0'),
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Verify fill
        assert len(fills) == 1
        fill = fills[0]
        
        # Market buy should fill at open + slippage
        expected_fill_price = bar['open'] * (Decimal('1') + self.broker.slippage_pct / Decimal('100'))
        
        assert fill['id'] == order_id
        assert fill['side'] == 'buy'
        assert Decimal(fill['filled_avg_price']) == expected_fill_price
        
        # Order should be removed from open orders
        assert len(self.broker.open_orders) == 0
        
    @pytest.mark.unit
    def test_market_sell_order_fill(self):
        """Test market sell order fills immediately with slippage."""
        # Place market sell order
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.SELL,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.1'),
            limit_price=None
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Create bar data
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('51000.0'),
            'low': Decimal('49000.0'),
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Verify fill
        assert len(fills) == 1
        fill = fills[0]
        
        # Market sell should fill at open - slippage
        expected_fill_price = bar['open'] * (Decimal('1') - self.broker.slippage_pct / Decimal('100'))
        
        assert Decimal(fill['filled_avg_price']) == expected_fill_price
        
    @pytest.mark.unit
    def test_limit_buy_order_fill(self):
        """Test limit buy order fills when price drops to limit."""
        # Place limit buy order
        limit_price = Decimal('49500.0')
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.1'),
            limit_price=limit_price
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Create bar where low touches limit price
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('51000.0'),
            'low': Decimal('49000.0'),  # Below limit price
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Verify fill at limit price (or better)
        assert len(fills) == 1
        fill = fills[0]
        
        # Should fill at the better of open or limit price
        expected_fill_price = min(bar['open'], limit_price)
        assert Decimal(fill['filled_avg_price']) == expected_fill_price
        
    @pytest.mark.unit
    def test_limit_buy_order_no_fill(self):
        """Test limit buy order doesn't fill when price doesn't reach limit."""
        # Place limit buy order
        limit_price = Decimal('48000.0')
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.1'),
            limit_price=limit_price
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Create bar where low doesn't reach limit price
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('51000.0'),
            'low': Decimal('49000.0'),  # Above limit price
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Should not fill
        assert len(fills) == 0
        assert len(self.broker.open_orders) == 1  # Order still open
        
    @pytest.mark.unit
    def test_limit_sell_order_fill(self):
        """Test limit sell order fills when price rises to limit."""
        # Place limit sell order
        limit_price = Decimal('52000.0')
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.1'),
            limit_price=limit_price
        )
        
        current_time = datetime.now(timezone.utc)
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Create bar where high reaches limit price
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('53000.0'),  # Above limit price
            'low': Decimal('49000.0'),
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Verify fill at limit price (or better)
        assert len(fills) == 1
        fill = fills[0]
        
        # Should fill at the better of open or limit price
        expected_fill_price = max(bar['open'], limit_price)
        assert Decimal(fill['filled_avg_price']) == expected_fill_price
        
    @pytest.mark.unit
    def test_multiple_orders_processing(self):
        """Test processing multiple orders in one bar."""
        current_time = datetime.now(timezone.utc)
        
        # Place multiple orders
        orders = []
        
        # Market buy
        market_buy = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            quantity=Decimal('0.1'),
            limit_price=None
        )
        orders.append(self.broker.place_order(market_buy, current_time))
        
        # Limit sell that will fill
        limit_sell = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.SELL,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.05'),
            limit_price=Decimal('51000.0')
        )
        orders.append(self.broker.place_order(limit_sell, current_time))
        
        # Limit buy that won't fill
        limit_buy = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.02'),
            limit_price=Decimal('48000.0')
        )
        orders.append(self.broker.place_order(limit_buy, current_time))
        
        # Create bar data
        bar = {
            'open': Decimal('50000.0'),
            'high': Decimal('52000.0'),  # High enough for limit sell
            'low': Decimal('49000.0'),   # Not low enough for limit buy
            'close': Decimal('50500.0')
        }
        
        # Process fills
        fills = self.broker.process_bar_fills(bar, current_time)
        
        # Should have 2 fills (market buy + limit sell)
        assert len(fills) == 2
        
        # Should have 1 remaining open order (limit buy)
        assert len(self.broker.open_orders) == 1
        assert self.broker.open_orders[0].order_type == 'LIMIT'
        assert self.broker.open_orders[0].side == 'BUY'
        
    @pytest.mark.unit
    def test_cancel_all_orders(self):
        """Test canceling all open orders."""
        current_time = datetime.now(timezone.utc)
        
        # Place multiple orders
        for i in range(3):
            order_intent = OrderIntent(
                symbol='BTC/USD',
                side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                quantity=Decimal('0.1'),
                limit_price=Decimal('48000.0')
            )
            self.broker.place_order(order_intent, current_time)
            
        assert len(self.broker.open_orders) == 3
        
        # Cancel all orders
        canceled_count = self.broker.cancel_all_orders()
        
        assert canceled_count == 3
        assert len(self.broker.open_orders) == 0
        
    @pytest.mark.unit 
    def test_get_order_status(self):
        """Test getting order status."""
        current_time = datetime.now(timezone.utc)
        
        # Place order
        order_intent = OrderIntent(
            symbol='BTC/USD',
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal('0.1'),
            limit_price=Decimal('48000.0')
        )
        order_id = self.broker.place_order(order_intent, current_time)
        
        # Check status
        status = self.broker.get_order_status(order_id)
        assert status == 'open'
        
        # Check non-existent order
        status = self.broker.get_order_status('non_existent_order')
        assert status is None


if __name__ == '__main__':
    pytest.main([__file__, '-v']) 