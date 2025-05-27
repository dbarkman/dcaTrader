"""
Functional tests for cycle data model.
Tests the cycle_data module functions.
"""

import logging
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
from decimal import Decimal
from mysql.connector import Error

from models.cycle_data import DcaCycle, get_latest_cycle, create_cycle, update_cycle, get_cycle_by_id

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


@pytest.mark.unit
def test_dca_cycle_from_dict(sample_cycle_data):
    """Test creating DcaCycle from dictionary."""
    cycle = DcaCycle.from_dict(sample_cycle_data)
    
    assert cycle.id == 1
    assert cycle.asset_id == 1
    assert cycle.status == 'watching'
    assert cycle.quantity == Decimal('0.1')
    assert cycle.average_purchase_price == Decimal('50000.00')
    assert cycle.safety_orders == 2
    assert cycle.latest_order_id == 'order123'
    assert cycle.last_order_fill_price == Decimal('49000.00')
    assert cycle.highest_trailing_price is None
    assert cycle.completed_at is None
    assert cycle.sell_price is None


@pytest.mark.unit
def test_dca_cycle_from_dict_with_trailing_status(sample_cycle_data):
    """Test creating DcaCycle with trailing status and highest_trailing_price."""
    data = sample_cycle_data.copy()
    data['status'] = 'trailing'
    data['highest_trailing_price'] = Decimal('52000.00')
    
    cycle = DcaCycle.from_dict(data)
    assert cycle.status == 'trailing'
    assert cycle.highest_trailing_price == Decimal('52000.00')


@pytest.mark.unit
def test_dca_cycle_from_dict_null_values(sample_cycle_data):
    """Test creating DcaCycle with null optional values."""
    data = sample_cycle_data.copy()
    data['latest_order_id'] = None
    data['last_order_fill_price'] = None
    data['highest_trailing_price'] = None
    data['sell_price'] = None
    
    cycle = DcaCycle.from_dict(data)
    assert cycle.latest_order_id is None
    assert cycle.last_order_fill_price is None
    assert cycle.highest_trailing_price is None
    assert cycle.sell_price is None


