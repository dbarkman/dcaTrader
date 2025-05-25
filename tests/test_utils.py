"""
Test utilities for creating mock WebSocket event data

This module provides helper functions to generate realistic mock event data 
structures that closely mimic the actual objects provided by the alpaca-py SDK 
for WebSocket messages. This allows for robust testing of WebSocket handlers 
without waiting for live market data.
"""

from datetime import datetime
from typing import Optional
from unittest.mock import Mock


def create_mock_crypto_quote_event(
    symbol: str, 
    ask_price: float, 
    bid_price: float, 
    ask_size: float = 100.0,
    bid_size: float = 100.0,
    timestamp: Optional[datetime] = None
) -> Mock:
    """
    Create a mock crypto quote event that mimics Alpaca's CryptoQuote structure.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        ask_price: Ask price for the quote
        bid_price: Bid price for the quote
        ask_size: Size available at ask price (default: 100.0)
        bid_size: Size available at bid price (default: 100.0)
        timestamp: Quote timestamp (default: current time)
    
    Returns:
        Mock object with CryptoQuote structure
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    mock_quote = Mock()
    mock_quote.symbol = symbol
    mock_quote.ask_price = ask_price
    mock_quote.bid_price = bid_price
    mock_quote.ask_size = ask_size
    mock_quote.bid_size = bid_size
    mock_quote.timestamp = timestamp
    
    return mock_quote


def create_mock_crypto_trade_event(
    symbol: str,
    price: float,
    size: float,
    timestamp: Optional[datetime] = None,
    trade_id: Optional[str] = None
) -> Mock:
    """
    Create a mock crypto trade event that mimics Alpaca's CryptoTrade structure.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        price: Trade execution price
        size: Trade size/quantity
        timestamp: Trade timestamp (default: current time)
        trade_id: Unique trade identifier (default: auto-generated)
    
    Returns:
        Mock object with CryptoTrade structure
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    if trade_id is None:
        trade_id = f"trade_{symbol.replace('/', '_')}_{int(timestamp.timestamp())}"
    
    mock_trade = Mock()
    mock_trade.symbol = symbol
    mock_trade.price = price
    mock_trade.size = size
    mock_trade.timestamp = timestamp
    mock_trade.id = trade_id
    
    return mock_trade


def create_mock_trade_update_event(
    order_id: str,
    symbol: str,
    event_type: str,  # 'fill', 'partial_fill', 'canceled', 'new', etc.
    side: str = 'buy',  # 'buy' or 'sell'
    order_status: str = 'filled',  # 'new', 'filled', 'canceled', etc.
    qty: str = '0',
    filled_qty: str = '0',
    filled_avg_price: str = '0',
    limit_price: Optional[str] = None,
    order_type: str = 'limit',
    time_in_force: str = 'gtc',
    client_order_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    execution_price: Optional[float] = None,
    execution_qty: Optional[float] = None,
    timestamp: Optional[datetime] = None
) -> Mock:
    """
    Create a mock trade update event that mimics Alpaca's TradeUpdate structure.
    
    Args:
        order_id: Alpaca order ID
        symbol: Trading symbol (e.g., 'BTC/USD')
        event_type: Type of event ('fill', 'partial_fill', 'canceled', 'new', etc.)
        side: Order side ('buy' or 'sell')
        order_status: Order status ('new', 'filled', 'canceled', etc.)
        qty: Order quantity as string
        filled_qty: Filled quantity as string
        filled_avg_price: Average fill price as string
        limit_price: Limit price as string (optional)
        order_type: Order type ('limit', 'market', etc.)
        time_in_force: Time in force ('gtc', 'day', etc.)
        client_order_id: Client-specified order ID (optional)
        execution_id: Execution ID for fills (optional)
        execution_price: Execution price for fills (optional)
        execution_qty: Execution quantity for fills (optional)
        timestamp: Event timestamp (default: current time)
    
    Returns:
        Mock object with TradeUpdate structure
    """
    if timestamp is None:
        timestamp = datetime.now()
    
    # Create mock order object
    mock_order = Mock()
    mock_order.id = order_id
    mock_order.symbol = symbol
    mock_order.side = side
    mock_order.status = order_status
    mock_order.qty = qty
    mock_order.filled_qty = filled_qty
    mock_order.filled_avg_price = filled_avg_price
    mock_order.limit_price = limit_price
    mock_order.order_type = order_type
    mock_order.time_in_force = time_in_force
    mock_order.client_order_id = client_order_id
    mock_order.created_at = timestamp
    mock_order.updated_at = timestamp
    
    # Create mock trade update object
    mock_trade_update = Mock()
    mock_trade_update.event = event_type
    mock_trade_update.order = mock_order
    mock_trade_update.timestamp = timestamp
    
    # Add execution details if this is a fill event
    if event_type in ['fill', 'partial_fill'] and execution_id:
        mock_trade_update.execution_id = execution_id
        mock_trade_update.price = execution_price
        mock_trade_update.qty = execution_qty
    
    return mock_trade_update


