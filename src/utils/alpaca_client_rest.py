"""
Alpaca REST API Client Utilities

This module provides functions to interact with Alpaca's REST API for:
- Account information
- Market data (crypto prices)
- Order placement, retrieval, and cancellation

Uses the alpaca-py SDK and loads credentials from environment variables.
"""

import os
import logging
from typing import Optional
from dotenv import load_dotenv

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import LimitOrderRequest, MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, OrderType
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoLatestTradeRequest
from alpaca.trading.models import TradeAccount, Order

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def get_trading_client() -> TradingClient:
    """
    Initialize and return an Alpaca TradingClient using credentials from .env
    
    Returns:
        TradingClient: Initialized Alpaca trading client
        
    Raises:
        ValueError: If required environment variables are missing
    """
    api_key = os.getenv('APCA_API_KEY_ID')
    api_secret = os.getenv('APCA_API_SECRET_KEY')
    base_url = os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    
    if not api_key or not api_secret:
        raise ValueError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in .env file")
    
    # Determine if this is paper trading
    paper = 'paper-api' in base_url
    
    logger.info(f"Initializing Alpaca TradingClient (paper={paper})")
    
    return TradingClient(
        api_key=api_key,
        secret_key=api_secret,
        paper=paper
    )


def get_account_info(client: TradingClient) -> Optional[TradeAccount]:
    """
    Fetch account information from Alpaca
    
    Args:
        client: Initialized TradingClient
        
    Returns:
        TradeAccount object or None if error occurs
    """
    try:
        account = client.get_account()
        logger.info(f"Account retrieved: {account.account_number}")
        return account
    except Exception as e:
        logger.error(f"Error fetching account info: {e}")
        return None


def get_latest_crypto_price(client: TradingClient, symbol: str) -> Optional[float]:
    """
    Fetch the latest trade price for a crypto symbol
    
    Args:
        client: Initialized TradingClient
        symbol: Crypto symbol (e.g., 'BTC/USD')
        
    Returns:
        Latest trade price as float or None if error/no data
    """
    try:
        # Use CryptoHistoricalDataClient for market data
        api_key = os.getenv('APCA_API_KEY_ID')
        api_secret = os.getenv('APCA_API_SECRET_KEY')
        
        crypto_client = CryptoHistoricalDataClient(
            api_key=api_key,
            secret_key=api_secret
        )
        
        request = CryptoLatestTradeRequest(symbol_or_symbols=symbol)
        latest_trade = crypto_client.get_crypto_latest_trade(request)
        
        if symbol in latest_trade:
            price = float(latest_trade[symbol].price)
            logger.info(f"Latest price for {symbol}: ${price}")
            return price
        else:
            logger.warning(f"No trade data found for symbol: {symbol}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching latest crypto price for {symbol}: {e}")
        return None


def place_limit_buy_order(
    client: TradingClient, 
    symbol: str, 
    qty: float, 
    limit_price: float, 
    time_in_force: str = 'gtc'
) -> Optional[Order]:
    """
    Place a limit BUY order
    
    Args:
        client: Initialized TradingClient
        symbol: Asset symbol (e.g., 'BTC/USD')
        qty: Quantity to buy
        limit_price: Limit price for the order
        time_in_force: Time in force ('day', 'gtc', etc.)
        
    Returns:
        Order object if successful, None if error
    """
    try:
        # Convert time_in_force string to enum
        tif_mapping = {
            'day': TimeInForce.DAY,
            'gtc': TimeInForce.GTC,
            'ioc': TimeInForce.IOC,
            'fok': TimeInForce.FOK
        }
        
        tif_enum = tif_mapping.get(time_in_force.lower(), TimeInForce.DAY)
        
        order_request = LimitOrderRequest(
            symbol=symbol,
            qty=qty,
            side=OrderSide.BUY,
            time_in_force=tif_enum,
            limit_price=limit_price
        )
        
        order = client.submit_order(order_request)
        logger.info(f"Limit BUY order placed: {order.id} for {qty} {symbol} @ ${limit_price}")
        return order
        
    except Exception as e:
        logger.error(f"Error placing limit buy order for {symbol}: {e}")
        return None


def get_open_orders(client: TradingClient) -> list[Order]:
    """
    Fetch all open orders from Alpaca
    
    Args:
        client: Initialized TradingClient
        
    Returns:
        List of Order objects (empty list if error or no orders)
    """
    try:
        orders = client.get_orders()
        logger.info(f"Retrieved {len(orders)} open orders")
        return orders
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}")
        return []


def cancel_order(client: TradingClient, order_id: str) -> bool:
    """
    Cancel an order by ID
    
    Args:
        client: Initialized TradingClient
        order_id: Alpaca order ID to cancel
        
    Returns:
        True if cancellation successful/acknowledged, False if error
    """
    try:
        client.cancel_order_by_id(order_id)
        logger.info(f"Order {order_id} cancellation requested")
        return True
    except Exception as e:
        logger.error(f"Error canceling order {order_id}: {e}")
        return False 