@pytest.mark.unit
def test_dca_cycle_from_dict_completed_with_sell_price(sample_cycle_data):
    """Test creating DcaCycle with completed status and sell_price."""
    data = sample_cycle_data.copy()
    data['status'] = 'complete'
    data['sell_price'] = Decimal('51500.00')
    data['completed_at'] = datetime.now()
    
    cycle = DcaCycle.from_dict(data)
    assert cycle.status == 'complete'
    assert cycle.sell_price == Decimal('51500.00')
    assert cycle.completed_at is not None


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_get_latest_cycle_found(mock_execute_query, sample_cycle_data):
    """Test getting latest cycle when cycle exists."""
    mock_execute_query.return_value = sample_cycle_data
    
    result = get_latest_cycle(1)
    
    assert isinstance(result, DcaCycle)
    assert result.asset_id == 1
    assert result.status == 'watching'
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_get_latest_cycle_not_found(mock_execute_query):
    """Test getting latest cycle when no cycle exists."""
    mock_execute_query.return_value = None
    
    result = get_latest_cycle(999)
    
    assert result is None
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_get_latest_cycle_error(mock_execute_query):
    """Test getting latest cycle when database error occurs."""
    mock_execute_query.side_effect = Error("Database error")
    
    with pytest.raises(Error):
        get_latest_cycle(1)


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_create_cycle_success(mock_execute_query, sample_cycle_data):
    """Test successful cycle creation."""
    # Mock the INSERT returning cycle_id = 123
    # Then mock the subsequent SELECT to fetch the created cycle
    mock_execute_query.side_effect = [
        123,  # INSERT result (last_insert_id)
        sample_cycle_data  # SELECT result
    ]
    
    result = create_cycle(
        asset_id=1,
        status='watching',
        quantity=Decimal('0.1'),
        average_purchase_price=Decimal('50000.00'),
        safety_orders=2
    )
    
    assert isinstance(result, DcaCycle)
    assert result.asset_id == 1
    assert result.status == 'watching'
    assert mock_execute_query.call_count == 2


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_create_cycle_with_defaults(mock_execute_query, sample_cycle_data):
    """Test cycle creation with default values."""
    created_cycle_data = sample_cycle_data.copy()
    created_cycle_data['quantity'] = Decimal('0')
    created_cycle_data['average_purchase_price'] = Decimal('0')
    created_cycle_data['safety_orders'] = 0
    created_cycle_data['latest_order_id'] = None
    created_cycle_data['last_order_fill_price'] = None
    created_cycle_data['highest_trailing_price'] = None
    created_cycle_data['completed_at'] = None
    
    mock_execute_query.side_effect = [
        123,  # INSERT result
        created_cycle_data  # SELECT result
    ]
    
    result = create_cycle(asset_id=1, status='watching')
    
    assert isinstance(result, DcaCycle)
    assert result.quantity == Decimal('0')
    assert result.safety_orders == 0
    assert result.latest_order_id is None
    assert result.highest_trailing_price is None


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_create_cycle_with_trailing_status(mock_execute_query, sample_cycle_data):
    """Test cycle creation with trailing status and highest_trailing_price."""
    created_cycle_data = sample_cycle_data.copy()
    created_cycle_data['status'] = 'trailing'
    created_cycle_data['highest_trailing_price'] = Decimal('52000.00')
    
    mock_execute_query.side_effect = [
        123,  # INSERT result
        created_cycle_data  # SELECT result
    ]
    
    result = create_cycle(
        asset_id=1, 
        status='trailing',
        highest_trailing_price=Decimal('52000.00')
    )
    
    assert isinstance(result, DcaCycle)
    assert result.status == 'trailing'
    assert result.highest_trailing_price == Decimal('52000.00')


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_create_cycle_no_id_returned(mock_execute_query):
    """Test cycle creation when no ID is returned."""
    mock_execute_query.return_value = None
    
    with pytest.raises(Error):
        create_cycle(asset_id=1, status='watching')


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_create_cycle_fetch_fails(mock_execute_query):
    """Test cycle creation when fetching created cycle fails."""
    mock_execute_query.side_effect = [
        123,  # INSERT succeeds
        None  # SELECT fails
    ]
    
    with pytest.raises(Error):
        create_cycle(asset_id=1, status='watching')


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_update_cycle_success(mock_execute_query):
    """Test successful cycle update."""
    mock_execute_query.return_value = 1  # 1 row affected
    
    updates = {
        'status': 'buying',
        'latest_order_id': 'order456',
        'quantity': Decimal('0.2')
    }
    
    result = update_cycle(1, updates)
    
    assert result == True
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_update_cycle_no_updates(mock_execute_query):
    """Test cycle update with no updates."""
    result = update_cycle(1, {})
    
    assert result == False
    mock_execute_query.assert_not_called()


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_update_cycle_no_rows_affected(mock_execute_query):
    """Test cycle update when no rows are affected."""
    mock_execute_query.return_value = 0  # 0 rows affected
    
    updates = {'status': 'complete'}
    
    result = update_cycle(999, updates)  # Non-existent ID
    
    assert result == False


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_update_cycle_error(mock_execute_query):
    """Test cycle update when database error occurs."""
    mock_execute_query.side_effect = Error("Database error")
    
    updates = {'status': 'complete'}
    
    with pytest.raises(Error):
        update_cycle(1, updates)


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_get_cycle_by_id_found(mock_execute_query, sample_cycle_data):
    """Test getting cycle by ID when cycle exists."""
    mock_execute_query.return_value = sample_cycle_data
    
    result = get_cycle_by_id(1)
    
    assert isinstance(result, DcaCycle)
    assert result.id == 1
    mock_execute_query.assert_called_once()


@pytest.mark.unit
@patch('models.cycle_data.execute_query')
def test_get_cycle_by_id_not_found(mock_execute_query):
    """Test getting cycle by ID when cycle doesn't exist."""
    mock_execute_query.return_value = None
    
    result = get_cycle_by_id(999)
    
    assert result is None
    mock_execute_query.assert_called_once() 