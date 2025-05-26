#!/usr/bin/env python3
"""
Tests for dynamic precision formatting utilities.
"""

import pytest
from decimal import Decimal
from src.utils.formatting import format_price, format_quantity, format_price_simple, format_percentage


class TestFormatPrice:
    """Test price formatting with dynamic precision."""
    
    def test_high_value_prices(self):
        """Test formatting for high-value assets like BTC."""
        # BTC-level prices (>= $1000)
        assert format_price(109589.17) == "$109,589.17"
        assert format_price(Decimal('109589.17')) == "$109,589.17"
        assert format_price("109589.17") == "$109,589.17"
        assert format_price(1000.00) == "$1,000.00"
        assert format_price(1000.1) == "$1,000.10"
    
    def test_medium_value_prices(self):
        """Test formatting for medium-value assets like AAVE."""
        # AAVE-level prices ($1 to $999.99)
        assert format_price(267.7266) == "$267.7266"
        assert format_price(Decimal('267.7266')) == "$267.7266"
        assert format_price(1.0) == "$1.0000"
        assert format_price(999.99) == "$999.9900"
    
    def test_sub_dollar_prices(self):
        """Test formatting for sub-dollar assets."""
        # Sub-dollar but >= $0.01
        assert format_price(0.5) == "$0.500000"
        assert format_price(0.123456) == "$0.123456"
        assert format_price(0.01) == "$0.010000"
    
    def test_micro_cap_prices(self):
        """Test formatting for micro-cap tokens like PEPE/SHIB."""
        # Micro-cap prices (< $0.01)
        assert format_price(0.0000140860) == "$0.0000140860"
        assert format_price(Decimal('0.0000140860')) == "$0.0000140860"
        assert format_price(0.0000145910) == "$0.0000145910"
        assert format_price(0.009999) == "$0.0099990000"
    
    def test_edge_cases(self):
        """Test edge cases and error handling."""
        assert format_price(None) == "N/A"
        assert format_price("") == "N/A"
        assert format_price("invalid") == "N/A"
        assert format_price(0) == "$0.0000000000"
        assert format_price(-1.5) == "$-1.5000000000"  # Negative prices (micro-cap range)
    
    def test_symbol_parameter(self):
        """Test that symbol parameter is accepted (for future use)."""
        # Symbol parameter should be accepted but not affect output currently
        assert format_price(100.5, "BTC/USD") == "$100.5000"
        assert format_price(0.00001, "PEPE/USD") == "$0.0000100000"


class TestFormatQuantity:
    """Test quantity formatting with appropriate precision."""
    
    def test_large_quantities(self):
        """Test formatting for large quantities (millions of tokens)."""
        # PEPE/SHIB quantities (>= 1,000,000)
        assert format_quantity(5950381.895565205) == "5,950,381.90"
        assert format_quantity(Decimal('5950381.895565205')) == "5,950,381.90"
        assert format_quantity(1000000) == "1,000,000.00"
        assert format_quantity(1000000.1) == "1,000,000.10"
    
    def test_medium_quantities(self):
        """Test formatting for medium quantities."""
        # Regular quantities (>= 1)
        assert format_quantity(1.537113) == "1.537113"
        assert format_quantity(Decimal('1.537113')) == "1.537113"
        assert format_quantity(1.0) == "1.000000"
        assert format_quantity(999999.99) == "999,999.990000"
    
    def test_small_quantities(self):
        """Test formatting for small quantities."""
        # Small quantities (< 1)
        assert format_quantity(0.13430418) == "0.13430418"
        assert format_quantity(Decimal('0.13430418')) == "0.13430418"
        assert format_quantity(0.00109367) == "0.00109367"
        assert format_quantity(0.99999999) == "0.99999999"
    
    def test_edge_cases(self):
        """Test edge cases and error handling."""
        assert format_quantity(None) == "N/A"
        assert format_quantity("") == "N/A"
        assert format_quantity("invalid") == "N/A"
        assert format_quantity(0) == "0.00000000"
    
    def test_symbol_parameter(self):
        """Test that symbol parameter is accepted (for future use)."""
        # Symbol parameter should be accepted but not affect output currently
        assert format_quantity(1000000, "PEPE/USD") == "1,000,000.00"
        assert format_quantity(0.5, "BTC/USD") == "0.50000000"


class TestFormatPriceSimple:
    """Test price formatting without dollar sign."""
    
    def test_removes_dollar_sign(self):
        """Test that dollar sign is removed from formatted prices."""
        assert format_price_simple(109589.17) == "109,589.17"
        assert format_price_simple(267.7266) == "267.7266"
        assert format_price_simple(0.0000140860) == "0.0000140860"
    
    def test_handles_none(self):
        """Test handling of None values."""
        assert format_price_simple(None) == "N/A"


class TestFormatPercentage:
    """Test percentage formatting."""
    
    def test_default_precision(self):
        """Test default 2 decimal places."""
        assert format_percentage(2.5) == "2.50%"
        assert format_percentage(Decimal('2.5')) == "2.50%"
        assert format_percentage("2.5") == "2.50%"
        assert format_percentage(0.9) == "0.90%"
    
    def test_custom_precision(self):
        """Test custom decimal places."""
        assert format_percentage(0.9, 3) == "0.900%"
        assert format_percentage(2.5, 1) == "2.5%"
        assert format_percentage(2.5, 0) == "2%"  # Truncates to integer
    
    def test_edge_cases(self):
        """Test edge cases and error handling."""
        assert format_percentage(None) == "N/A"
        assert format_percentage("") == "N/A"
        assert format_percentage("invalid") == "N/A"
        assert format_percentage(0) == "0.00%"


class TestRealWorldExamples:
    """Test with real-world data from the DCA bot."""
    
    def test_btc_example(self):
        """Test with real BTC data."""
        price = Decimal('109589.17')
        quantity = Decimal('0.00109367')
        
        assert format_price(price) == "$109,589.17"
        assert format_quantity(quantity) == "0.00109367"
    
    def test_aave_example(self):
        """Test with real AAVE data."""
        price = Decimal('267.7266')
        quantity = Decimal('0.134304182')
        
        assert format_price(price) == "$267.7266"
        assert format_quantity(quantity) == "0.13430418"
    
    def test_pepe_example(self):
        """Test with real PEPE data."""
        price = Decimal('0.0000140860')
        quantity = Decimal('5950381.895565205')
        
        assert format_price(price) == "$0.0000140860"
        assert format_quantity(quantity) == "5,950,381.90"
    
    def test_shib_example(self):
        """Test with real SHIB data."""
        price = Decimal('0.0000145910')
        quantity = Decimal('2464484.836193710')
        
        assert format_price(price) == "$0.0000145910"
        assert format_quantity(quantity) == "2,464,484.84"
    
    def test_comparison_with_old_formatting(self):
        """Test that new formatting is better than old hardcoded formatting."""
        pepe_price = Decimal('0.0000140860')
        
        # Old formatting (broken)
        old_format = f"${pepe_price:.4f}"  # Results in "$0.0000"
        
        # New formatting (fixed)
        new_format = format_price(pepe_price)  # Results in "$0.0000140860"
        
        assert old_format == "$0.0000"  # Demonstrates the problem
        assert new_format == "$0.0000140860"  # Shows the fix
        assert new_format != old_format  # Confirms they're different


if __name__ == "__main__":
    pytest.main([__file__, "-v"]) 