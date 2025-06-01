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
        """Test portfolio initialization with default values."""
        assert self.portfolio.starting_cash == Decimal('10000.0')
        assert self.portfolio.cash_balance == Decimal('10000.0')
        assert self.portfolio.positions == {}
        assert self.portfolio.realized_pnl == Decimal('0.0')
        assert self.portfolio.total_fees == Decimal('0.0')
        
    @pytest.mark.unit
    def test_update_on_buy_first_purchase(self):
        """Test first purchase updates portfolio correctly."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        price = Decimal('50000.0')
        fee = Decimal('5.0')
        
        self.portfolio.update_on_buy(symbol, quantity, price, fee)
        
        # Check cash is reduced by total cost
        expected_cash = Decimal('10000.0') - (quantity * price + fee)
        assert self.portfolio.cash_balance == expected_cash
        
        # Check position is created
        assert symbol in self.portfolio.positions
        assert self.portfolio.positions[symbol]['quantity'] == quantity
        assert self.portfolio.positions[symbol]['weighted_avg_price'] == price
        
        # Check fees
        assert self.portfolio.total_fees == fee
        
    @pytest.mark.unit
    def test_update_on_buy_additional_purchase(self):
        """Test additional purchase updates weighted average correctly."""
        symbol = 'BTC/USD'
        
        # First purchase - use smaller amounts to stay within cash limits
        self.portfolio.update_on_buy(symbol, Decimal('0.05'), Decimal('50000.0'))
        
        # Second purchase at different price - $48k so we have enough cash
        self.portfolio.update_on_buy(symbol, Decimal('0.05'), Decimal('48000.0'))
        
        # Check total quantity
        assert self.portfolio.positions[symbol]['quantity'] == Decimal('0.1')
        
        # Check weighted average price: (0.05*50000 + 0.05*48000) / 0.1 = 49000
        expected_avg = Decimal('49000.0')
        assert self.portfolio.positions[symbol]['weighted_avg_price'] == expected_avg
        
    @pytest.mark.unit
    def test_update_on_buy_insufficient_cash(self):
        """Test buy operation with insufficient cash."""
        symbol = 'BTC/USD'
        quantity = Decimal('1.0')  # 1 BTC
        price = Decimal('60000.0')  # $60k per BTC (more than $10k cash)
        
        initial_cash = self.portfolio.cash_balance
        
        # This should fail silently and not change anything
        self.portfolio.update_on_buy(symbol, quantity, price)
        
        assert self.portfolio.cash_balance == initial_cash  # Unchanged
        assert symbol not in self.portfolio.positions  # No position created
        
    @pytest.mark.unit
    def test_update_on_sell_full_position(self):
        """Test selling entire position."""
        symbol = 'BTC/USD'
        buy_quantity = Decimal('0.1')
        buy_price = Decimal('50000.0')
        sell_price = Decimal('55000.0')
        
        # First buy
        self.portfolio.update_on_buy(symbol, buy_quantity, buy_price)
        initial_cash = self.portfolio.cash_balance
        
        # Then sell all
        realized_pnl = self.portfolio.update_on_sell(symbol, buy_quantity, sell_price)
        
        # Check position is removed
        assert symbol not in self.portfolio.positions
        
        # Check cash increased by sale proceeds
        expected_cash_increase = buy_quantity * sell_price
        assert self.portfolio.cash_balance == initial_cash + expected_cash_increase
        
        # Check realized P/L
        expected_pnl = buy_quantity * (sell_price - buy_price)
        assert realized_pnl == expected_pnl
        assert self.portfolio.realized_pnl == expected_pnl
        
    @pytest.mark.unit
    def test_update_on_sell_partial_position(self):
        """Test selling part of position."""
        symbol = 'BTC/USD'
        buy_quantity = Decimal('0.2')
        buy_price = Decimal('50000.0')
        sell_quantity = Decimal('0.1')
        sell_price = Decimal('55000.0')
        
        # First buy
        self.portfolio.update_on_buy(symbol, buy_quantity, buy_price)
        
        # Then sell partial
        realized_pnl = self.portfolio.update_on_sell(symbol, sell_quantity, sell_price)
        
        # Check remaining position
        remaining_quantity = buy_quantity - sell_quantity
        assert self.portfolio.positions[symbol]['quantity'] == remaining_quantity
        assert self.portfolio.positions[symbol]['weighted_avg_price'] == buy_price  # Unchanged
        
        # Check realized P/L
        expected_pnl = sell_quantity * (sell_price - buy_price)
        assert realized_pnl == expected_pnl
        
    @pytest.mark.unit
    def test_update_on_sell_insufficient_position(self):
        """Test selling more than available position."""
        symbol = 'BTC/USD'
        
        # Try to sell without any position
        initial_cash = self.portfolio.cash_balance
        realized_pnl = self.portfolio.update_on_sell(symbol, Decimal('0.1'), Decimal('50000.0'))
        
        # Should return 0 P/L and not change cash
        assert realized_pnl == Decimal('0.0')
        assert self.portfolio.cash_balance == initial_cash
        
    @pytest.mark.unit
    def test_get_position_methods(self):
        """Test position getter methods."""
        symbol = 'BTC/USD'
        quantity = Decimal('0.1')
        price = Decimal('50000.0')
        
        # Test with no position
        assert self.portfolio.get_position_qty(symbol) == Decimal('0.0')
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
        
        # Buy position
        self.portfolio.update_on_buy(symbol, quantity, buy_price)
        
        # Calculate portfolio value
        current_prices = {symbol: current_price}
        position_value = quantity * current_price
        expected_total = self.portfolio.cash_balance + position_value
        
        assert self.portfolio.get_portfolio_value(current_prices) == expected_total


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