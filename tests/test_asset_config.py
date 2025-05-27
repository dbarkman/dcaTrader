"""
Functional tests for asset configuration model.
Tests the asset_config module functions.
"""

import logging
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from decimal import Decimal
from mysql.connector import Error

from models.asset_config import DcaAsset, get_asset_config, get_all_enabled_assets, update_asset_config

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


@pytest.mark.unit
def test_dca_asset_from_dict(sample_asset_data):
    """Test creating DcaAsset from dictionary."""
    asset = DcaAsset.from_dict(sample_asset_data)
    
    assert asset.id == 1
    assert asset.asset_symbol == 'BTC/USD'
    assert asset.is_enabled == True
    assert asset.base_order_amount == Decimal('100.00')
    assert asset.safety_order_amount == Decimal('50.00')
    assert asset.max_safety_orders == 5
    assert asset.safety_order_deviation == Decimal('2.0')
    assert asset.take_profit_percent == Decimal('1.5')
    assert asset.ttp_enabled == False
    assert asset.ttp_deviation_percent is None
    assert asset.cooldown_period == 300
    assert asset.buy_order_price_deviation_percent == Decimal('3.0')
    assert asset.last_sell_price == Decimal('50000.00')


@pytest.mark.unit
def test_dca_asset_from_dict_with_ttp_enabled(sample_asset_data):
    """Test creating DcaAsset with TTP enabled."""
    data = sample_asset_data.copy()
    data['ttp_enabled'] = True
    data['ttp_deviation_percent'] = Decimal('0.5')
    
    asset = DcaAsset.from_dict(data)
    assert asset.ttp_enabled == True
    assert asset.ttp_deviation_percent == Decimal('0.5')


@pytest.mark.unit
def test_dca_asset_from_dict_null_last_sell_price(sample_asset_data):
    """Test creating DcaAsset with null last_sell_price."""
    data = sample_asset_data.copy()
    data['last_sell_price'] = None
    
    asset = DcaAsset.from_dict(data)
    assert asset.last_sell_price is None


@pytest.mark.unit
def test_dca_asset_from_dict_null_ttp_deviation(sample_asset_data):
    """Test creating DcaAsset with null ttp_deviation_percent."""
    data = sample_asset_data.copy()
    data['ttp_enabled'] = False
    data['ttp_deviation_percent'] = None
    
    asset = DcaAsset.from_dict(data)
    assert asset.ttp_enabled == False
    assert asset.ttp_deviation_percent is None


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_get_asset_config_found(mock_execute_query, sample_asset_data):
    """Test getting asset config when asset exists."""
    mock_execute_query.return_value = sample_asset_data
    
    result = get_asset_config('BTC/USD')
    
    assert isinstance(result, DcaAsset)
    assert result.asset_symbol == 'BTC/USD'
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_get_asset_config_not_found(mock_execute_query):
    """Test getting asset config when asset doesn't exist."""
    mock_execute_query.return_value = None
    
    result = get_asset_config('NONEXISTENT/USD')
    
    assert result is None
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_get_asset_config_error(mock_execute_query):
    """Test getting asset config when database error occurs."""
    mock_execute_query.side_effect = Error("Database error")
    
    with pytest.raises(Error):
        get_asset_config('BTC/USD')


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_get_all_enabled_assets_found(mock_execute_query, sample_asset_data):
    """Test getting all enabled assets when assets exist."""
    asset1_data = sample_asset_data.copy()
    asset2_data = sample_asset_data.copy()
    asset2_data['id'] = 2
    asset2_data['asset_symbol'] = 'ETH/USD'
    
    mock_execute_query.return_value = [asset1_data, asset2_data]
    
    result = get_all_enabled_assets()
    
    assert len(result) == 2
    assert isinstance(result[0], DcaAsset)
    assert isinstance(result[1], DcaAsset)
    assert result[0].asset_symbol == 'BTC/USD'
    assert result[1].asset_symbol == 'ETH/USD'


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_get_all_enabled_assets_empty(mock_execute_query):
    """Test getting all enabled assets when no assets exist."""
    mock_execute_query.return_value = []
    
    result = get_all_enabled_assets()
    
    assert len(result) == 0
    assert isinstance(result, list)


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_update_asset_config_success(mock_execute_query):
    """Test successful asset config update."""
    mock_execute_query.return_value = 1  # 1 row affected
    
    updates = {
        'is_enabled': False,
        'last_sell_price': Decimal('51000.00')
    }
    
    result = update_asset_config(1, updates)
    
    assert result == True
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_update_asset_config_no_updates(mock_execute_query):
    """Test asset config update with no updates."""
    result = update_asset_config(1, {})
    
    assert result == False
    mock_execute_query.assert_not_called()


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_update_asset_config_no_rows_affected(mock_execute_query):
    """Test asset config update when no rows are affected."""
    mock_execute_query.return_value = 0  # 0 rows affected
    
    updates = {'is_enabled': False}
    
    result = update_asset_config(999, updates)  # Non-existent ID
    
    assert result == False


@pytest.mark.unit
@patch('models.asset_config.execute_query')
def test_update_asset_config_error(mock_execute_query):
    """Test asset config update when database error occurs."""
    mock_execute_query.side_effect = Error("Database error")
    
    updates = {'is_enabled': False}
    
    with pytest.raises(Error):
        update_asset_config(1, updates) 