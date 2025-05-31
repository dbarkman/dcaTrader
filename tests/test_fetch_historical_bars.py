#!/usr/bin/env python3
"""
Tests for fetch_historical_bars.py backtesting infrastructure script.
"""

import pytest
import sys
import os
from unittest.mock import Mock, patch, MagicMock, call
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from argparse import Namespace

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import fetch_historical_bars
from fetch_historical_bars import HistoricalBarsFetcher, parse_date, main
from alpaca.common.exceptions import APIError


class TestUtilityFunctions:
    """Test utility functions."""
    
    @pytest.mark.unit
    def test_parse_date_valid(self):
        """Test parsing valid date strings."""
        result = parse_date("2024-01-15")
        expected = datetime(2024, 1, 15)
        assert result == expected
    
    @pytest.mark.unit
    def test_parse_date_invalid(self):
        """Test parsing invalid date strings."""
        with pytest.raises(Exception):  # argparse.ArgumentTypeError
            parse_date("2024-13-01")
        
        with pytest.raises(Exception):
            parse_date("invalid-date")
        
        with pytest.raises(Exception):
            parse_date("24-01-01")


class TestHistoricalBarsFetcher:
    """Test the HistoricalBarsFetcher class."""
    
    def setup_method(self):
        """Setup for each test method."""
        self.fetcher = HistoricalBarsFetcher()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.execute_query')
    def test_get_asset_mapping_success(self, mock_execute_query):
        """Test successful asset mapping retrieval."""
        # Mock database response
        mock_execute_query.return_value = [
            {'id': 1, 'asset_symbol': 'BTC/USD'},
            {'id': 2, 'asset_symbol': 'ETH/USD'},
            {'id': 3, 'asset_symbol': 'SOL/USD'}
        ]
        
        result = self.fetcher.get_asset_mapping()
        
        expected = {
            'BTC/USD': 1,
            'ETH/USD': 2,
            'SOL/USD': 3
        }
        assert result == expected
        mock_execute_query.assert_called_once()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.execute_query')
    def test_get_asset_mapping_empty(self, mock_execute_query):
        """Test asset mapping with no enabled assets."""
        mock_execute_query.return_value = []
        
        result = self.fetcher.get_asset_mapping()
        
        assert result == {}
        mock_execute_query.assert_called_once()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    def test_get_all_configured_symbols(self, mock_get_mapping):
        """Test getting all configured symbols."""
        mock_get_mapping.return_value = {
            'BTC/USD': 1,
            'ETH/USD': 2,
            'SOL/USD': 3
        }
        
        result = self.fetcher.get_all_configured_symbols()
        
        expected = ['BTC/USD', 'ETH/USD', 'SOL/USD']
        assert sorted(result) == sorted(expected)
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.execute_query')
    def test_get_latest_timestamp_with_data(self, mock_execute_query):
        """Test getting latest timestamp when data exists."""
        test_timestamp = datetime(2024, 5, 27, 12, 0, 0)
        mock_execute_query.return_value = {'latest_timestamp': test_timestamp}
        
        result = self.fetcher.get_latest_timestamp(1)
        
        assert result == test_timestamp
        # Check that execute_query was called with the right parameters, ignoring whitespace differences
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        assert call_args[0][1] == (1,)  # Check parameters
        assert call_args[1]['fetch_one'] == True  # Check keyword args
        # Check that the SQL contains the essential parts
        sql_query = call_args[0][0]
        assert 'SELECT MAX(timestamp) as latest_timestamp' in sql_query
        assert 'FROM historical_1min_bars' in sql_query
        assert 'WHERE asset_id = %s' in sql_query
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.execute_query')
    def test_get_latest_timestamp_no_data(self, mock_execute_query):
        """Test getting latest timestamp when no data exists."""
        mock_execute_query.return_value = {'latest_timestamp': None}
        
        result = self.fetcher.get_latest_timestamp(1)
        
        assert result is None
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.get_db_connection')
    def test_store_bars_success(self, mock_get_connection):
        """Test successful bars storage."""
        # Mock database connection and cursor
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 5
        mock_connection.cursor.return_value = mock_cursor
        mock_get_connection.return_value = mock_connection
        
        # Create mock bars
        mock_bars = []
        for i in range(3):
            bar = Mock()
            bar.timestamp = datetime(2024, 5, 27, 12, i)
            bar.open = Decimal('50000.00')
            bar.high = Decimal('50100.00')
            bar.low = Decimal('49900.00')
            bar.close = Decimal('50050.00')
            bar.volume = Decimal('10.5')
            bar.trade_count = 100
            bar.vwap = Decimal('50025.00')
            mock_bars.append(bar)
        
        result = self.fetcher.store_bars(1, mock_bars)
        
        assert result == 3
        mock_cursor.executemany.assert_called_once()
        mock_connection.commit.assert_called_once()
    
    @pytest.mark.unit
    def test_store_bars_empty_list(self):
        """Test storing empty bars list."""
        result = self.fetcher.store_bars(1, [])
        assert result == 0
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.time.sleep')
    @patch('fetch_historical_bars.CryptoBarsRequest')
    def test_fetch_bars_for_period_success(self, mock_request_class, mock_sleep):
        """Test successful bars fetching for a period."""
        # Mock the request
        mock_request = Mock()
        mock_request_class.return_value = mock_request
        
        # Mock the client response
        mock_bars = [Mock(), Mock()]
        mock_response = Mock()
        mock_response.data = {'BTC/USD': mock_bars}
        mock_response.next_page_token = None
        
        self.fetcher.client = Mock()
        self.fetcher.client.get_crypto_bars.return_value = mock_response
        
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_bars_for_period('BTC/USD', start_date, end_date)
        
        assert result == mock_bars
        self.fetcher.client.get_crypto_bars.assert_called_once()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.time.sleep')
    @patch('fetch_historical_bars.CryptoBarsRequest')
    def test_fetch_bars_for_period_with_pagination(self, mock_request_class, mock_sleep):
        """Test bars fetching with pagination."""
        mock_request = Mock()
        mock_request_class.return_value = mock_request
        
        # First page
        mock_bars_page1 = [Mock(), Mock()]
        mock_response_page1 = Mock()
        mock_response_page1.data = {'BTC/USD': mock_bars_page1}
        mock_response_page1.next_page_token = 'token123'
        
        # Second page  
        mock_bars_page2 = [Mock()]
        mock_response_page2 = Mock()
        mock_response_page2.data = {'BTC/USD': mock_bars_page2}
        mock_response_page2.next_page_token = None
        
        self.fetcher.client = Mock()
        self.fetcher.client.get_crypto_bars.side_effect = [mock_response_page1, mock_response_page2]
        
        # Set up bar timestamps for pagination logic
        mock_bars_page1[-1].timestamp = datetime(2024, 5, 27, 12, 30)
        
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_bars_for_period('BTC/USD', start_date, end_date)
        
        expected_bars = mock_bars_page1 + mock_bars_page2
        assert result == expected_bars
        assert self.fetcher.client.get_crypto_bars.call_count == 2
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.time.sleep')
    @patch('fetch_historical_bars.CryptoBarsRequest')
    def test_fetch_bars_api_error_rate_limit(self, mock_request_class, mock_sleep):
        """Test handling API rate limit errors."""
        mock_request = Mock()
        mock_request_class.return_value = mock_request
        
        # First call raises rate limit error, second succeeds
        rate_limit_error = APIError("rate limit exceeded")
        
        mock_bars = [Mock()]
        mock_response = Mock()
        mock_response.data = {'BTC/USD': mock_bars}
        mock_response.next_page_token = None
        
        self.fetcher.client = Mock()
        self.fetcher.client.get_crypto_bars.side_effect = [rate_limit_error, mock_response]
        
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_bars_for_period('BTC/USD', start_date, end_date)
        
        assert result == mock_bars
        assert self.fetcher.client.get_crypto_bars.call_count == 2
        # Should sleep for 60 seconds on rate limit
        mock_sleep.assert_called_with(60)
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.fetch_bars_for_period')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.store_bars')
    def test_fetch_bulk_success(self, mock_store_bars, mock_fetch_bars, mock_get_mapping):
        """Test successful bulk fetch operation."""
        # Setup mocks
        mock_get_mapping.return_value = {'BTC/USD': 1, 'ETH/USD': 2}
        mock_fetch_bars.return_value = [Mock(), Mock(), Mock()]  # 3 bars
        mock_store_bars.return_value = 3
        
        symbols = ['BTC/USD', 'ETH/USD']
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_bulk(symbols, start_date, end_date)
        
        assert result is True
        assert mock_fetch_bars.call_count == 2
        assert mock_store_bars.call_count == 2
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    def test_fetch_bulk_unknown_symbol(self, mock_get_mapping):
        """Test bulk fetch with unknown symbol."""
        mock_get_mapping.return_value = {'BTC/USD': 1}
        
        symbols = ['BTC/USD', 'UNKNOWN/USD']
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_bulk(symbols, start_date, end_date)
        
        assert result is False  # Should fail due to unknown symbol
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_latest_timestamp')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.fetch_bars_for_period')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.store_bars')
    def test_fetch_incremental_with_existing_data(self, mock_store_bars, mock_fetch_bars, 
                                                 mock_get_latest, mock_get_mapping):
        """Test incremental fetch with existing data."""
        # Setup mocks
        mock_get_mapping.return_value = {'BTC/USD': 1}
        mock_get_latest.return_value = datetime(2024, 5, 27, 12, 0)
        mock_fetch_bars.return_value = [Mock(), Mock()]
        mock_store_bars.return_value = 2
        
        symbols = ['BTC/USD']
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_incremental(symbols, end_date)
        
        assert result is True
        # Should fetch from latest + 1 minute
        expected_start = datetime(2024, 5, 27, 12, 1)
        mock_fetch_bars.assert_called_once_with('BTC/USD', expected_start, end_date)
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_latest_timestamp')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.fetch_bars_for_period')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.store_bars')
    def test_fetch_incremental_no_existing_data(self, mock_store_bars, mock_fetch_bars, 
                                               mock_get_latest, mock_get_mapping):
        """Test incremental fetch with no existing data."""
        # Setup mocks
        mock_get_mapping.return_value = {'BTC/USD': 1}
        mock_get_latest.return_value = None  # No existing data
        mock_fetch_bars.return_value = [Mock(), Mock()]
        mock_store_bars.return_value = 2
        
        symbols = ['BTC/USD']
        end_date = datetime(2024, 5, 27, 13, 0)
        
        result = self.fetcher.fetch_incremental(symbols, end_date)
        
        assert result is True
        # Should fetch from 30 days ago
        expected_start = end_date - timedelta(days=30)
        mock_fetch_bars.assert_called_once_with('BTC/USD', expected_start, end_date)
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_latest_timestamp')
    def test_fetch_incremental_up_to_date(self, mock_get_latest, mock_get_mapping):
        """Test incremental fetch when data is already up to date."""
        # Setup mocks
        mock_get_mapping.return_value = {'BTC/USD': 1}
        end_date = datetime(2024, 5, 27, 13, 0)
        # Latest timestamp is same as end date
        mock_get_latest.return_value = end_date
        
        symbols = ['BTC/USD']
        
        result = self.fetcher.fetch_incremental(symbols, end_date)
        
        assert result is True


