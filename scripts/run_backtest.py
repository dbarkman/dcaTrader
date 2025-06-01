#!/usr/bin/env python3
"""
Enhanced DCA Backtesting Engine - Phase 5
Includes broker simulation, portfolio management, cooldown management, 
stale order cancellation, and performance reporting.

This script creates a complete backtesting engine that:
1. Reads historical 1-minute bars from the database
2. Feeds them to our refactored strategy logic
3. Simulates order execution via Broker Simulator
4. Manages portfolio state and integrates with existing fill handlers
5. Provides comprehensive P/L tracking and state management

Usage:
    python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2024-01-01" --end-date "2024-01-02"
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Iterator, Optional, Any
from dataclasses import dataclass
import traceback
import asyncio

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

# Project imports
from config import config
from utils.logging_config import setup_logging
from utils.db_utils import get_db_connection, execute_query
from models.asset_config import DcaAsset, get_asset_config
from models.cycle_data import DcaCycle
from strategy_logic import decide_base_order_action, decide_safety_order_action, decide_take_profit_action
from models.backtest_structs import MarketTickInput, StrategyAction

# Add imports for the existing fill handlers
# ... existing code ...
from strategy_logic import decide_base_order_action, decide_safety_order_action, decide_take_profit_action
from models.backtest_structs import MarketTickInput, StrategyAction

# Add imports for fill handlers (we'll need to modify these to work in backtest mode)
try:
    # Import the existing fill handler functions
    import importlib.util
    main_app_path = os.path.join(os.path.dirname(__file__), '..', 'src', 'main_app.py')
    spec = importlib.util.spec_from_file_location("main_app", main_app_path)
    main_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(main_app)
    
    # Access the functions from main_app
    update_cycle_on_buy_fill_live = main_app.update_cycle_on_buy_fill
    update_cycle_on_sell_fill_live = main_app.update_cycle_on_sell_fill
    
except Exception as e:
    logging.warning(f"Could not import live fill handlers: {e}")
    update_cycle_on_buy_fill_live = None
    update_cycle_on_sell_fill_live = None

# Phase 5 Configuration Constants
STALE_ORDER_THRESHOLD_MINUTES = 5  # Cancel stale BUY limit orders after 5 minutes
STUCK_MARKET_SELL_TIMEOUT_SECONDS = 120  # Cancel stuck SELL market orders after 2 minutes
BAR_INTERVAL_MINUTES = 1  # Assuming 1-minute bars for time calculations

# Convert time thresholds to bar counts (for 1-minute bars)
STALE_ORDER_THRESHOLD_BARS = STALE_ORDER_THRESHOLD_MINUTES
STUCK_MARKET_SELL_TIMEOUT_BARS = STUCK_MARKET_SELL_TIMEOUT_SECONDS // 60  # Convert to minutes

@dataclass
class CompletedTrade:
    """Represents a completed trading cycle for performance reporting."""
    asset_symbol: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    realized_pnl: Decimal
    trade_type: str  # 'take_profit', 'stop_loss', etc.
    safety_orders_used: int

@dataclass
class PerformanceMetrics:
    """Container for backtesting performance metrics."""
    total_realized_pnl: Decimal
    total_unrealized_pnl: Decimal
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    average_pnl_per_trade: Decimal
    max_drawdown: Decimal
    total_fees_paid: Decimal
    final_portfolio_value: Decimal
    
    @property
    def total_pnl(self) -> Decimal:
        return self.total_realized_pnl + self.total_unrealized_pnl

@dataclass
class SimulatedOrder:
    """
    Represents a simulated order in the backtesting environment.
    """
    sim_order_id: str
    asset_symbol: str
    side: str  # 'BUY' or 'SELL'
    order_type: str  # 'MARKET' or 'LIMIT'
    quantity: Decimal
    limit_price: Optional[Decimal]
    status: str  # 'open', 'filled', 'canceled'
    created_at_bar_timestamp: datetime
    filled_price: Optional[Decimal] = None
    filled_at_bar_timestamp: Optional[datetime] = None


class SimulatedPortfolio:
    """
    Manages simulated portfolio state for backtesting.
    Tracks cash balance, positions, and performance metrics.
    """
    
    def __init__(self, starting_cash: Decimal = Decimal('10000.0')):
        """Initialize portfolio with starting cash."""
        self.starting_cash = starting_cash
        self.cash_balance = starting_cash
        self.positions: Dict[str, Dict[str, Decimal]] = {}  # symbol -> {qty, weighted_avg_price}
        self.realized_pnl = Decimal('0.0')
        self.total_fees = Decimal('0.0')
        self.completed_trades: List[CompletedTrade] = []  # Track completed trades for reporting
        self.logger = logging.getLogger('portfolio_sim')
        
    def update_on_buy(self, symbol: str, quantity: Decimal, price: Decimal, fee: Decimal = Decimal('0.0')) -> None:
        """
        Update portfolio on a buy transaction.
        
        Args:
            symbol: Asset symbol
            quantity: Quantity purchased
            price: Purchase price per unit
            fee: Transaction fee
        """
        total_cost = quantity * price + fee
        
        # Check if we have sufficient cash
        if total_cost > self.cash_balance:
            self.logger.warning(f"💸 Insufficient cash for buy: need ${total_cost:.3f}, have ${self.cash_balance:.3f}")
            return
            
        # Update cash balance
        self.cash_balance -= total_cost
        self.total_fees += fee
        
        # Update position with weighted average
        if symbol not in self.positions:
            self.positions[symbol] = {
                'quantity': quantity,
                'weighted_avg_price': price
            }
        else:
            current_qty = self.positions[symbol]['quantity']
            current_avg_price = self.positions[symbol]['weighted_avg_price']
            
            # Calculate new weighted average
            total_value = (current_qty * current_avg_price) + (quantity * price)
            new_quantity = current_qty + quantity
            new_avg_price = total_value / new_quantity
            
            self.positions[symbol] = {
                'quantity': new_quantity,
                'weighted_avg_price': new_avg_price
            }
            
        self.logger.info(f"💰 BUY: {quantity} {symbol} @ ${price:.2f} | "
                        f"Position: {self.positions[symbol]['quantity']:.6f} @ "
                        f"${self.positions[symbol]['weighted_avg_price']:.2f} avg | "
                        f"Cash: ${self.cash_balance:.2f}")

    def update_on_sell(self, symbol: str, quantity: Decimal, price: Decimal, fee: Decimal = Decimal('0.0')) -> Decimal:
        """
        Update portfolio on a sell transaction.
        
        Args:
            symbol: Asset symbol
            quantity: Quantity sold
            price: Sale price per unit
            fee: Transaction fee
            
        Returns:
            Realized P/L from this sale
        """
        if symbol not in self.positions:
            self.logger.warning(f"💸 Cannot sell {symbol}: no position exists")
            return Decimal('0.0')
            
        current_qty = self.positions[symbol]['quantity']
        if quantity > current_qty:
            self.logger.warning(f"💸 Insufficient position for sell: need {quantity}, have {current_qty}")
            return Decimal('0.0')
            
        # Calculate realized P/L
        avg_price = self.positions[symbol]['weighted_avg_price']
        sale_proceeds = quantity * price - fee
        cost_basis = quantity * avg_price
        realized_pnl = sale_proceeds - cost_basis
        
        # Update cash and fees
        self.cash_balance += sale_proceeds
        self.total_fees += fee
        self.realized_pnl += realized_pnl
        
        # Update position
        remaining_qty = current_qty - quantity
        if remaining_qty <= Decimal('0.000001'):  # Close position if very small remainder
            del self.positions[symbol]
            self.logger.info(f"📊 Position closed for {symbol}")
        else:
            self.positions[symbol]['quantity'] = remaining_qty
            # Keep same weighted average price for remaining position
            
        self.logger.info(f"💰 SELL: {quantity} {symbol} @ ${price:.2f} | "
                        f"Realized P/L: ${realized_pnl:.2f} | "
                        f"Remaining: {remaining_qty:.6f} | "
                        f"Cash: ${self.cash_balance:.2f}")
                        
        return realized_pnl

    def get_position_qty(self, symbol: str) -> Decimal:
        """Get current position quantity for a symbol."""
        return self.positions.get(symbol, {}).get('quantity', Decimal('0.0'))

    def get_position_avg_price(self, symbol: str) -> Optional[Decimal]:
        """Get weighted average price for a position."""
        return self.positions.get(symbol, {}).get('weighted_avg_price')

    def get_portfolio_value(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """
        Calculate total portfolio value including cash and positions.
        
        Args:
            current_prices: Dict of symbol -> current_price
            
        Returns:
            Total portfolio value
        """
        total_value = self.cash_balance
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                position_value = position['quantity'] * current_prices[symbol]
                total_value += position_value
                
        return total_value

    def get_unrealized_pnl(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """
        Calculate unrealized P/L for open positions.
        
        Args:
            current_prices: Dict of symbol -> current_price
            
        Returns:
            Total unrealized P/L
        """
        unrealized_pnl = Decimal('0.0')
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                current_value = position['quantity'] * current_prices[symbol]
                cost_basis = position['quantity'] * position['weighted_avg_price']
                unrealized_pnl += (current_value - cost_basis)
                
        return unrealized_pnl
        
    def record_completed_trade(self, trade: CompletedTrade) -> None:
        """Record a completed trade for performance reporting."""
        self.completed_trades.append(trade)
        self.logger.info(f"📊 Trade completed: {trade.trade_type} | "
                        f"P/L: ${trade.realized_pnl:.2f} | "
                        f"Safety orders: {trade.safety_orders_used}")

    def log_portfolio_summary(self, current_prices: Dict[str, Decimal] = None) -> None:
        """Log detailed portfolio summary."""
        if current_prices is None:
            current_prices = {}
            
        portfolio_value = self.get_portfolio_value(current_prices)
        unrealized_pnl = self.get_unrealized_pnl(current_prices)
        total_pnl = self.realized_pnl + unrealized_pnl
        
        self.logger.info("💼 PORTFOLIO SUMMARY:")
        self.logger.info(f"   💰 Cash Balance: ${self.cash_balance:.2f}")
        self.logger.info(f"   🎯 Total Portfolio Value: ${portfolio_value:.2f}")
        self.logger.info(f"   📈 Realized P/L: ${self.realized_pnl:.2f}")
        self.logger.info(f"   📊 Unrealized P/L: ${unrealized_pnl:.2f}")
        self.logger.info(f"   🏆 Total P/L: ${total_pnl:.2f} ({total_pnl/self.starting_cash*100:.2f}%)")
        self.logger.info(f"   💸 Total Fees: ${self.total_fees:.2f}")
        self.logger.info(f"   📊 Completed Trades: {len(self.completed_trades)}")
        
        # Log positions
        if self.positions:
            self.logger.info("   🎯 OPEN POSITIONS:")
            for symbol, position in self.positions.items():
                current_price = current_prices.get(symbol, Decimal('0.0'))
                position_value = position['quantity'] * current_price if current_price > 0 else Decimal('0.0')
                position_pnl = position_value - (position['quantity'] * position['weighted_avg_price'])
                
                self.logger.info(f"      {symbol}: {position['quantity']:.6f} @ "
                               f"${position['weighted_avg_price']:.2f} avg | "
                               f"Current: ${current_price:.2f} | "
                               f"Value: ${position_value:.2f} | "
                               f"P/L: ${position_pnl:.2f}")


class BrokerSimulator:
    """
    Simulates order execution based on historical bar data.
    Enhanced with stale/stuck order cancellation for Phase 5.
    """
    
    def __init__(self, portfolio: SimulatedPortfolio, slippage_pct: Decimal = Decimal('0.05')):
        """
        Initialize the broker simulator.
        
        Args:
            portfolio: SimulatedPortfolio instance
            slippage_pct: Slippage percentage for market orders (default 0.05%)
        """
        self.portfolio = portfolio
        self.slippage_pct = slippage_pct
        self.open_orders: List[SimulatedOrder] = []
        self.order_counter = 0
        self.logger = logging.getLogger('broker_sim')
        
    def get_next_order_id(self) -> str:
        """Generate unique order ID."""
        self.order_counter += 1
        return f"sim_order_{self.order_counter}"
        
    def place_order(self, order_intent, current_timestamp: datetime) -> str:
        """
        Place a simulated order from strategy intent.
        
        Args:
            order_intent: OrderIntent from strategy logic
            current_timestamp: Current bar timestamp
            
        Returns:
            Simulated order ID
        """
        order_id = self.get_next_order_id()
        
        sim_order = SimulatedOrder(
            sim_order_id=order_id,
            asset_symbol=order_intent.symbol,
            side=order_intent.side.value.upper(),
            order_type=order_intent.order_type.value.upper(),
            quantity=order_intent.quantity,
            limit_price=order_intent.limit_price,
            status='open',
            created_at_bar_timestamp=current_timestamp
        )
        
        self.open_orders.append(sim_order)
        
        self.logger.info(f"📋 ORDER PLACED: {sim_order.side} {sim_order.order_type} - "
                        f"Symbol: {sim_order.asset_symbol}, "
                        f"Quantity: {sim_order.quantity}, "
                        f"Price: {sim_order.limit_price or 'MARKET'}, "
                        f"ID: {order_id}")
                        
        return order_id
        
    def process_bar_fills(self, bar: Dict[str, Any], current_timestamp: datetime) -> List[Dict]:
        """
        Process potential fills for open orders based on current bar data.
        Also handles stale/stuck order cancellation.
        
        Args:
            bar: Historical bar data with OHLC prices
            current_timestamp: Current bar timestamp
            
        Returns:
            List of simulated fill events and cancellation events
        """
        events = []
        orders_to_remove = []
        
        # First, check for stale/stuck orders that need cancellation
        stale_cancel_events = self._check_stale_orders(current_timestamp)
        events.extend(stale_cancel_events)
        
        # Then check for fills on remaining orders
        for order in self.open_orders[:]:  # Create copy since we modify the list
            if order.status == 'canceled':
                orders_to_remove.append(order)
                continue
                
            fill_event = self._check_order_fill(order, bar, current_timestamp)
            if fill_event:
                events.append(fill_event)
                orders_to_remove.append(order)
                
        # Remove filled/canceled orders
        for order in orders_to_remove:
            if order in self.open_orders:
                self.open_orders.remove(order)
            
        return events
        
    def _check_stale_orders(self, current_timestamp: datetime) -> List[Dict]:
        """
        Check for stale/stuck orders that should be canceled.
        
        Args:
            current_timestamp: Current bar timestamp
            
        Returns:
            List of cancellation events
        """
        cancellation_events = []
        
        for order in self.open_orders[:]:  # Copy list since we modify it
            if order.status != 'open':
                continue
                
            # Calculate order age in minutes
            order_age_minutes = (current_timestamp - order.created_at_bar_timestamp).total_seconds() / 60
            
            should_cancel = False
            cancel_reason = ""
            
            # Check for stale BUY limit orders
            if (order.side == 'BUY' and 
                order.order_type == 'LIMIT' and 
                order_age_minutes >= STALE_ORDER_THRESHOLD_MINUTES):
                should_cancel = True
                cancel_reason = "stale_buy_limit"
                
            # Check for stuck SELL market orders
            elif (order.side == 'SELL' and 
                  order.order_type == 'MARKET' and 
                  order_age_minutes >= (STUCK_MARKET_SELL_TIMEOUT_SECONDS / 60)):
                should_cancel = True
                cancel_reason = "stuck_sell_market"
                
            if should_cancel:
                # Mark order as canceled
                order.status = 'canceled'
                
                # Create cancellation event (mimicking Alpaca TradeUpdate for cancellation)
                cancel_event = {
                    'event': 'order_canceled',
                    'id': order.sim_order_id,
                    'symbol': order.asset_symbol,
                    'side': order.side.lower(),
                    'filled_qty': '0',  # Assume no partial fills for simplicity
                    'status': 'canceled',
                    'order_type': order.order_type.lower(),
                    'created_at': order.created_at_bar_timestamp.isoformat(),
                    'canceled_at': current_timestamp.isoformat(),
                    'cancel_reason': cancel_reason
                }
                
                cancellation_events.append(cancel_event)
                
                self.logger.info(f"❌ ORDER CANCELED: {cancel_reason} - "
                               f"{order.side} {order.order_type} {order.asset_symbol} "
                               f"(Age: {order_age_minutes:.1f}min, ID: {order.sim_order_id})")
                
        return cancellation_events
        
    def _check_order_fill(self, order: SimulatedOrder, bar: Dict[str, Any], current_timestamp: datetime) -> Optional[Dict]:
        """
        Check if an order should fill based on bar data.
        
        Args:
            order: SimulatedOrder to check
            bar: Bar data with OHLC
            current_timestamp: Current timestamp
            
        Returns:
            Fill event dict if order fills, None otherwise
        """
        bar_open = bar['open']
        bar_high = bar['high'] 
        bar_low = bar['low']
        bar_close = bar['close']
        
        fill_price = None
        
        if order.order_type == 'MARKET':
            # Market orders fill immediately at open price (with slippage)
            if order.side == 'BUY':
                # Add slippage for buy market orders
                fill_price = bar_open * (Decimal('1') + self.slippage_pct / Decimal('100'))
            else:  # SELL
                # Subtract slippage for sell market orders
                fill_price = bar_open * (Decimal('1') - self.slippage_pct / Decimal('100'))
                
        elif order.order_type == 'LIMIT':
            if order.side == 'BUY':
                # Buy limit fills if bar goes at or below limit price
                if bar_low <= order.limit_price:
                    # Fill at the better of open price or limit price
                    fill_price = min(bar_open, order.limit_price)
            else:  # SELL
                # Sell limit fills if bar goes at or above limit price
                if bar_high >= order.limit_price:
                    # Fill at the better of open price or limit price
                    fill_price = max(bar_open, order.limit_price)
                    
        if fill_price is not None:
            # Update order status
            order.status = 'filled'
            order.filled_price = fill_price
            order.filled_at_bar_timestamp = current_timestamp
            
            # Update portfolio
            if order.side == 'BUY':
                self.portfolio.update_on_buy(order.asset_symbol, order.quantity, fill_price)
            else:  # SELL
                self.portfolio.update_on_sell(order.asset_symbol, order.quantity, fill_price)
                
            # Create fill event (mimicking Alpaca TradeUpdate structure)
            fill_event = {
                'event': 'order_filled',
                'id': order.sim_order_id,
                'symbol': order.asset_symbol,
                'side': order.side.lower(),
                'filled_qty': str(order.quantity),
                'filled_avg_price': str(fill_price),
                'status': 'filled',
                'order_type': order.order_type.lower(),
                'created_at': order.created_at_bar_timestamp.isoformat(),
                'filled_at': current_timestamp.isoformat()
            }
            
            self.logger.info(f"✅ ORDER FILLED: {order.side} {order.quantity} {order.asset_symbol} @ ${fill_price:.2f} (ID: {order.sim_order_id})")
            
            return fill_event
            
        return None
        
    def cancel_all_orders(self) -> int:
        """Cancel all open orders (useful for cleanup)."""
        canceled_count = len(self.open_orders)
        self.open_orders.clear()
        if canceled_count > 0:
            self.logger.info(f"❌ Canceled {canceled_count} open orders")
        return canceled_count
        
    def get_order_status(self, order_id: str) -> Optional[str]:
        """Get status of a specific order."""
        for order in self.open_orders:
            if order.sim_order_id == order_id:
                return order.status
        return None
        
    def get_open_order_count(self) -> int:
        """Get count of open orders."""
        return len([order for order in self.open_orders if order.status == 'open'])


class HistoricalDataFeeder:
    """
    Feeds historical 1-minute bar data from the database for backtesting.
    """
    
    def __init__(self, asset_id: int, start_date: datetime, end_date: datetime):
        """
        Initialize the data feeder.
        
        Args:
            asset_id: Database ID of the asset to fetch data for
            start_date: Start date for historical data (UTC)
            end_date: End date for historical data (UTC)
        """
        self.asset_id = asset_id
        self.start_date = start_date
        self.end_date = end_date
        self._data_cache = None
        
    def fetch_data(self) -> List[Dict[str, Any]]:
        """
        Fetch historical bar data from the database.
        
        Returns:
            List of bar dictionaries with timestamp, open, high, low, close, volume
        """
        if self._data_cache is not None:
            return self._data_cache
            
        query = """
        SELECT timestamp, open_price, high_price, low_price, close_price, volume
        FROM historical_1min_bars
        WHERE asset_id = %s 
        AND timestamp >= %s 
        AND timestamp <= %s
        ORDER BY timestamp ASC
        """
        
        try:
            rows = execute_query(
                query,
                (self.asset_id, self.start_date, self.end_date),
                fetch_all=True
            )
            
            # Convert to list of dictionaries
            bars = []
            for row in rows:
                bars.append({
                    'timestamp': row['timestamp'],
                    'open': Decimal(str(row['open_price'])),
                    'high': Decimal(str(row['high_price'])),
                    'low': Decimal(str(row['low_price'])),
                    'close': Decimal(str(row['close_price'])),
                    'volume': Decimal(str(row['volume']))
                })
                
            self._data_cache = bars
            return bars
            
        except Exception as e:
            logging.error(f"Error fetching historical data: {e}")
            raise
            
    def get_bars(self) -> Iterator[Dict[str, Any]]:
        """
        Generator that yields historical bars one at a time.
        
        Yields:
            Dict containing bar data
        """
        bars = self.fetch_data()
        for bar in bars:
            yield bar
            
    def get_bar_count(self) -> int:
        """Get total number of bars in the dataset."""
        return len(self.fetch_data())


class BacktestSimulation:
    """
    Enhanced backtesting simulation with broker simulator integration.
    Includes cooldown management and performance tracking for Phase 5.
    """
    
    def __init__(self, asset_config: DcaAsset, portfolio: SimulatedPortfolio, broker: BrokerSimulator):
        """
        Initialize simulation state.
        
        Args:
            asset_config: Asset configuration for the backtest
            portfolio: Simulated portfolio instance
            broker: Broker simulator instance
        """
        self.asset_config = asset_config
        self.portfolio = portfolio
        self.broker = broker
        self.logger = logging.getLogger('backtest_sim')
        
        # Initialize in-memory cycle state
        self.current_cycle = DcaCycle(
            id=0,  # Simulated cycle ID
            asset_id=asset_config.id,
            status='watching',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            latest_order_created_at=None,
            last_order_fill_price=None,
            highest_trailing_price=None,
            completed_at=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )
        
        # Simulation state
        self.current_alpaca_position = None  # Mock position for base order checks
        self.order_counter = 0  # For generating simulated order IDs
        
        # Performance tracking
        self.completed_cycles: List[CompletedTrade] = []
        self.cycle_entry_timestamp = None  # Track when current cycle started
        self.cycle_entry_price = None  # Track entry price for P/L calculation
        
    def check_cooldown_expiry(self, current_timestamp: datetime) -> None:
        """
        Check if current cycle's cooldown period has expired.
        
        Args:
            current_timestamp: Current bar timestamp
        """
        if self.current_cycle.status == 'cooldown' and self.current_cycle.completed_at:
            cooldown_duration = timedelta(seconds=self.asset_config.cooldown_period)
            cooldown_end = self.current_cycle.completed_at + cooldown_duration
            
            if current_timestamp >= cooldown_end:
                self.logger.info(f"⏰ Cooldown expired for {self.asset_config.asset_symbol}. Status: cooldown → watching")
                self.current_cycle.status = 'watching'
                self.current_cycle.completed_at = None
                # Reset cycle for new trading opportunity
                self._reset_cycle_for_new_trade()
    
    def _reset_cycle_for_new_trade(self) -> None:
        """Reset cycle state for a new trading opportunity."""
        self.current_cycle.quantity = Decimal('0')
        self.current_cycle.average_purchase_price = Decimal('0')
        self.current_cycle.safety_orders = 0
        self.current_cycle.latest_order_id = None
        self.current_cycle.latest_order_created_at = None
        self.current_cycle.last_order_fill_price = None
        self.current_cycle.highest_trailing_price = None
        self.cycle_entry_timestamp = None
        self.cycle_entry_price = None

    def get_simulated_position(self, symbol: str):
        """
        Create a mock Alpaca position object from simulated portfolio data.
        This allows existing fill handlers to work in backtest mode.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Mock position object or None if no position
        """
        position_qty = self.portfolio.get_position_qty(symbol)
        avg_price = self.portfolio.get_position_avg_price(symbol)
        
        if position_qty > 0 and avg_price:
            # Create a mock position object that mimics Alpaca's position
            class MockPosition:
                def __init__(self, qty, avg_entry_price):
                    self.qty = str(qty)
                    self.avg_entry_price = str(avg_entry_price)
                    
            return MockPosition(position_qty, avg_price)
        return None
        
    async def process_event(self, event: Dict, symbol: str, current_timestamp: datetime) -> None:
        """
        Process either a fill event or cancellation event.
        
        Args:
            event: Event from broker simulator (fill or cancellation)
            symbol: Trading symbol
            current_timestamp: Current bar timestamp
        """
        event_type = event.get('event', 'order_filled')  # Default to fill for backward compatibility
        
        if event_type == 'order_filled':
            await self.process_fill_event(event, symbol)
        elif event_type == 'order_canceled':
            await self.process_cancellation_event(event, symbol, current_timestamp)
        else:
            self.logger.warning(f"⚠️ Unknown event type: {event_type}")
            
    async def process_cancellation_event(self, cancel_event: Dict, symbol: str, current_timestamp: datetime) -> None:
        """
        Process a simulated order cancellation event.
        
        Args:
            cancel_event: Cancellation event from broker simulator
            symbol: Trading symbol
            current_timestamp: Current bar timestamp
        """
        try:
            order_id = cancel_event['id']
            cancel_reason = cancel_event.get('cancel_reason', 'unknown')
            side = cancel_event['side']
            
            self.logger.info(f"🔄 Processing {cancel_reason} cancellation for {side.upper()} order {order_id}")
            
            # If this was our current order, clear the tracking
            if self.current_cycle.latest_order_id == order_id:
                self.current_cycle.latest_order_id = None
                self.current_cycle.latest_order_created_at = None
                
                # For most cancellations, revert to watching status to allow retry
                if self.current_cycle.status in ['buying', 'selling']:
                    self.current_cycle.status = 'watching'
                    self.logger.info(f"🔄 Cycle status reverted to 'watching' after {cancel_reason}")
                    
            # Record cancellation for performance tracking
            self.logger.info(f"📊 Order cancellation recorded: {cancel_reason} - {side.upper()} order after "
                           f"{(current_timestamp - datetime.fromisoformat(cancel_event['created_at'].replace('Z', '+00:00'))).total_seconds()/60:.1f} minutes")
            
        except Exception as e:
            self.logger.error(f"❌ Error processing cancellation event: {e}")
        
    async def process_fill_event(self, fill_event: Dict, symbol: str) -> None:
        """
        Process a simulated fill event using existing fill handler logic.
        
        Args:
            fill_event: Simulated fill event from broker simulator
            symbol: Trading symbol
        """
        try:
            # Create mock order and trade_update objects for fill handlers
            class MockOrder:
                def __init__(self, fill_event):
                    self.id = fill_event['id']
                    self.symbol = fill_event['symbol']
                    self.side = fill_event['side']
                    self.filled_qty = fill_event['filled_qty']
                    self.filled_avg_price = fill_event['filled_avg_price']
                    self.status = fill_event['status']
                    self.order_type = fill_event.get('order_type', 'market')
                    
            class MockTradeUpdate:
                def __init__(self, fill_event):
                    self.qty = fill_event['filled_qty']
                    self.price = fill_event['filled_avg_price']
                    
            mock_order = MockOrder(fill_event)
            mock_trade_update = MockTradeUpdate(fill_event)
            
            # Patch position lookup functions to use simulated data
            original_get_alpaca_position = getattr(main_app, 'get_alpaca_position_by_symbol', None)
            
            def mock_get_alpaca_position(client, symbol):
                return self.get_simulated_position(symbol)
                
            # Patch the get_alpaca_position function
            if hasattr(main_app, 'get_alpaca_position_by_symbol'):
                main_app.get_alpaca_position_by_symbol = mock_get_alpaca_position
            
            # Update cycle state first (this mimics setting latest_order_id)
            self.current_cycle.latest_order_id = fill_event['id']
            self.current_cycle.latest_order_created_at = datetime.fromisoformat(fill_event['created_at'].replace('Z', '+00:00'))
            
            try:
                # Call appropriate fill handler
                if fill_event['side'] == 'buy':
                    self.logger.info(f"🔄 Processing BUY fill via existing handler...")
                    if update_cycle_on_buy_fill_live:
                        await self.process_buy_fill_backtest_mode(mock_order, mock_trade_update, symbol)
                    else:
                        self.logger.warning("⚠️ Live buy fill handler not available, using fallback")
                        self._fallback_buy_fill_processing(mock_order, symbol)
                        
                elif fill_event['side'] == 'sell':
                    self.logger.info(f"🔄 Processing SELL fill via existing handler...")
                    if update_cycle_on_sell_fill_live:
                        await self.process_sell_fill_backtest_mode(mock_order, mock_trade_update, symbol)
                    else:
                        self.logger.warning("⚠️ Live sell fill handler not available, using fallback")
                        self._fallback_sell_fill_processing(mock_order, symbol)
                        
            finally:
                # Restore original function
                if original_get_alpaca_position and hasattr(main_app, 'get_alpaca_position_by_symbol'):
                    main_app.get_alpaca_position_by_symbol = original_get_alpaca_position
                    
        except Exception as e:
            self.logger.error(f"❌ Error processing fill event: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            
    async def process_buy_fill_backtest_mode(self, order, trade_update, symbol: str):
        """Process buy fill in backtest mode with simulated data."""
        try:
            # Update cycle data to match the fill
            filled_qty = Decimal(str(order.filled_qty))
            filled_price = Decimal(str(order.filled_avg_price))
            
            # Calculate new position data
            current_qty = self.current_cycle.quantity
            current_avg = self.current_cycle.average_purchase_price
            
            # Track cycle entry for performance metrics
            if current_qty == 0:
                # This is the base order - start tracking the cycle
                self.cycle_entry_timestamp = datetime.now(timezone.utc)
                self.cycle_entry_price = filled_price
                is_safety_order = False
            else:
                is_safety_order = True
            
            # Calculate new totals
            new_total_qty = current_qty + filled_qty
            
            if current_qty == 0:
                # First purchase (base order)
                new_avg_price = filled_price
            else:
                # Safety order - calculate weighted average
                total_value = (current_qty * current_avg) + (filled_qty * filled_price)
                new_avg_price = total_value / new_total_qty
            
            # Update cycle state
            self.current_cycle.quantity = new_total_qty
            self.current_cycle.average_purchase_price = new_avg_price
            self.current_cycle.last_order_fill_price = filled_price
            self.current_cycle.status = 'watching'
            self.current_cycle.latest_order_id = None
            
            if is_safety_order:
                self.current_cycle.safety_orders += 1
                
            self.logger.info(f"✅ BUY fill processed: {new_total_qty} @ avg ${new_avg_price:.2f}")
            
            if is_safety_order:
                self.logger.info(f"🛡️ Safety order #{self.current_cycle.safety_orders} completed")
            else:
                self.logger.info(f"🚀 Base order completed - cycle started")
                
        except Exception as e:
            self.logger.error(f"❌ Error in buy fill processing: {e}")
            
    async def process_sell_fill_backtest_mode(self, order, trade_update, symbol: str):
        """Process sell fill in backtest mode with simulated data."""
        try:
            filled_qty = Decimal(str(order.filled_qty))
            filled_price = Decimal(str(order.filled_avg_price))
            
            # Calculate profit
            entry_price = self.current_cycle.average_purchase_price
            profit_per_unit = filled_price - entry_price
            total_profit = profit_per_unit * filled_qty
            profit_pct = (profit_per_unit / entry_price) * 100 if entry_price > 0 else Decimal('0')
            
            self.logger.info(f"💰 SELL fill processed: {filled_qty} @ ${filled_price:.2f}")
            self.logger.info(f"💰 Profit: ${total_profit:.2f} ({profit_pct:.2f}%)")
            
            # Record completed trade for performance tracking
            if self.cycle_entry_timestamp and self.cycle_entry_price:
                completed_trade = CompletedTrade(
                    asset_symbol=symbol,
                    entry_timestamp=self.cycle_entry_timestamp,
                    exit_timestamp=datetime.now(timezone.utc),
                    entry_price=self.cycle_entry_price,
                    exit_price=filled_price,
                    quantity=filled_qty,
                    realized_pnl=total_profit,
                    trade_type='take_profit',  # Assume take profit for now
                    safety_orders_used=self.current_cycle.safety_orders
                )
                self.portfolio.record_completed_trade(completed_trade)
                self.completed_cycles.append(completed_trade)
            
            # Mark cycle as complete and start cooldown
            self.current_cycle.status = 'cooldown'
            self.current_cycle.completed_at = datetime.now(timezone.utc)
            self.current_cycle.quantity = Decimal('0')
            self.current_cycle.sell_price = filled_price
            self.current_cycle.latest_order_id = None
            
            self.logger.info(f"⏰ Cycle completed, entering cooldown for {self.asset_config.cooldown_period} seconds")
            
        except Exception as e:
            self.logger.error(f"❌ Error in sell fill processing: {e}")

    def _create_new_cooldown_cycle(self):
        """Create a new cycle in cooldown status."""
        self.current_cycle = DcaCycle(
            id=self.current_cycle.id + 1,
            asset_id=self.asset_config.id,
            status='cooldown',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            latest_order_created_at=None,
            last_order_fill_price=None,
            highest_trailing_price=None,
            completed_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc)
        )

    def _fallback_buy_fill_processing(self, order, symbol: str):
        """Fallback buy fill processing if live handler unavailable."""
        self.logger.info(f"🔄 Using fallback BUY fill processing for {symbol}")
        # Simple fallback logic would go here
        
    def _fallback_sell_fill_processing(self, order, symbol: str):
        """Fallback sell fill processing if live handler unavailable."""
        self.logger.info(f"🔄 Using fallback SELL fill processing for {symbol}")
        # Simple fallback logic would go here
        
    async def process_strategy_action(self, action: StrategyAction, current_timestamp: datetime, current_bar: Dict[str, Any]) -> None:
        """
        Process a strategy action by placing simulated orders.
        
        Args:
            action: Strategy action to execute
            current_timestamp: Current bar timestamp
            current_bar: Current bar data
        """
        if not action or not action.has_action():
            return
            
        # Process order intent if present
        if action.order_intent:
            self.logger.info(f"📋 Processing order intent: {action.order_intent.side.value.upper()} "
                           f"{action.order_intent.order_type.value.upper()}")
            
            # Place order via broker simulator
            order_id = self.broker.place_order(action.order_intent, current_timestamp)
            
            # Update cycle tracking
            self.current_cycle.latest_order_id = order_id
            self.current_cycle.latest_order_created_at = current_timestamp
            
            # Immediately process any fills that might occur in this bar
            fill_events = self.broker.process_bar_fills(current_bar, current_timestamp)
            for event in fill_events:
                if event['id'] == order_id:  # This is our order filling
                    await self.process_event(event, action.order_intent.symbol, current_timestamp)
                    break
        
        # Process cycle updates if present
        if action.cycle_update_intent:
            self._apply_cycle_updates(action.cycle_update_intent)
            
        # Process TTP updates if present  
        if action.ttp_update_intent:
            self._apply_ttp_updates(action.ttp_update_intent)
            
    def _apply_cycle_updates(self, update_intent):
        """Apply cycle state updates from strategy logic."""
        if update_intent.new_status:
            old_status = self.current_cycle.status
            self.current_cycle.status = update_intent.new_status
            self.logger.info(f"🔄 Cycle status: {old_status} → {update_intent.new_status}")
            
        if update_intent.new_quantity is not None:
            self.current_cycle.quantity = update_intent.new_quantity
            
        if update_intent.new_safety_orders is not None:
            self.current_cycle.safety_orders = update_intent.new_safety_orders
            
    def _apply_ttp_updates(self, ttp_intent):
        """Apply TTP state updates from strategy logic."""
        if ttp_intent.new_status:
            old_status = self.current_cycle.status
            self.current_cycle.status = ttp_intent.new_status
            self.logger.info(f"🎯 TTP status: {old_status} → {ttp_intent.new_status}")
            
        if ttp_intent.new_highest_trailing_price:
            self.current_cycle.highest_trailing_price = ttp_intent.new_highest_trailing_price
            self.logger.info(f"⬆️ TTP peak: ${ttp_intent.new_highest_trailing_price}")

    def log_cycle_state(self) -> None:
        """Log current cycle state for debugging."""
        self.logger.debug(f"💾 CYCLE STATE: Status={self.current_cycle.status}, "
                         f"Qty={self.current_cycle.quantity}, "
                         f"AvgPrice=${self.current_cycle.average_purchase_price}, "
                         f"SafetyOrders={self.current_cycle.safety_orders}, "
                         f"LastFill=${self.current_cycle.last_order_fill_price}, "
                         f"TTPPeak=${self.current_cycle.highest_trailing_price}")


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DCA Trading Bot Backtesting Engine - Phase 4",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_backtest.py --symbol "BTC/USD" --start-date "2024-01-01" --end-date "2024-01-02"
  python scripts/run_backtest.py --asset-id 1 --start-date "2024-01-01" --end-date "2024-01-02"
        """
    )
    
    parser.add_argument(
        '--symbol',
        type=str,
        help='Trading symbol (e.g., "BTC/USD"). Required if --asset-id not provided.'
    )
    
    parser.add_argument(
        '--asset-id',
        type=int,
        help='Asset ID from dca_assets table. Takes precedence over --symbol.'
    )
    
    parser.add_argument(
        '--start-date',
        type=str,
        required=True,
        help='Start date in YYYY-MM-DD format'
    )
    
    parser.add_argument(
        '--end-date', 
        type=str,
        required=True,
        help='End date in YYYY-MM-DD format'
    )
    
    parser.add_argument(
        '--log-level',
        type=str,
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Logging level (default: INFO)'
    )
    
    args = parser.parse_args()
    
    # Validate that either symbol or asset-id is provided
    if not args.symbol and not args.asset_id:
        parser.error("Either --symbol or --asset-id must be provided")
        
    return args


