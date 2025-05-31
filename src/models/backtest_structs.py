"""
Data structures for backtesting strategy logic.

These structures decouple strategy decision-making from execution,
allowing the same logic to be used for both live trading and backtesting.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime
from decimal import Decimal
from enum import Enum


class OrderSide(Enum):
    """Order side enumeration."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type enumeration."""
    LIMIT = "limit"
    MARKET = "market"


@dataclass
class MarketTickInput:
    """
    Market data input for strategy functions.
    
    This represents a single market data point that strategy functions
    use to make decisions.
    """
    timestamp: datetime  # UTC timestamp
    current_ask_price: Decimal  # Current ask price
    current_bid_price: Decimal  # Current bid price
    symbol: str  # Trading symbol (e.g., 'BTC/USD')
    
    # Optional OHLC data for future technical analysis
    ohlc_bar: Optional[Dict[str, Any]] = None


@dataclass
class OrderIntent:
    """
    Represents an intent to place an order.
    
    This is returned by strategy functions to indicate what order
    should be placed, without actually placing it.
    """
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    limit_price: Optional[Decimal] = None  # Required for limit orders
    client_order_id: Optional[str] = None  # Optional client-generated ID


@dataclass
class CycleStateUpdateIntent:
    """
    Represents an intent to update cycle state.
    
    Contains the cycle fields that should be updated immediately
    after placing an order intent, before order confirmation.
    """
    new_status: Optional[str] = None
    new_latest_order_id: Optional[str] = None  # Will be filled with real ID after order placement
    new_latest_order_created_at: Optional[datetime] = None
    new_quantity: Optional[Decimal] = None
    new_average_purchase_price: Optional[Decimal] = None
    new_safety_orders: Optional[int] = None
    new_last_order_fill_price: Optional[Decimal] = None


@dataclass
class TTPStateUpdateIntent:
    """
    Represents an intent to update Trailing Take Profit state.
    
    Used when TTP logic determines state changes are needed.
    """
    new_status: Optional[str] = None
    new_highest_trailing_price: Optional[Decimal] = None


@dataclass
class StrategyAction:
    """
    Complete action returned by strategy functions.
    
    Contains all the intents that should be executed as a result
    of processing a market tick with the current state.
    """
    order_intent: Optional[OrderIntent] = None
    cycle_update_intent: Optional[CycleStateUpdateIntent] = None
    ttp_update_intent: Optional[TTPStateUpdateIntent] = None
    
    def has_action(self) -> bool:
        """Check if this action contains any intents to execute."""
        return (self.order_intent is not None or 
                self.cycle_update_intent is not None or 
                self.ttp_update_intent is not None)


# Convenience functions for creating common action types

def create_buy_order_action(
    symbol: str,
    quantity: Decimal,
    limit_price: Decimal,
    new_status: str = "buying",
    timestamp: Optional[datetime] = None
) -> StrategyAction:
    """Create a StrategyAction for placing a buy order."""
    return StrategyAction(
        order_intent=OrderIntent(
            symbol=symbol,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=quantity,
            limit_price=limit_price
        ),
        cycle_update_intent=CycleStateUpdateIntent(
            new_status=new_status,
            new_latest_order_created_at=timestamp
        )
    )


def create_sell_order_action(
    symbol: str,
    quantity: Decimal,
    new_status: str = "selling",
    limit_price: Optional[Decimal] = None,
    timestamp: Optional[datetime] = None
) -> StrategyAction:
    """Create a StrategyAction for placing a sell order."""
    order_type = OrderType.LIMIT if limit_price else OrderType.MARKET
    
    return StrategyAction(
        order_intent=OrderIntent(
            symbol=symbol,
            side=OrderSide.SELL,
            order_type=order_type,
            quantity=quantity,
            limit_price=limit_price
        ),
        cycle_update_intent=CycleStateUpdateIntent(
            new_status=new_status,
            new_latest_order_created_at=timestamp
        )
    )


def create_ttp_activation_action(
    new_status: str = "trailing",
    highest_trailing_price: Decimal = None
) -> StrategyAction:
    """Create a StrategyAction for TTP activation."""
    return StrategyAction(
        ttp_update_intent=TTPStateUpdateIntent(
            new_status=new_status,
            new_highest_trailing_price=highest_trailing_price
        )
    )


def create_ttp_update_action(
    highest_trailing_price: Decimal
) -> StrategyAction:
    """Create a StrategyAction for TTP price update."""
    return StrategyAction(
        ttp_update_intent=TTPStateUpdateIntent(
            new_highest_trailing_price=highest_trailing_price
        )
    ) 