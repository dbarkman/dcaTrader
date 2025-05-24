#!/usr/bin/env python3
"""
Test Utilities for DCA Trading Bot Integration Tests

This module provides helper functions to create mock WebSocket event data
that closely mimics the actual objects provided by the alpaca-py SDK.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional, Any
import uuid


class MockCryptoQuote:
    """Mock object that mimics alpaca.data.models.CryptoQuote"""
    
    def __init__(self, symbol: str, ask_price: float, bid_price: float, 
                 ask_size: float = 100.0, bid_size: float = 100.0, 
                 timestamp: Optional[datetime] = None):
        self.symbol = symbol
        self.ask_price = ask_price
        self.bid_price = bid_price
        self.ask_size = ask_size
        self.bid_size = bid_size
        self.timestamp = timestamp or datetime.now()


class MockCryptoTrade:
    """Mock object that mimics alpaca.data.models.CryptoTrade"""
    
    def __init__(self, symbol: str, price: float, size: float, 
                 timestamp: Optional[datetime] = None):
        self.symbol = symbol
        self.price = price
        self.size = size
        self.timestamp = timestamp or datetime.now()


class MockOrder:
    """Mock object that mimics alpaca.trading.models.Order"""
    
    def __init__(self, order_id: str, symbol: str, side: str, qty: str,
                 status: str = 'filled', order_type: str = 'limit',
                 limit_price: Optional[str] = None, filled_qty: str = '0',
                 filled_avg_price: Optional[str] = None, 
                 client_order_id: Optional[str] = None):
        self.id = order_id
        self.symbol = symbol
        self.side = side  # 'buy' or 'sell'
        self.qty = qty
        self.status = status  # 'new', 'filled', 'canceled', etc.
        self.order_type = order_type  # 'limit', 'market', etc.
        self.limit_price = limit_price
        self.filled_qty = filled_qty
        self.filled_avg_price = filled_avg_price
        self.client_order_id = client_order_id


class MockTradeUpdate:
    """Mock object that mimics alpaca.trading.models.TradeUpdate"""
    
    def __init__(self, order: MockOrder, event: str, 
                 execution_id: Optional[str] = None,
                 price: Optional[str] = None, qty: Optional[str] = None,
                 timestamp: Optional[datetime] = None):
        self.order = order
        self.event = event  # 'fill', 'partial_fill', 'canceled', 'new', etc.
        self.execution_id = execution_id
        self.price = price  # Fill price (if fill event)
        self.qty = qty      # Fill quantity (if fill event)
        self.timestamp = timestamp or datetime.now()


def create_mock_crypto_quote_event(symbol: str, ask_price: float, bid_price: float,
                                  ask_size: float = 100.0, bid_size: float = 100.0,
                                  timestamp: Optional[datetime] = None) -> MockCryptoQuote:
    """
    Create a mock cryptocurrency quote event.
    
    Args:
        symbol: The crypto symbol (e.g., 'BTC/USD')
        ask_price: Current ask price
        bid_price: Current bid price  
        ask_size: Ask size (optional, defaults to 100.0)
        bid_size: Bid size (optional, defaults to 100.0)
        timestamp: Event timestamp (optional, defaults to now)
        
    Returns:
        MockCryptoQuote object that mimics alpaca.data.models.CryptoQuote
    """
    return MockCryptoQuote(
        symbol=symbol,
        ask_price=ask_price,
        bid_price=bid_price,
        ask_size=ask_size,
        bid_size=bid_size,
        timestamp=timestamp
    )


def create_mock_crypto_trade_event(symbol: str, price: float, size: float,
                                  timestamp: Optional[datetime] = None) -> MockCryptoTrade:
    """
    Create a mock cryptocurrency trade event.
    
    Args:
        symbol: The crypto symbol (e.g., 'BTC/USD')
        price: Trade price
        size: Trade size
        timestamp: Event timestamp (optional, defaults to now)
        
    Returns:
        MockCryptoTrade object that mimics alpaca.data.models.CryptoTrade
    """
    return MockCryptoTrade(
        symbol=symbol,
        price=price,
        size=size,
        timestamp=timestamp
    )


def create_mock_trade_update_event(order_id: str, symbol: str, event_type: str,
                                  side: str = 'buy', qty: str = '0.001',
                                  status: str = 'filled', order_type: str = 'limit',
                                  limit_price: Optional[str] = None,
                                  filled_qty: Optional[str] = None,
                                  filled_avg_price: Optional[str] = None,
                                  fill_price: Optional[str] = None,
                                  fill_qty: Optional[str] = None,
                                  client_order_id: Optional[str] = None,
                                  timestamp: Optional[datetime] = None) -> MockTradeUpdate:
    """
    Create a mock trade update event (order fill, cancellation, etc.).
    
    Args:
        order_id: Alpaca order ID
        symbol: The crypto symbol (e.g., 'BTC/USD')
        event_type: Event type ('fill', 'partial_fill', 'canceled', 'new', etc.)
        side: Order side ('buy' or 'sell')
        qty: Total order quantity
        status: Order status ('new', 'filled', 'canceled', etc.)
        order_type: Order type ('limit', 'market', etc.)
        limit_price: Limit price (if limit order)
        filled_qty: Total filled quantity
        filled_avg_price: Average fill price
        fill_price: This specific fill price (for fill events)
        fill_qty: This specific fill quantity (for fill events)
        client_order_id: Client order ID (optional)
        timestamp: Event timestamp (optional, defaults to now)
        
    Returns:
        MockTradeUpdate object that mimics alpaca.trading.models.TradeUpdate
    """
    # Create the order object
    order = MockOrder(
        order_id=order_id,
        symbol=symbol,
        side=side,
        qty=qty,
        status=status,
        order_type=order_type,
        limit_price=limit_price,
        filled_qty=filled_qty or qty,  # Default to full fill
        filled_avg_price=filled_avg_price,
        client_order_id=client_order_id
    )
    
    # Create execution details for fill events
    execution_id = None
    if event_type in ['fill', 'partial_fill']:
        execution_id = str(uuid.uuid4())
        
    return MockTradeUpdate(
        order=order,
        event=event_type,
        execution_id=execution_id,
        price=fill_price,
        qty=fill_qty,
        timestamp=timestamp
    )


def create_base_order_scenario(symbol: str = 'BTC/USD', ask_price: float = 109000.0,
                             bid_price: float = 108950.0) -> MockCryptoQuote:
    """
    Create a realistic scenario for base order placement testing.
    
    This creates a quote that should trigger base order placement when:
    - Asset is configured and enabled
    - Cycle status is 'watching' with quantity = 0
    - No existing position on Alpaca
    
    Args:
        symbol: The crypto symbol
        ask_price: Ask price that should trigger order
        bid_price: Bid price (slightly below ask)
        
    Returns:
        MockCryptoQuote for base order testing
    """
    return create_mock_crypto_quote_event(
        symbol=symbol,
        ask_price=ask_price,
        bid_price=bid_price,
        ask_size=50.0,
        bid_size=75.0
    )


def create_safety_order_scenario(symbol: str = 'BTC/USD', 
                                last_fill_price: float = 120000.0,
                                safety_deviation_pct: float = 2.0,
                                current_drop_pct: float = 3.0) -> MockCryptoQuote:
    """
    Create a realistic scenario for safety order placement testing.
    
    Args:
        symbol: The crypto symbol
        last_fill_price: The last order fill price in the cycle
        safety_deviation_pct: Safety order deviation percentage
        current_drop_pct: How much the price has dropped from last fill
        
    Returns:
        MockCryptoQuote that should trigger safety order
    """
    # Calculate current price based on drop percentage
    current_ask = last_fill_price * (1 - current_drop_pct / 100)
    current_bid = current_ask - (current_ask * 0.001)  # Small spread
    
    return create_mock_crypto_quote_event(
        symbol=symbol,
        ask_price=current_ask,
        bid_price=current_bid,
        ask_size=25.0,
        bid_size=30.0
    )


def create_order_fill_scenario(order_id: str, symbol: str = 'BTC/USD',
                              side: str = 'buy', fill_price: float = 109500.0,
                              fill_qty: str = '0.0004566') -> MockTradeUpdate:
    """
    Create a realistic scenario for order fill testing.
    
    Args:
        order_id: The order ID that filled
        symbol: The crypto symbol
        side: Order side ('buy' or 'sell')
        fill_price: The fill price
        fill_qty: The fill quantity
        
    Returns:
        MockTradeUpdate for fill testing
    """
    return create_mock_trade_update_event(
        order_id=order_id,
        symbol=symbol,
        event_type='fill',
        side=side,
        qty=fill_qty,
        status='filled',
        order_type='limit',
        limit_price=str(fill_price),
        filled_qty=fill_qty,
        filled_avg_price=str(fill_price),
        fill_price=str(fill_price),
        fill_qty=fill_qty
    )


# Utility functions for test setup and validation
def validate_mock_quote(mock_quote: MockCryptoQuote) -> bool:
    """Validate that a mock quote has all required fields"""
    required_attrs = ['symbol', 'ask_price', 'bid_price', 'ask_size', 'bid_size', 'timestamp']
    return all(hasattr(mock_quote, attr) for attr in required_attrs)


def validate_mock_trade_update(mock_update: MockTradeUpdate) -> bool:
    """Validate that a mock trade update has all required fields"""
    if not hasattr(mock_update, 'order') or not hasattr(mock_update, 'event'):
        return False
    
    order_attrs = ['id', 'symbol', 'side', 'qty', 'status']
    return all(hasattr(mock_update.order, attr) for attr in order_attrs)


def print_mock_quote_details(mock_quote: MockCryptoQuote, description: str = "Mock Quote"):
    """Print detailed information about a mock quote for debugging"""
    print(f"📊 {description}:")
    print(f"   Symbol: {mock_quote.symbol}")
    print(f"   Bid: ${mock_quote.bid_price:,.4f} @ {mock_quote.bid_size}")
    print(f"   Ask: ${mock_quote.ask_price:,.4f} @ {mock_quote.ask_size}")
    print(f"   Spread: ${mock_quote.ask_price - mock_quote.bid_price:.4f}")
    print(f"   Timestamp: {mock_quote.timestamp}")


def print_mock_trade_update_details(mock_update: MockTradeUpdate, description: str = "Mock Trade Update"):
    """Print detailed information about a mock trade update for debugging"""
    print(f"📨 {description}:")
    print(f"   Event: {mock_update.event}")
    print(f"   Order ID: {mock_update.order.id}")
    print(f"   Symbol: {mock_update.order.symbol}")
    print(f"   Side: {mock_update.order.side}")
    print(f"   Quantity: {mock_update.order.qty}")
    print(f"   Status: {mock_update.order.status}")
    if mock_update.execution_id:
        print(f"   Execution ID: {mock_update.execution_id}")
    if mock_update.price:
        print(f"   Fill Price: ${float(mock_update.price):,.4f}")
    if mock_update.qty:
        print(f"   Fill Qty: {mock_update.qty}") 