def setup_backtest_logging(log_level: str) -> logging.Logger:
    """Setup logging specific to the backtester."""
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, log_level),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('logs/backtest.log'),
            logging.StreamHandler()
        ]
    )
    
    return logging.getLogger('backtest')


def calculate_performance_metrics(
    portfolio: SimulatedPortfolio,
    completed_trades: List[CompletedTrade],
    current_prices: Dict[str, Decimal],
    start_time: datetime,
    end_time: datetime
) -> PerformanceMetrics:
    """
    Calculate comprehensive performance metrics for the backtest.
    
    Args:
        portfolio: SimulatedPortfolio instance
        completed_trades: List of completed trades
        current_prices: Current asset prices for unrealized P/L
        start_time: Backtest start time
        end_time: Backtest end time
        
    Returns:
        PerformanceMetrics instance
    """
    # Basic metrics from portfolio
    total_realized_pnl = portfolio.realized_pnl
    total_unrealized_pnl = portfolio.get_unrealized_pnl(current_prices)
    final_portfolio_value = portfolio.get_portfolio_value(current_prices)
    total_fees = portfolio.total_fees
    
    # Trade statistics
    total_trades = len(completed_trades)
    winning_trades = len([trade for trade in completed_trades if trade.realized_pnl > 0])
    losing_trades = len([trade for trade in completed_trades if trade.realized_pnl < 0])
    
    # Calculate win rate
    win_rate = Decimal(str(winning_trades)) / Decimal(str(total_trades)) * 100 if total_trades > 0 else Decimal('0')
    
    # Calculate average P/L per trade
    average_pnl_per_trade = total_realized_pnl / Decimal(str(total_trades)) if total_trades > 0 else Decimal('0')
    
    # Simple max drawdown calculation (from portfolio value perspective)
    max_drawdown = Decimal('0')  # Simplified for now - would need historical portfolio values for accurate calculation
    
    return PerformanceMetrics(
        total_realized_pnl=total_realized_pnl,
        total_unrealized_pnl=total_unrealized_pnl,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        average_pnl_per_trade=average_pnl_per_trade,
        max_drawdown=max_drawdown,
        total_fees_paid=total_fees,
        final_portfolio_value=final_portfolio_value
    )


