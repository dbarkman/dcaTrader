#!/usr/bin/env python3
"""
Dynamic precision formatting utilities for DCA Trading Bot.

Handles proper formatting of prices and quantities based on magnitude,
ensuring micro-cap tokens like PEPE/SHIB display correctly.
"""

from decimal import Decimal
import decimal
from typing import Union, Optional


def format_price(price: Union[Decimal, float, str, None], symbol: Optional[str] = None) -> str:
    """
    Format price with appropriate precision based on magnitude.
    
    Args:
        price: Price value to format
        symbol: Optional symbol for future asset-specific overrides
    
    Returns:
        Formatted price string with appropriate precision
        
    Examples:
        format_price(109589.17) -> "$109,589.17"     (BTC)
        format_price(267.7266) -> "$267.7266"       (AAVE)
        format_price(0.0000140860) -> "$0.0000140860" (PEPE)
    """
    if price is None:
        return "N/A"
    
    try:
        if price == "":
            return "N/A"
        price_decimal = Decimal(str(price))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return "N/A"
    
    # Dynamic precision based on price magnitude
    if price_decimal >= Decimal('1000'):
        return f"${price_decimal:,.2f}"      # $109,589.17 (BTC)
    elif price_decimal >= Decimal('1'):
        return f"${price_decimal:.4f}"       # $267.7266 (AAVE)
    elif price_decimal >= Decimal('0.01'):
        return f"${price_decimal:.6f}"       # $0.123456 (sub-dollar)
    else:
        return f"${price_decimal:.10f}"      # $0.0000140860 (PEPE/SHIB)


def format_quantity(quantity: Union[Decimal, float, str, None], symbol: Optional[str] = None) -> str:
    """
    Format quantity with appropriate precision.
    
    Args:
        quantity: Quantity value to format
        symbol: Optional symbol for future asset-specific formatting
    
    Returns:
        Formatted quantity string
        
    Examples:
        format_quantity(5950381.895565205) -> "5,950,381.90"  (PEPE)
        format_quantity(1.537113) -> "1.537113"              (AVAX)
        format_quantity(0.13430418) -> "0.13430418"          (AAVE)
    """
    if quantity is None:
        return "N/A"
    
    try:
        if quantity == "":
            return "N/A"
        qty_decimal = Decimal(str(quantity))
    except (ValueError, TypeError, decimal.InvalidOperation):
        return "N/A"
    
    # Large quantities (millions of tokens) vs small quantities
    if qty_decimal >= Decimal('1000000'):
        return f"{qty_decimal:,.2f}"         # 5,950,381.90 PEPE
    elif qty_decimal >= Decimal('100000'):
        return f"{qty_decimal:,.6f}"         # 999,999.990000 (large but < 1M)
    elif qty_decimal >= Decimal('1'):
        return f"{qty_decimal:.6f}"          # 1.537113 AVAX
    else:
        return f"{qty_decimal:.8f}"          # 0.13430418 AAVE


def format_price_simple(price: Union[Decimal, float, str, None]) -> str:
    """
    Format price without dollar sign for calculations display.
    
    Args:
        price: Price value to format
    
    Returns:
        Formatted price string without currency symbol
    """
    formatted = format_price(price)
    return formatted.replace('$', '') if formatted != "N/A" else "N/A"


def format_percentage(percentage: Union[Decimal, float, str, None], decimal_places: int = 2) -> str:
    """
    Format percentage with specified decimal places.
    
    Args:
        percentage: Percentage value to format
        decimal_places: Number of decimal places to show
    
    Returns:
        Formatted percentage string
        
    Examples:
        format_percentage(2.5) -> "2.50%"
        format_percentage(0.9, 3) -> "0.900%"
    """
    if percentage is None:
        return "N/A"
    
    try:
        if percentage == "":
            return "N/A"
        pct_decimal = Decimal(str(percentage))
        return f"{pct_decimal:.{decimal_places}f}%"
    except (ValueError, TypeError, decimal.InvalidOperation):
        return "N/A" 