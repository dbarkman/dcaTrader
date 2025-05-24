"""
Functional tests for database connectivity.
Tests the db_utils module functions.
"""

import logging
import pytest
from unittest.mock import patch, MagicMock
from mysql.connector import Error

from utils.db_utils import get_db_connection, execute_query, check_connection

# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)


@pytest.mark.unit
@patch('utils.db_utils.mysql.connector.connect')
@patch('utils.db_utils.os.getenv')
def test_get_db_connection_success(mock_getenv, mock_connect):
    """Test successful database connection."""
    # Mock environment variables
    mock_getenv.side_effect = lambda key, default=None: {
        'DB_HOST': 'localhost',
        'DB_USER': 'test_user',
        'DB_PASSWORD': 'test_pass',
        'DB_NAME': 'test_db',
        'DB_PORT': '3306'
    }.get(key, default)
    
    # Mock successful connection
    mock_connection = MagicMock()
    mock_connection.is_connected.return_value = True
    mock_connect.return_value = mock_connection
    
    # Test the function
    result = get_db_connection()
    
    # Assertions
    assert result == mock_connection
    mock_connect.assert_called_once_with(
        host='localhost',
        user='test_user',
        password='test_pass',
        database='test_db',
        port=3306,
        autocommit=False
    )


@pytest.mark.unit
@patch('utils.db_utils.mysql.connector.connect')
def test_get_db_connection_failure(mock_connect):
    """Test database connection failure."""
    # Mock connection failure
    mock_connect.side_effect = Error("Connection failed")
    
    # Test the function and expect exception
    with pytest.raises(Error):
        get_db_connection()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_execute_query_fetch_one(mock_get_connection):
    """Test execute_query with fetch_one=True."""
    # Setup mocks
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = {'id': 1, 'name': 'test'}
    mock_connection.cursor.return_value = mock_cursor
    mock_get_connection.return_value = mock_connection
    
    # Test the function
    result = execute_query("SELECT * FROM test WHERE id = %s", (1,), fetch_one=True)
    
    # Assertions
    assert result == {'id': 1, 'name': 'test'}
    mock_cursor.execute.assert_called_once_with("SELECT * FROM test WHERE id = %s", (1,))
    mock_cursor.fetchone.assert_called_once()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_execute_query_fetch_all(mock_get_connection):
    """Test execute_query with fetch_all=True."""
    # Setup mocks
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [{'id': 1}, {'id': 2}]
    mock_connection.cursor.return_value = mock_cursor
    mock_get_connection.return_value = mock_connection
    
    # Test the function
    result = execute_query("SELECT * FROM test", fetch_all=True)
    
    # Assertions
    assert result == [{'id': 1}, {'id': 2}]
    mock_cursor.fetchall.assert_called_once()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_execute_query_commit(mock_get_connection):
    """Test execute_query with commit=True."""
    # Setup mocks
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.lastrowid = 123
    mock_connection.cursor.return_value = mock_cursor
    mock_get_connection.return_value = mock_connection
    
    # Test the function
    result = execute_query("INSERT INTO test (name) VALUES (%s)", ('test',), commit=True)
    
    # Assertions
    assert result == 123
    mock_connection.commit.assert_called_once()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_execute_query_error_rollback(mock_get_connection):
    """Test execute_query handles errors with rollback."""
    # Setup mocks
    mock_connection = MagicMock()
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = Error("Query failed")
    mock_connection.cursor.return_value = mock_cursor
    mock_get_connection.return_value = mock_connection
    
    # Test the function and expect exception
    with pytest.raises(Error):
        execute_query("SELECT * FROM test", fetch_one=True)
    
    # Verify rollback was called
    mock_connection.rollback.assert_called_once()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_connection_test_success(mock_get_connection):
    """Test successful connection test."""
    mock_connection = MagicMock()
    mock_connection.is_connected.return_value = True
    mock_get_connection.return_value = mock_connection
    
    result = check_connection()
    
    assert result == True
    mock_connection.close.assert_called_once()


@pytest.mark.unit
@patch('utils.db_utils.get_db_connection')
def test_connection_test_failure(mock_get_connection):
    """Test failed connection test."""
    mock_get_connection.side_effect = Error("Connection failed")
    
    result = check_connection()
    
    assert result == False 