def display_performance_report(
    logger: logging.Logger,
    metrics: PerformanceMetrics,
    asset_config: DcaAsset,
    total_bars: int
) -> None:
    """
    Display comprehensive performance report.
    
    Args:
        logger: Logger instance
        metrics: Performance metrics
        asset_config: Asset configuration
        total_bars: Total bars processed
    """
    logger.info("=" * 60)
    logger.info("📈 BACKTESTING PERFORMANCE REPORT")
    logger.info("=" * 60)
    
    # Asset and backtest info
    logger.info(f"🎯 Asset: {asset_config.asset_symbol}")
    logger.info(f"📊 Total Bars Processed: {total_bars:,}")
    logger.info(f"⚙️ Strategy Config: Base=${asset_config.base_order_amount}, "
               f"Safety=${asset_config.safety_order_amount}, "
               f"Max Safety={asset_config.max_safety_orders}")
    logger.info("")
    
    # Portfolio performance
    starting_capital = Decimal('10000.0')  # Default starting capital
    total_return = metrics.total_pnl
    total_return_pct = (total_return / starting_capital) * 100
    
    logger.info("💰 PORTFOLIO PERFORMANCE:")
    logger.info(f"   🏛️ Starting Capital: ${starting_capital:.2f}")
    logger.info(f"   💼 Final Portfolio Value: ${metrics.final_portfolio_value:.2f}")
    logger.info(f"   📈 Total Return: ${total_return:.2f} ({total_return_pct:.2f}%)")
    logger.info(f"   ✅ Realized P/L: ${metrics.total_realized_pnl:.2f}")
    logger.info(f"   📊 Unrealized P/L: ${metrics.total_unrealized_pnl:.2f}")
    logger.info(f"   💸 Total Fees: ${metrics.total_fees_paid:.2f}")
    logger.info("")
    
    # Trading statistics
    logger.info("📊 TRADING STATISTICS:")
    logger.info(f"   🔄 Total Completed Trades: {metrics.total_trades}")
    logger.info(f"   ✅ Winning Trades: {metrics.winning_trades}")
    logger.info(f"   ❌ Losing Trades: {metrics.losing_trades}")
    logger.info(f"   🎯 Win Rate: {metrics.win_rate:.1f}%")
    logger.info(f"   📈 Average P/L per Trade: ${metrics.average_pnl_per_trade:.2f}")
    logger.info("")
    
    # Performance assessment
    if metrics.total_trades > 0:
        if total_return_pct > 0:
            logger.info("🎉 POSITIVE PERFORMANCE - Strategy was profitable!")
        elif total_return_pct == 0:
            logger.info("➡️ NEUTRAL PERFORMANCE - Strategy broke even")
        else:
            logger.info("📉 NEGATIVE PERFORMANCE - Strategy lost money")
            
        if metrics.win_rate >= 60:
            logger.info("🏆 EXCELLENT WIN RATE - Very consistent strategy")
        elif metrics.win_rate >= 50:
            logger.info("👍 GOOD WIN RATE - Reasonably consistent strategy")
        else:
            logger.info("⚠️ LOW WIN RATE - Strategy needs improvement")
    else:
        logger.info("⚠️ NO TRADES COMPLETED - Strategy may be too conservative or conditions not met")
    
    logger.info("=" * 60)


