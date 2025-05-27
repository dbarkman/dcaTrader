"""
Functional tests for Alpaca REST API client utilities
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import os

# Import the functions we want to test
from src.utils.alpaca_client_rest import (
    get_trading_client,
    get_account_info,
    get_latest_crypto_price,
    get_latest_crypto_quote,
    get_api_credentials_from_client
)


@pytest.mark.unit
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'test_key_id',
    'APCA_API_SECRET_KEY': 'test_secret_key',
    'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets'
})
@patch('src.utils.alpaca_client_rest.TradingClient')
def test_get_trading_client_initialization(mock_trading_client):
    """Test that get_trading_client initializes correctly with environment variables"""
    
    # Mock the TradingClient constructor
    mock_client_instance = Mock()
    mock_trading_client.return_value = mock_client_instance
    
    # Call the function
    result = get_trading_client()
    
    # Verify TradingClient was called with correct parameters
    mock_trading_client.assert_called_once_with(
        api_key='test_key_id',
        secret_key='test_secret_key',
        paper=True  # Should be True because URL contains 'paper-api'
    )
    
    # Verify the result is the mocked client instance
    assert result == mock_client_instance


@pytest.mark.unit
@patch.dict(os.environ, {}, clear=True)  # Clear environment variables
def test_get_trading_client_missing_credentials():
    """Test that get_trading_client raises ValueError when credentials are missing"""
    
    with pytest.raises(ValueError) as exc_info:
        get_trading_client()
    
    assert "APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set" in str(exc_info.value)


@pytest.mark.unit
def test_get_account_info_parsing():
    """Test that get_account_info correctly processes account data"""
    
    # Create a mock TradingClient
    mock_client = Mock()
    
    # Create a mock TradeAccount object
    mock_account = Mock()
    mock_account.account_number = "TEST123456"
    mock_account.buying_power = "10000.00"
    mock_account.cash = "5000.00"
    
    # Configure the mock client to return our mock account
    mock_client.get_account.return_value = mock_account
    
    # Call the function
    result = get_account_info(mock_client)
    
    # Verify the client method was called
    mock_client.get_account.assert_called_once()
    
    # Verify the result is our mock account
    assert result == mock_account
    assert result.account_number == "TEST123456"


@pytest.mark.unit
def test_get_account_info_api_error():
    """Test that get_account_info handles API errors gracefully"""
    
    # Create a mock TradingClient that raises an exception
    mock_client = Mock()
    mock_client.get_account.side_effect = Exception("API Error")
    
    # Call the function
    result = get_account_info(mock_client)
    
    # Verify it returns None on error
    assert result is None
    
    # Verify the client method was called
    mock_client.get_account.assert_called_once()


@pytest.mark.unit
@patch('src.utils.alpaca_client_rest.CryptoHistoricalDataClient')
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'test_key_id',
    'APCA_API_SECRET_KEY': 'test_secret_key'
})
def test_get_latest_crypto_price_parsing(mock_crypto_client_class):
    """Test that get_latest_crypto_price correctly processes price data"""
    
    # Create mock TradingClient (not used in this function but passed as parameter)
    mock_trading_client = Mock()
    
    # Create mock crypto data client
    mock_crypto_client = Mock()
    mock_crypto_client_class.return_value = mock_crypto_client
    
    # Create mock trade data
    mock_trade = Mock()
    mock_trade.price = 45000.50
    
    # Configure the mock to return trade data
    mock_crypto_client.get_crypto_latest_trade.return_value = {
        'BTC/USD': mock_trade
    }
    
    # Call the function
    result = get_latest_crypto_price(mock_trading_client, 'BTC/USD')
    
    # Verify the crypto client was initialized correctly (no paper parameter)
    mock_crypto_client_class.assert_called_once_with(
        api_key='test_key_id',
        secret_key='test_secret_key'
    )
    
    # Verify the get_crypto_latest_trade method was called
    mock_crypto_client.get_crypto_latest_trade.assert_called_once()
    
    # Verify the result is the expected price
    assert result == 45000.50


@pytest.mark.unit
@patch('src.utils.alpaca_client_rest.CryptoHistoricalDataClient')
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'test_key_id',
    'APCA_API_SECRET_KEY': 'test_secret_key'
})
def test_get_latest_crypto_price_no_data(mock_crypto_client_class):
    """Test that get_latest_crypto_price handles missing symbol data"""
    
    # Create mock TradingClient
    mock_trading_client = Mock()
    
    # Create mock crypto data client
    mock_crypto_client = Mock()
    mock_crypto_client_class.return_value = mock_crypto_client
    
    # Configure the mock to return empty data (symbol not found)
    mock_crypto_client.get_crypto_latest_trade.return_value = {}
    
    # Call the function
    result = get_latest_crypto_price(mock_trading_client, 'INVALID/USD')
    
    # Verify the result is None when no data found
    assert result is None


@pytest.mark.unit
@patch('src.utils.alpaca_client_rest.CryptoHistoricalDataClient')
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'test_key_id',
    'APCA_API_SECRET_KEY': 'test_secret_key'
})
def test_get_latest_crypto_price_api_error(mock_crypto_client_class):
    """Test that get_latest_crypto_price handles API errors gracefully"""
    
    # Create mock TradingClient
    mock_trading_client = Mock()
    
    # Create mock crypto data client that raises an exception
    mock_crypto_client = Mock()
    mock_crypto_client_class.return_value = mock_crypto_client
    mock_crypto_client.get_crypto_latest_trade.side_effect = Exception("API Error")
    
    # Call the function
    result = get_latest_crypto_price(mock_trading_client, 'BTC/USD')
    
    # Verify it returns None on error
    assert result is None


@pytest.mark.unit
@patch('src.utils.alpaca_client_rest.CryptoHistoricalDataClient')
def test_get_latest_crypto_price_with_provided_keys(mock_crypto_client_class):
    """Test that get_latest_crypto_price works with directly provided API keys"""
    
    # Create mock TradingClient
    mock_trading_client = Mock()
    
    # Create mock crypto data client
    mock_crypto_client = Mock()
    mock_crypto_client_class.return_value = mock_crypto_client
    
    # Create mock trade data
    mock_trade = Mock()
    mock_trade.price = 45000.50
    
    # Configure the mock to return trade data
    mock_crypto_client.get_crypto_latest_trade.return_value = {
        'BTC/USD': mock_trade
    }
    
    # Call the function with provided keys (no environment variables needed)
    result = get_latest_crypto_price(
        mock_trading_client, 
        'BTC/USD',
        api_key='direct_key',
        secret_key='direct_secret',
        paper=False  # This parameter is ignored for crypto client
    )
    
    # Verify the crypto client was initialized with provided keys (no paper parameter)
    mock_crypto_client_class.assert_called_once_with(
        api_key='direct_key',
        secret_key='direct_secret'
    )
    
    # Verify the result is the expected price
    assert result == 45000.50


@pytest.mark.unit
@patch('src.utils.alpaca_client_rest.CryptoHistoricalDataClient')
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'test_key_id',
    'APCA_API_SECRET_KEY': 'test_secret_key',
    'APCA_API_BASE_URL': 'https://api.alpaca.markets'  # Live trading URL
})
def test_get_latest_crypto_quote_live_trading(mock_crypto_client_class):
    """Test that get_latest_crypto_quote correctly processes quote data"""
    
    # Create mock TradingClient
    mock_trading_client = Mock()
    
    # Create mock crypto data client
    mock_crypto_client = Mock()
    mock_crypto_client_class.return_value = mock_crypto_client
    
    # Create mock quote data
    mock_quote = Mock()
    mock_quote.bid_price = 44950.0
    mock_quote.ask_price = 45050.0
    
    # Configure the mock to return quote data
    mock_crypto_client.get_crypto_latest_quote.return_value = {
        'BTC/USD': mock_quote
    }
    
    # Call the function
    result = get_latest_crypto_quote(mock_trading_client, 'BTC/USD')
    
    # Verify the crypto client was initialized correctly (no paper parameter)
    mock_crypto_client_class.assert_called_once_with(
        api_key='test_key_id',
        secret_key='test_secret_key'
    )
    
    # Verify the result contains bid/ask prices
    assert result == {'bid': 44950.0, 'ask': 45050.0}


@pytest.mark.unit
def test_get_api_credentials_from_client():
    """Test extracting API credentials from a TradingClient"""
    
    # Create mock TradingClient with private attributes
    mock_client = Mock()
    mock_client._api_key = 'extracted_key'
    mock_client._secret_key = 'extracted_secret'
    mock_client._paper = True
    
    # Call the helper function
    api_key, secret_key, paper = get_api_credentials_from_client(mock_client)
    
    # Verify the credentials were extracted correctly
    assert api_key == 'extracted_key'
    assert secret_key == 'extracted_secret'
    assert paper == True


@pytest.mark.unit
@patch.dict(os.environ, {
    'APCA_API_KEY_ID': 'fallback_key',
    'APCA_API_SECRET_KEY': 'fallback_secret',
    'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets'
})
def test_get_api_credentials_from_client_fallback():
    """Test that get_api_credentials_from_client falls back to environment variables"""
    
    # Create a simple object without the private attributes
    class MockClientWithoutAttrs:
        pass
    
    mock_client = MockClientWithoutAttrs()
    
    # Call the helper function
    api_key, secret_key, paper = get_api_credentials_from_client(mock_client)
    
    # Verify it fell back to environment variables
    assert api_key == 'fallback_key'
    assert secret_key == 'fallback_secret'
    assert paper == True 