class TestMainFunction:
    """Test the main function and argument parsing."""
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--symbols', 'BTC/USD', 
                        '--start-date', '2024-01-01', '--end-date', '2024-01-02', '--mode', 'bulk'])
    def test_main_bulk_mode_success(self, mock_fetcher_class):
        """Test main function in bulk mode."""
        # Setup mock fetcher
        mock_fetcher = Mock()
        mock_fetcher.fetch_bulk.return_value = True
        mock_fetcher_class.return_value = mock_fetcher
        
        result = main()
        
        assert result == 0
        mock_fetcher.fetch_bulk.assert_called_once()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--all-configured', '--mode', 'incremental'])
    def test_main_incremental_mode_success(self, mock_fetcher_class):
        """Test main function in incremental mode."""
        # Setup mock fetcher
        mock_fetcher = Mock()
        mock_fetcher.get_all_configured_symbols.return_value = ['BTC/USD', 'ETH/USD']
        mock_fetcher.fetch_incremental.return_value = True
        mock_fetcher_class.return_value = mock_fetcher
        
        result = main()
        
        assert result == 0
        mock_fetcher.fetch_incremental.assert_called_once()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--symbols', 'BTC/USD', '--mode', 'bulk'])
    def test_main_bulk_mode_missing_start_date(self, mock_fetcher_class):
        """Test main function bulk mode without start date."""
        # This should cause an argument parsing error
        with pytest.raises(SystemExit):
            main()
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--symbols', 'BTC/USD', 
                        '--start-date', '2024-01-01', '--end-date', '2024-01-02', '--mode', 'bulk'])
    def test_main_fetch_failure(self, mock_fetcher_class):
        """Test main function when fetch operation fails."""
        # Setup mock fetcher to fail
        mock_fetcher = Mock()
        mock_fetcher.fetch_bulk.return_value = False
        mock_fetcher_class.return_value = mock_fetcher
        
        result = main()
        
        assert result == 1  # Should return failure exit code
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--symbols', 'BTC/USD', 
                        '--start-date', '2024-01-01', '--end-date', '2024-01-02', '--mode', 'bulk'])
    def test_main_exception_handling(self, mock_fetcher_class):
        """Test main function exception handling."""
        # Setup mock fetcher to raise exception
        mock_fetcher_class.side_effect = Exception("Test error")
        
        result = main()
        
        assert result == 1  # Should return failure exit code
    
    @pytest.mark.unit
    @patch('fetch_historical_bars.HistoricalBarsFetcher')
    @patch('sys.argv', ['fetch_historical_bars.py', '--all-configured', '--mode', 'incremental'])
    def test_main_no_symbols_to_process(self, mock_fetcher_class):
        """Test main function when no symbols are available to process."""
        # Setup mock fetcher with no symbols
        mock_fetcher = Mock()
        mock_fetcher.get_all_configured_symbols.return_value = []
        mock_fetcher_class.return_value = mock_fetcher
        
        result = main()
        
        assert result == 1  # Should return failure exit code