async def main():
    """Main backtesting function with Phase 5 enhancements."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Setup logging
        logger = setup_backtest_logging(args.log_level)
        logger.info("🚀 Starting DCA Backtesting Engine - Phase 5")
        logger.info("   ✨ Features: Broker Simulation, Portfolio Management, Cooldown Management")
        logger.info("   ✨ Features: Stale Order Cancellation, Performance Reporting")
        
        # Parse dates
        try:
            start_date = datetime.strptime(args.start_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
            end_date = datetime.strptime(args.end_date, '%Y-%m-%d').replace(tzinfo=timezone.utc)
        except ValueError as e:
            logger.error(f"Invalid date format: {e}")
            return 1
            
        # Load asset configuration
        if args.asset_id:
            # Load by asset ID (would need a function to get asset by ID)
            asset_config = execute_query(
                "SELECT * FROM dca_assets WHERE id = %s",
                (args.asset_id,),
                fetch_one=True
            )
            if not asset_config:
                logger.error(f"Asset with ID {args.asset_id} not found")
                return 1
            # Convert to DcaAsset object (simplified for now)
            symbol = asset_config['symbol']
        else:
            # Load by symbol
            symbol = args.symbol
            asset_config = get_asset_config(symbol)
            if not asset_config:
                logger.error(f"Asset configuration for {symbol} not found")
                return 1
                
        logger.info(f"📊 Asset: {symbol}")
        logger.info(f"📅 Date Range: {start_date.date()} to {end_date.date()}")
        logger.info(f"⚙️ Config: Base=${asset_config.base_order_amount}, "
                   f"Safety=${asset_config.safety_order_amount}, "
                   f"Max Safety={asset_config.max_safety_orders}, "
                   f"TP={asset_config.take_profit_percent}%, "
                   f"TTP={asset_config.ttp_enabled}")
        
        # Initialize historical data feeder
        data_feeder = HistoricalDataFeeder(asset_config.id, start_date, end_date)
        bar_count = data_feeder.get_bar_count()
        logger.info(f"📈 Historical bars loaded: {bar_count}")
        
        if bar_count == 0:
            logger.warning("No historical data found for the specified date range")
            return 1
            
        # Initialize simulation
        portfolio = SimulatedPortfolio()
        broker = BrokerSimulator(portfolio)
        simulation = BacktestSimulation(asset_config, portfolio, broker)
        logger.info(f"🎮 Simulation initialized with cycle state: {simulation.current_cycle.status}")
        
        # Initialize portfolio
        portfolio = SimulatedPortfolio()
        logger.info("💼 Portfolio initialized")
        
        # Initialize broker simulator
        broker = BrokerSimulator(portfolio)
        logger.info("🤖 Broker simulator initialized")
        
        # Main backtest loop
        logger.info("🔄 Starting backtest loop...")
        bar_counter = 0
        
        for bar in data_feeder.get_bars():
            bar_counter += 1
            
            # Log progress every 100 bars
            if bar_counter % 100 == 0:
                logger.info(f"📊 Processed {bar_counter}/{bar_count} bars "
                           f"({bar_counter/bar_count*100:.1f}%)")
            
            # Phase 5: Check cooldown expiry first
            simulation.check_cooldown_expiry(bar['timestamp'])
            
            # Create market input from bar
            market_input = MarketTickInput(
                timestamp=bar['timestamp'],
                current_ask_price=bar['close'],  # Simplified: use close as both ask/bid
                current_bid_price=bar['close'],
                symbol=symbol
            )
            
            # Log current bar (every 500 bars to avoid spam)
            if bar_counter % 500 == 0:
                logger.info(f"📈 Bar {bar_counter}: {bar['timestamp']} "
                           f"OHLC: ${bar['open']:.2f}/${bar['high']:.2f}/"
                           f"${bar['low']:.2f}/${bar['close']:.2f}")
            
            # Process any pending fills/cancellations first (before strategy decisions)
            events = simulation.broker.process_bar_fills(bar, bar['timestamp'])
            for event in events:
                await simulation.process_event(event, symbol, bar['timestamp'])
            
            # Call strategy functions based on current cycle status
            actions_executed = []
            
            # Check base order action
            if simulation.current_cycle.status in ['watching', 'cooldown']:
                try:
                    base_action = decide_base_order_action(
                        market_input, 
                        asset_config, 
                        simulation.current_cycle, 
                        simulation.current_alpaca_position
                    )
                    if base_action and base_action.has_action():
                        logger.info(f"🟢 BASE ORDER ACTION at ${bar['close']}")
                        await simulation.process_strategy_action(base_action, bar['timestamp'], bar)
                        actions_executed.append('base_order')
                except Exception as e:
                    logger.error(f"Error in base order logic: {e}")
            
            # Check safety order action
            if simulation.current_cycle.status == 'watching':
                try:
                    safety_action = decide_safety_order_action(
                        market_input,
                        asset_config,
                        simulation.current_cycle
                    )
                    if safety_action and safety_action.has_action():
                        logger.info(f"🛡️ SAFETY ORDER ACTION at ${bar['close']}")
                        await simulation.process_strategy_action(safety_action, bar['timestamp'], bar)
                        actions_executed.append('safety_order')
                except Exception as e:
                    logger.error(f"Error in safety order logic: {e}")
            
            # Check take-profit action
            if simulation.current_cycle.status in ['watching', 'trailing']:
                try:
                    tp_action = decide_take_profit_action(
                        market_input,
                        asset_config,
                        simulation.current_cycle,
                        simulation.current_alpaca_position
                    )
                    if tp_action and tp_action.has_action():
                        logger.info(f"💰 TAKE-PROFIT ACTION at ${bar['close']}")
                        await simulation.process_strategy_action(tp_action, bar['timestamp'], bar)
                        actions_executed.append('take_profit')
                except Exception as e:
                    logger.error(f"Error in take-profit logic: {e}")
            
            # Log cycle state periodically or when actions are taken
            if actions_executed or bar_counter % 1000 == 0:
                simulation.log_cycle_state()
        
        # Phase 5: Calculate and report performance metrics
        logger.info("✅ Backtest completed!")
        logger.info(f"📊 Total bars processed: {bar_counter}")
        logger.info(f"💾 Final cycle state: Status={simulation.current_cycle.status}, "
                   f"Qty={simulation.current_cycle.quantity}, "
                   f"SafetyOrders={simulation.current_cycle.safety_orders}")
        
        # Get final prices for unrealized P/L calculation
        final_prices = {symbol: bar['close']} if 'bar' in locals() else {}
        
        # Calculate performance metrics
        performance = calculate_performance_metrics(
            portfolio=portfolio,
            completed_trades=simulation.completed_cycles,
            current_prices=final_prices,
            start_time=start_date,
            end_time=end_date
        )
        
        # Display comprehensive performance report
        display_performance_report(logger, performance, asset_config, bar_counter)
        
        # Log portfolio summary with current prices
        portfolio.log_portfolio_summary(final_prices)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Backtesting failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == '__main__':
    exit(asyncio.run(main())) 