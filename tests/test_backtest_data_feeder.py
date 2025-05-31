"""
Unit tests for the HistoricalDataFeeder class from the Phase 3 backtesting engine.

Tests the data fetching and bar generation functionality.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from decimal import Decimal
from datetime import datetime, timezone
import sys
import os

# Add src and scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from run_backtest import HistoricalDataFeeder


class TestHistoricalDataFeeder:
    """Test the HistoricalDataFeeder class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.asset_id = 1
        self.start_date = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.end_date = datetime(2024, 1, 2, tzinfo=timezone.utc)
        self.feeder = HistoricalDataFeeder(self.asset_id, self.start_date, self.end_date)
        
        # Mock database rows
        self.mock_rows = [
            {
                'timestamp': datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                'open_price': 45000.00,
                'high_price': 45500.00,
                'low_price': 44800.00,
                'close_price': 45200.00,
                'volume': 123.45
            },
            {
                'timestamp': datetime(2024, 1, 1, 12, 1, tzinfo=timezone.utc),
                'open_price': 45200.00,
                'high_price': 45600.00,
                'low_price': 45000.00,
                'close_price': 45400.00,
                'volume': 234.56
            },
            {
                'timestamp': datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc),
                'open_price': 45400.00,
                'high_price': 45800.00,
                'low_price': 45300.00,
                'close_price': 45700.00,
                'volume': 345.67
            }
        ]
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_fetch_data_constructs_correct_query(self, mock_execute_query):
        """Test that fetch_data constructs the correct SQL query."""
        mock_execute_query.return_value = self.mock_rows
        
        result = self.feeder.fetch_data()
        
        # Verify execute_query was called with correct parameters
        expected_query = """
        SELECT timestamp, open_price, high_price, low_price, close_price, volume
        FROM historical_1min_bars
        WHERE asset_id = %s 
        AND timestamp >= %s 
        AND timestamp <= %s
        ORDER BY timestamp ASC
        """
        
        mock_execute_query.assert_called_once()
        call_args = mock_execute_query.call_args
        
        # Check the query (normalize whitespace)
        actual_query = ' '.join(call_args[0][0].split())
        expected_query_normalized = ' '.join(expected_query.split())
        assert actual_query == expected_query_normalized
        
        # Check parameters
        assert call_args[0][1] == (self.asset_id, self.start_date, self.end_date)
        assert call_args[1]['fetch_all'] == True
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_fetch_data_processes_results_correctly(self, mock_execute_query):
        """Test that fetch_data correctly processes database results."""
        mock_execute_query.return_value = self.mock_rows
        
        result = self.feeder.fetch_data()
        
        # Verify result structure and data types
        assert len(result) == 3
        
        bar = result[0]
        assert bar['timestamp'] == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert bar['open'] == Decimal('45000.00')
        assert bar['high'] == Decimal('45500.00')
        assert bar['low'] == Decimal('44800.00')
        assert bar['close'] == Decimal('45200.00')
        assert bar['volume'] == Decimal('123.45')
        
        # Verify all values are Decimal (except timestamp)
        assert isinstance(bar['open'], Decimal)
        assert isinstance(bar['high'], Decimal)
        assert isinstance(bar['low'], Decimal)
        assert isinstance(bar['close'], Decimal)
        assert isinstance(bar['volume'], Decimal)
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_fetch_data_caches_results(self, mock_execute_query):
        """Test that fetch_data caches results and doesn't query twice."""
        mock_execute_query.return_value = self.mock_rows
        
        # Call fetch_data twice
        result1 = self.feeder.fetch_data()
        result2 = self.feeder.fetch_data()
        
        # Verify execute_query was only called once
        assert mock_execute_query.call_count == 1
        
        # Verify results are identical
        assert result1 == result2
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_fetch_data_handles_empty_results(self, mock_execute_query):
        """Test that fetch_data handles empty query results."""
        mock_execute_query.return_value = []
        
        result = self.feeder.fetch_data()
        
        assert result == []
        assert len(result) == 0
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_fetch_data_handles_database_error(self, mock_execute_query):
        """Test that fetch_data properly handles database errors."""
        mock_execute_query.side_effect = Exception("Database connection error")
        
        with pytest.raises(Exception) as exc_info:
            self.feeder.fetch_data()
        
        assert "Database connection error" in str(exc_info.value)
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_get_bars_yields_correct_data(self, mock_execute_query):
        """Test that get_bars yields bars correctly."""
        mock_execute_query.return_value = self.mock_rows
        
        bars = list(self.feeder.get_bars())
        
        assert len(bars) == 3
        
        # Verify first bar
        bar = bars[0]
        assert bar['timestamp'] == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        assert bar['close'] == Decimal('45200.00')
        
        # Verify last bar
        bar = bars[2]
        assert bar['timestamp'] == datetime(2024, 1, 1, 12, 2, tzinfo=timezone.utc)
        assert bar['close'] == Decimal('45700.00')
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_get_bars_is_generator(self, mock_execute_query):
        """Test that get_bars returns a generator."""
        mock_execute_query.return_value = self.mock_rows
        
        bars_generator = self.feeder.get_bars()
        
        # Verify it's a generator
        assert hasattr(bars_generator, '__iter__')
        assert hasattr(bars_generator, '__next__')
        
        # Verify we can iterate
        first_bar = next(bars_generator)
        assert first_bar['close'] == Decimal('45200.00')
        
        second_bar = next(bars_generator)
        assert second_bar['close'] == Decimal('45400.00')
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_get_bar_count_returns_correct_count(self, mock_execute_query):
        """Test that get_bar_count returns the correct number of bars."""
        mock_execute_query.return_value = self.mock_rows
        
        count = self.feeder.get_bar_count()
        
        assert count == 3
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_get_bar_count_with_empty_data(self, mock_execute_query):
        """Test that get_bar_count returns 0 for empty data."""
        mock_execute_query.return_value = []
        
        count = self.feeder.get_bar_count()
        
        assert count == 0
    
    @pytest.mark.unit
    def test_feeder_initialization(self):
        """Test that HistoricalDataFeeder initializes correctly."""
        feeder = HistoricalDataFeeder(123, self.start_date, self.end_date)
        
        assert feeder.asset_id == 123
        assert feeder.start_date == self.start_date
        assert feeder.end_date == self.end_date
        assert feeder._data_cache is None
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_multiple_calls_use_cache(self, mock_execute_query):
        """Test that multiple method calls use the cached data."""
        mock_execute_query.return_value = self.mock_rows
        
        # Call different methods
        bars_list = list(self.feeder.get_bars())
        count = self.feeder.get_bar_count()
        data = self.feeder.fetch_data()
        
        # Verify execute_query was only called once
        assert mock_execute_query.call_count == 1
        
        # Verify all results are consistent
        assert len(bars_list) == count == len(data) == 3
    
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_date_range_handling(self, mock_execute_query):
        """Test that different date ranges work correctly."""
        # Test with different date range
        start = datetime(2024, 6, 15, tzinfo=timezone.utc)
        end = datetime(2024, 6, 16, tzinfo=timezone.utc)
        
        feeder = HistoricalDataFeeder(999, start, end)
        mock_execute_query.return_value = []
        
        feeder.fetch_data()
        
        # Verify the correct dates were passed to the query
        call_args = mock_execute_query.call_args
        assert call_args[0][1] == (999, start, end)
        
    @pytest.mark.unit
    @patch('run_backtest.execute_query')
    def test_decimal_precision_preserved(self, mock_execute_query):
        """Test that decimal precision is preserved in price conversions."""
        # Mock data with high precision prices
        high_precision_rows = [
            {
                'timestamp': datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                'open_price': 45000.123456789,
                'high_price': 45500.987654321,
                'low_price': 44800.555555555,
                'close_price': 45200.123123123,
                'volume': 123.456789012
            }
        ]
        
        mock_execute_query.return_value = high_precision_rows
        
        result = self.feeder.fetch_data()
        bar = result[0]
        
        # Verify precision is preserved
        assert str(bar['open']) == '45000.123456789'
        assert str(bar['high']) == '45500.987654321'
        assert str(bar['low']) == '44800.555555555'
        assert str(bar['close']) == '45200.123123123'
        assert str(bar['volume']) == '123.456789012' 