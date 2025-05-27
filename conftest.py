"""
Pytest configuration and shared fixtures.
This file is automatically loaded by pytest and provides shared setup.
"""

import os
import sys
import pytest
from pathlib import Path

# Add src to Python path for all tests
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Markers for test categorization
pytest_plugins = []


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent


@pytest.fixture(scope="session")
def src_path(project_root):
    """Return the src directory path."""
    return project_root / "src"


@pytest.fixture
def sample_asset_data():
    """Sample asset data for testing."""
    from decimal import Decimal
    from datetime import datetime
    
    return {
        'id': 1,
        'asset_symbol': 'BTC/USD',
        'is_enabled': True,
        'base_order_amount': Decimal('100.00'),
        'safety_order_amount': Decimal('50.00'),
        'max_safety_orders': 5,
        'safety_order_deviation': Decimal('2.0'),
        'take_profit_percent': Decimal('1.5'),
        'ttp_enabled': False,
        'ttp_deviation_percent': None,
        'cooldown_period': 300,
        'buy_order_price_deviation_percent': Decimal('3.0'),
        'last_sell_price': Decimal('50000.00'),
        'created_at': datetime.now(),
        'updated_at': datetime.now()
    }


@pytest.fixture
def sample_cycle_data():
    """Sample cycle data for testing."""
    from decimal import Decimal
    from datetime import datetime
    
    return {
        'id': 1,
        'asset_id': 1,
        'status': 'watching',
        'quantity': Decimal('0.1'),
        'average_purchase_price': Decimal('50000.00'),
        'safety_orders': 2,
        'latest_order_id': 'order123',
        'latest_order_created_at': datetime.now(),
        'last_order_fill_price': Decimal('49000.00'),
        'highest_trailing_price': None,
        'completed_at': None,
        'sell_price': None,
        'created_at': datetime.now(),
        'updated_at': datetime.now()
    } 