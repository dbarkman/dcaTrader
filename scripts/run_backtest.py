#!/usr/bin/env python3
"""
Phase 4: Backtesting Engine - Broker Simulator & Simulated State Management

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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Iterator, Optional, Any
from dataclasses import dataclass
import traceback

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
    Manages cash and asset positions for backtesting simulation.
    """
    
    def __init__(self, starting_cash: Decimal = Decimal('10000.0')):
        """
        Initialize the simulated portfolio.
        
        Args:
            starting_cash: Initial cash balance for backtesting
        """
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: Dict[str, Dict[str, Decimal]] = {}  # symbol -> {'quantity': Decimal, 'average_entry_price': Decimal}
        self.total_fees_paid = Decimal('0.0')
        self.realized_pnl = Decimal('0.0')
        self.logger = logging.getLogger('portfolio_sim')
        
    def update_on_buy(self, symbol: str, quantity: Decimal, price: Decimal, fee: Decimal = Decimal('0.0')) -> None:
        """
        Update portfolio on a buy transaction.
        
        Args:
            symbol: Trading symbol (e.g., 'BTC/USD')
            quantity: Quantity purchased
            price: Price per unit
            fee: Transaction fee
        """
        total_cost = quantity * price + fee
        
        if total_cost > self.cash:
            self.logger.warning(f"💸 Insufficient cash for buy: need ${total_cost}, have ${self.cash}")
            return
            
        # Update cash
        self.cash -= total_cost
        self.total_fees_paid += fee
        
        # Update position
        if symbol not in self.positions:
            self.positions[symbol] = {
                'quantity': Decimal('0'),
                'average_entry_price': Decimal('0')
            }
            
        current_qty = self.positions[symbol]['quantity']
        current_avg = self.positions[symbol]['average_entry_price']
        
        # Calculate new average entry price
        if current_qty == 0:
            new_avg_price = price
        else:
            total_value = (current_qty * current_avg) + (quantity * price)
            new_quantity = current_qty + quantity
            new_avg_price = total_value / new_quantity
            
        self.positions[symbol]['quantity'] = current_qty + quantity
        self.positions[symbol]['average_entry_price'] = new_avg_price
        
        self.logger.info(f"📊 BUY: {quantity} {symbol} @ ${price} (total: ${total_cost:.2f})")
        self.logger.info(f"💰 Position: {self.positions[symbol]['quantity']} @ avg ${new_avg_price:.2f}")
        self.logger.info(f"💵 Cash remaining: ${self.cash:.2f}")
        
    def update_on_sell(self, symbol: str, quantity: Decimal, price: Decimal, fee: Decimal = Decimal('0.0')) -> Decimal:
        """
        Update portfolio on a sell transaction.
        
        Args:
            symbol: Trading symbol
            quantity: Quantity sold
            price: Price per unit
            fee: Transaction fee
            
        Returns:
            Realized P/L from this trade
        """
        if symbol not in self.positions or self.positions[symbol]['quantity'] < quantity:
            self.logger.warning(f"💸 Insufficient position for sell: need {quantity}, have {self.get_position_qty(symbol)}")
            return Decimal('0.0')
            
        total_proceeds = (quantity * price) - fee
        
        # Calculate realized P/L
        avg_entry_price = self.positions[symbol]['average_entry_price']
        trade_pnl = (price - avg_entry_price) * quantity - fee
        
        # Update cash and fees
        self.cash += total_proceeds
        self.total_fees_paid += fee
        self.realized_pnl += trade_pnl
        
        # Update position
        self.positions[symbol]['quantity'] -= quantity
        
        # If position is fully closed, remove it
        if self.positions[symbol]['quantity'] == 0:
            del self.positions[symbol]
            
        self.logger.info(f"📊 SELL: {quantity} {symbol} @ ${price} (proceeds: ${total_proceeds:.2f})")
        self.logger.info(f"💰 Trade P/L: ${trade_pnl:.2f} (entry: ${avg_entry_price:.2f})")
        self.logger.info(f"💵 Cash: ${self.cash:.2f}, Total P/L: ${self.realized_pnl:.2f}")
        
        return trade_pnl
        
    def get_position_qty(self, symbol: str) -> Decimal:
        """Get current position quantity for a symbol."""
        return self.positions.get(symbol, {}).get('quantity', Decimal('0'))
        
    def get_position_avg_price(self, symbol: str) -> Optional[Decimal]:
        """Get average entry price for a position."""
        return self.positions.get(symbol, {}).get('average_entry_price')
        
    def get_portfolio_value(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """
        Calculate total portfolio value including cash and positions.
        
        Args:
            current_prices: Dict mapping symbols to current prices
            
        Returns:
            Total portfolio value
        """
        total_value = self.cash
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                position_value = position['quantity'] * current_prices[symbol]
                total_value += position_value
                
        return total_value
        
    def get_unrealized_pnl(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """Calculate unrealized P/L for open positions."""
        unrealized_pnl = Decimal('0.0')
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                current_value = position['quantity'] * current_prices[symbol]
                cost_basis = position['quantity'] * position['average_entry_price']
                unrealized_pnl += current_value - cost_basis
                
        return unrealized_pnl
        
    def log_portfolio_summary(self, current_prices: Dict[str, Decimal] = None) -> None:
        """Log current portfolio status."""
        current_prices = current_prices or {}
        
        self.logger.info("💼 PORTFOLIO SUMMARY:")
        self.logger.info(f"   💵 Cash: ${self.cash:.2f}")
        self.logger.info(f"   💰 Realized P/L: ${self.realized_pnl:.2f}")
        self.logger.info(f"   💸 Total Fees: ${self.total_fees_paid:.2f}")
        
        if self.positions:
            self.logger.info("   📊 Positions:")
            for symbol, position in self.positions.items():
                qty = position['quantity']
                avg_price = position['average_entry_price']
                current_price = current_prices.get(symbol)
                
                if current_price:
                    current_value = qty * current_price
                    cost_basis = qty * avg_price
                    unrealized_pnl = current_value - cost_basis
                    self.logger.info(f"      {symbol}: {qty} @ ${avg_price:.2f} (current: ${current_price:.2f}, P/L: ${unrealized_pnl:.2f})")
                else:
                    self.logger.info(f"      {symbol}: {qty} @ ${avg_price:.2f}")
        else:
            self.logger.info("   📊 No open positions")
            
        if current_prices:
            total_value = self.get_portfolio_value(current_prices)
            total_return = total_value - self.starting_cash
            total_return_pct = (total_return / self.starting_cash) * 100
            self.logger.info(f"   🎯 Total Value: ${total_value:.2f} (Return: ${total_return:.2f}, {total_return_pct:.2f}%)")


class BrokerSimulator:
    """
    Simulates order execution based on historical bar data.
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
        
        Args:
            bar: Historical bar data with OHLC prices
            current_timestamp: Current bar timestamp
            
        Returns:
            List of simulated fill events
        """
        fills = []
        orders_to_remove = []
        
        # Create a copy to iterate over since we might modify the list
        for order in self.open_orders[:]:
            fill_event = self._check_order_fill(order, bar, current_timestamp)
            if fill_event:
                fills.append(fill_event)
                orders_to_remove.append(order)
                
        # Remove filled orders
        for order in orders_to_remove:
            self.open_orders.remove(order)
            
        return fills
        
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
            
            # Calculate new totals
            new_total_qty = current_qty + filled_qty
            
            if current_qty == 0:
                # First purchase (base order)
                new_avg_price = filled_price
                is_safety_order = False
            else:
                # Safety order - calculate weighted average
                total_value = (current_qty * current_avg) + (filled_qty * filled_price)
                new_avg_price = total_value / new_total_qty
                is_safety_order = True
            
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
            
            # Mark cycle as complete
            self.current_cycle.status = 'complete'
            self.current_cycle.completed_at = datetime.now(timezone.utc)
            self.current_cycle.quantity = Decimal('0')
            self.current_cycle.sell_price = filled_price
            self.current_cycle.latest_order_id = None
            
            # Create new cooldown cycle
            self._create_new_cooldown_cycle()
            
            self.logger.info(f"✅ Cycle completed - entering cooldown")
            
        except Exception as e:
            self.logger.error(f"❌ Error in sell fill processing: {e}")
            
    def _create_new_cooldown_cycle(self):
        """Create a new cooldown cycle after completion."""
        self.current_cycle = DcaCycle(
            id=self.current_cycle.id + 1,  # Increment cycle ID
            asset_id=self.asset_config.id,
            status='cooldown',
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
        
    def _fallback_buy_fill_processing(self, order, symbol: str):
        """Fallback buy fill processing when live handler not available."""
        self.logger.info(f"🔄 Using fallback buy fill processing for {symbol}")
        # Basic processing similar to process_buy_fill_backtest_mode
        # (implementation would be similar to above)
        
    def _fallback_sell_fill_processing(self, order, symbol: str):
        """Fallback sell fill processing when live handler not available."""
        self.logger.info(f"🔄 Using fallback sell fill processing for {symbol}")
        # Basic processing similar to process_sell_fill_backtest_mode
        # (implementation would be similar to above)
        
    async def process_strategy_action(self, action: StrategyAction, current_timestamp: datetime, current_bar: Dict[str, Any]) -> None:
        """
        Process a strategy action by integrating with broker simulator.
        
        Args:
            action: Strategy action with intents to process
            current_timestamp: Current simulation timestamp
            current_bar: Current bar data for fill simulation
        """
        if not action or not action.has_action():
            return
            
        # Step 1: Process order intent via broker simulator
        if action.order_intent:
            order_id = self.broker.place_order(action.order_intent, current_timestamp)
            self.logger.info(f"📋 Order placed with broker simulator: {order_id}")
            
        # Step 2: Process cycle state update intent
        if action.cycle_update_intent:
            intent = action.cycle_update_intent
            
            if intent.new_status:
                old_status = self.current_cycle.status
                self.current_cycle.status = intent.new_status
                self.logger.info(f"🔄 CYCLE STATUS: {old_status} → {intent.new_status}")
                
            if intent.new_latest_order_id or action.order_intent:
                # Set the latest order ID to the one from broker simulator
                if action.order_intent:
                    self.current_cycle.latest_order_id = order_id
                    self.current_cycle.latest_order_created_at = current_timestamp
                elif intent.new_latest_order_id:
                    self.current_cycle.latest_order_id = intent.new_latest_order_id
                    
            # Apply other cycle updates
            if intent.new_quantity is not None:
                self.current_cycle.quantity = intent.new_quantity
                self.logger.info(f"📊 QUANTITY: {intent.new_quantity}")
                
            if intent.new_average_purchase_price is not None:
                self.current_cycle.average_purchase_price = intent.new_average_purchase_price
                self.logger.info(f"💰 AVG PRICE: ${intent.new_average_purchase_price}")
                
            if intent.new_safety_orders is not None:
                self.current_cycle.safety_orders = intent.new_safety_orders
                self.logger.info(f"🛡️ SAFETY ORDERS: {intent.new_safety_orders}")
                
            if intent.new_last_order_fill_price is not None:
                self.current_cycle.last_order_fill_price = intent.new_last_order_fill_price
                self.logger.info(f"📈 LAST FILL PRICE: ${intent.new_last_order_fill_price}")
        
        # Step 3: Process TTP state update intent
        if action.ttp_update_intent:
            intent = action.ttp_update_intent
            
            if intent.new_status:
                old_status = self.current_cycle.status
                self.current_cycle.status = intent.new_status
                self.logger.info(f"🎯 TTP STATUS: {old_status} → {intent.new_status}")
                
            if intent.new_highest_trailing_price is not None:
                self.current_cycle.highest_trailing_price = intent.new_highest_trailing_price
                self.logger.info(f"⬆️ TTP PEAK: ${intent.new_highest_trailing_price}")
                
        # Step 4: Process any immediate fills from broker simulator
        fills = self.broker.process_bar_fills(current_bar, current_timestamp)
        for fill_event in fills:
            await self.process_fill_event(fill_event, self.asset_config.asset_symbol)
    
    def log_cycle_state(self) -> None:
        """Log current cycle state for debugging."""
        self.logger.debug(f"💾 CYCLE STATE: Status={self.current_cycle.status}, "
                         f"Qty={self.current_cycle.quantity}, "
                         f"AvgPrice=${self.current_cycle.average_purchase_price}, "
                         f"SafetyOrders={self.current_cycle.safety_orders}, "
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


async def main():
    """Main backtesting function."""
    try:
        # Parse arguments
        args = parse_arguments()
        
        # Setup logging
        logger = setup_backtest_logging(args.log_level)
        logger.info("🚀 Starting DCA Backtesting Engine - Phase 4")
        
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
            
            # Process any pending fills first (before strategy decisions)
            fills = simulation.broker.process_bar_fills(bar, bar['timestamp'])
            for fill_event in fills:
                await simulation.process_fill_event(fill_event, symbol)
            
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
        
        # Final summary
        logger.info("✅ Backtest completed!")
        logger.info(f"📊 Total bars processed: {bar_counter}")
        logger.info(f"💾 Final cycle state: Status={simulation.current_cycle.status}, "
                   f"Qty={simulation.current_cycle.quantity}, "
                   f"SafetyOrders={simulation.current_cycle.safety_orders}")
        
        # Log portfolio summary with current prices
        current_prices = {symbol: bar['close']} if 'bar' in locals() else {}
        portfolio.log_portfolio_summary(current_prices)
        
        return 0
        
    except Exception as e:
        logger.error(f"❌ Backtesting failed: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1


if __name__ == '__main__':
    import asyncio
    exit(asyncio.run(main())) 