class TestIntegration:
    """Integration tests for the historical bars fetcher."""
    
    @pytest.mark.integration
    @patch('fetch_historical_bars.execute_query')
    @patch('fetch_historical_bars.get_db_connection')
    def test_database_integration(self, mock_get_connection, mock_execute_query):
        """Test integration with database operations."""
        # Mock database responses
        mock_execute_query.return_value = [
            {'id': 1, 'asset_symbol': 'BTC/USD'}
        ]
        
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.rowcount = 1
        mock_connection.cursor.return_value = mock_cursor
        mock_get_connection.return_value = mock_connection
        
        fetcher = HistoricalBarsFetcher()
        
        # Test asset mapping
        mapping = fetcher.get_asset_mapping()
        assert mapping == {'BTC/USD': 1}
        
        # Test storing bars
        mock_bar = Mock()
        mock_bar.timestamp = datetime(2024, 5, 27, 12, 0)
        mock_bar.open = Decimal('50000.00')
        mock_bar.high = Decimal('50100.00')
        mock_bar.low = Decimal('49900.00')
        mock_bar.close = Decimal('50050.00')
        mock_bar.volume = Decimal('10.5')
        mock_bar.trade_count = 100
        mock_bar.vwap = Decimal('50025.00')
        
        result = fetcher.store_bars(1, [mock_bar])
        assert result == 1
    
    @pytest.mark.integration
    def test_alpaca_client_initialization(self):
        """Test that Alpaca client is properly initialized."""
        fetcher = HistoricalBarsFetcher()
        
        # Should have a client instance
        assert fetcher.client is not None
        assert hasattr(fetcher.client, 'get_crypto_bars')
    
    @pytest.mark.integration
    @patch('fetch_historical_bars.HistoricalBarsFetcher.get_asset_mapping')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.fetch_bars_for_period')
    @patch('fetch_historical_bars.HistoricalBarsFetcher.store_bars')
    def test_full_workflow_simulation(self, mock_store_bars, mock_fetch_bars, mock_get_mapping):
        """Test complete workflow simulation."""
        # Setup realistic mocks
        mock_get_mapping.return_value = {
            'BTC/USD': 1,
            'ETH/USD': 2
        }
        
        # Create realistic mock bars
        mock_bars = []
        for i in range(5):
            bar = Mock()
            bar.timestamp = datetime(2024, 5, 27, 12, i)
            bar.open = Decimal(f'5000{i}.00')
            bar.high = Decimal(f'5010{i}.00')
            bar.low = Decimal(f'4990{i}.00')
            bar.close = Decimal(f'5005{i}.00')
            bar.volume = Decimal('10.5')
            bar.trade_count = 100
            bar.vwap = Decimal(f'5000{i}.00')
            mock_bars.append(bar)
        
        mock_fetch_bars.return_value = mock_bars
        mock_store_bars.return_value = len(mock_bars)
        
        fetcher = HistoricalBarsFetcher()
        
        # Test bulk fetch workflow
        symbols = ['BTC/USD', 'ETH/USD']
        start_date = datetime(2024, 5, 27, 12, 0)
        end_date = datetime(2024, 5, 27, 17, 0)
        
        result = fetcher.fetch_bulk(symbols, start_date, end_date)
        
        assert result is True
        # Should have called fetch_bars and store_bars for each symbol
        assert mock_fetch_bars.call_count == 2
        assert mock_store_bars.call_count == 2 