def create_mock_base_order_fill_event(
    symbol: str,
    order_id: str,
    fill_price: float,
    fill_qty: float,
    total_order_qty: float,
    limit_price: float
) -> Mock:
    """
    Create a mock trade update event for a base order fill.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        order_id: Alpaca order ID
        fill_price: Price at which order was filled
        fill_qty: Quantity that was filled
        total_order_qty: Total order quantity
        limit_price: Original limit price of the order
    
    Returns:
        Mock TradeUpdate object for a filled base order
    """
    return create_mock_trade_update_event(
        order_id=order_id,
        symbol=symbol,
        event_type='fill',
        side='buy',
        order_status='filled',
        qty=str(total_order_qty),
        filled_qty=str(fill_qty),
        filled_avg_price=str(fill_price),
        limit_price=str(limit_price),
        execution_id=f"exec_{order_id}",
        execution_price=fill_price,
        execution_qty=fill_qty
    )


def create_mock_safety_order_fill_event(
    symbol: str,
    order_id: str,
    fill_price: float,
    fill_qty: float,
    total_order_qty: float,
    limit_price: float
) -> Mock:
    """
    Create a mock trade update event for a safety order fill.
    
    Args:
        symbol: Trading symbol (e.g., 'BTC/USD')
        order_id: Alpaca order ID
        fill_price: Price at which order was filled
        fill_qty: Quantity that was filled
        total_order_qty: Total order quantity
        limit_price: Original limit price of the order
    
    Returns:
        Mock TradeUpdate object for a filled safety order
    """
    return create_mock_trade_update_event(
        order_id=order_id,
        symbol=symbol,
        event_type='fill',
        side='buy',
        order_status='filled',
        qty=str(total_order_qty),
        filled_qty=str(fill_qty),
        filled_avg_price=str(fill_price),
        limit_price=str(limit_price),
        execution_id=f"safety_exec_{order_id}",
        execution_price=fill_price,
        execution_qty=fill_qty
    )


def create_realistic_btc_quote(ask_price: float, spread_pct: float = 0.1) -> Mock:
    """
    Create a realistic BTC/USD quote with proper bid/ask spread.
    
    Args:
        ask_price: Ask price for BTC/USD
        spread_pct: Spread percentage (default: 0.1%)
    
    Returns:
        Mock CryptoQuote object for BTC/USD
    """
    spread = ask_price * (spread_pct / 100)
    bid_price = ask_price - spread
    
    return create_mock_crypto_quote_event(
        symbol='BTC/USD',
        ask_price=ask_price,
        bid_price=bid_price,
        ask_size=150.0,
        bid_size=200.0
    )


def create_realistic_eth_quote(ask_price: float, spread_pct: float = 0.1) -> Mock:
    """
    Create a realistic ETH/USD quote with proper bid/ask spread.
    
    Args:
        ask_price: Ask price for ETH/USD
        spread_pct: Spread percentage (default: 0.1%)
    
    Returns:
        Mock CryptoQuote object for ETH/USD
    """
    spread = ask_price * (spread_pct / 100)
    bid_price = ask_price - spread
    
    return create_mock_crypto_quote_event(
        symbol='ETH/USD',
        ask_price=ask_price,
        bid_price=bid_price,
        ask_size=500.0,
        bid_size=750.0
    ) 