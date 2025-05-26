"""
Tests for the add_asset.py script.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from add_asset import (
    validate_asset_symbol,
    asset_exists,
    add_asset,
    parse_asset_list
)


class TestAssetSymbolValidation:
    """Test asset symbol validation logic."""
    
    def test_valid_asset_symbols(self):
        """Test that valid asset symbols pass validation."""
        valid_symbols = [
            'BTC/USD',
            'ETH/USD',
            'SOL/USD',
            'DOGE/USD',
            'AVAX/USD'
        ]
        
        for symbol in valid_symbols:
            assert validate_asset_symbol(symbol), f"Symbol {symbol} should be valid"
    
    def test_invalid_asset_symbols(self):
        """Test that invalid asset symbols fail validation."""
        invalid_symbols = [
            '',
            'BTC',
            'BTC/',
            '/USD',
            'BTC/USD/EUR',
            'BTC-USD',
            'BTC USD',
            'BTC/US$',
            'BTC/U$D',
            None
        ]
        
        for symbol in invalid_symbols:
            assert not validate_asset_symbol(symbol), f"Symbol {symbol} should be invalid"
    
    def test_case_sensitivity(self):
        """Test that validation works with different cases."""
        assert validate_asset_symbol('btc/usd')
        assert validate_asset_symbol('BTC/USD')
        assert validate_asset_symbol('Btc/Usd')


class TestAssetExistence:
    """Test asset existence checking."""
    
    @patch('add_asset.execute_query')
    def test_asset_exists_true(self, mock_execute_query):
        """Test when asset exists in database."""
        mock_execute_query.return_value = {'id': 1}
        
        result = asset_exists('BTC/USD')
        
        assert result is True
        mock_execute_query.assert_called_once_with(
            "SELECT id FROM dca_assets WHERE asset_symbol = %s",
            ('BTC/USD',),
            fetch_one=True
        )
    
    @patch('add_asset.execute_query')
    def test_asset_exists_false(self, mock_execute_query):
        """Test when asset doesn't exist in database."""
        mock_execute_query.return_value = None
        
        result = asset_exists('NEW/USD')
        
        assert result is False
        mock_execute_query.assert_called_once_with(
            "SELECT id FROM dca_assets WHERE asset_symbol = %s",
            ('NEW/USD',),
            fetch_one=True
        )
    
    @patch('add_asset.execute_query')
    @patch('add_asset.logger')
    def test_asset_exists_database_error(self, mock_logger, mock_execute_query):
        """Test handling of database errors."""
        mock_execute_query.side_effect = Exception("Database error")
        
        result = asset_exists('BTC/USD')
        
        assert result is False
        mock_logger.error.assert_called_once()


class TestAddAsset:
    """Test asset addition functionality."""
    
    @patch('add_asset.asset_exists')
    @patch('add_asset.execute_query')
    @patch('add_asset.logger')
    def test_add_asset_success_enabled(self, mock_logger, mock_execute_query, mock_asset_exists):
        """Test successful addition of enabled asset."""
        mock_asset_exists.return_value = False
        mock_execute_query.return_value = 123  # Mock asset ID
        
        result = add_asset('BTC/USD', enabled=True)
        
        assert result is True
        mock_execute_query.assert_called_once_with(
            """
        INSERT INTO dca_assets (asset_symbol, is_enabled)
        VALUES (%s, %s)
        """,
            ('BTC/USD', 1),
            commit=True
        )
        mock_logger.info.assert_called_with("✅ Successfully added asset BTC/USD (ID: 123) as enabled")
    
    @patch('add_asset.asset_exists')
    @patch('add_asset.execute_query')
    @patch('add_asset.logger')
    def test_add_asset_success_disabled(self, mock_logger, mock_execute_query, mock_asset_exists):
        """Test successful addition of disabled asset."""
        mock_asset_exists.return_value = False
        mock_execute_query.return_value = 124
        
        result = add_asset('ETH/USD', enabled=False)
        
        assert result is True
        mock_execute_query.assert_called_once_with(
            """
        INSERT INTO dca_assets (asset_symbol, is_enabled)
        VALUES (%s, %s)
        """,
            ('ETH/USD', 0),
            commit=True
        )
        mock_logger.info.assert_called_with("✅ Successfully added asset ETH/USD (ID: 124) as disabled")
    
    @patch('add_asset.asset_exists')
    @patch('add_asset.logger')
    def test_add_asset_already_exists(self, mock_logger, mock_asset_exists):
        """Test when asset already exists."""
        mock_asset_exists.return_value = True
        
        result = add_asset('BTC/USD')
        
        assert result is False
        mock_logger.warning.assert_called_with("Asset BTC/USD already exists in database")
    
    @patch('add_asset.asset_exists')
    @patch('add_asset.execute_query')
    @patch('add_asset.logger')
    def test_add_asset_no_id_returned(self, mock_logger, mock_execute_query, mock_asset_exists):
        """Test when database doesn't return an ID."""
        mock_asset_exists.return_value = False
        mock_execute_query.return_value = None
        
        result = add_asset('BTC/USD')
        
        assert result is False
        mock_logger.error.assert_called_with("❌ Failed to add asset BTC/USD - no ID returned")
    
    @patch('add_asset.asset_exists')
    @patch('add_asset.execute_query')
    @patch('add_asset.logger')
    def test_add_asset_database_error(self, mock_logger, mock_execute_query, mock_asset_exists):
        """Test handling of database errors during addition."""
        mock_asset_exists.return_value = False
        mock_execute_query.side_effect = Exception("Database error")
        
        result = add_asset('BTC/USD')
        
        assert result is False
        mock_logger.error.assert_called_with("❌ Error adding asset BTC/USD: Database error")


class TestAssetListParsing:
    """Test asset list parsing functionality."""
    
    def test_parse_single_asset(self):
        """Test parsing a single asset."""
        result = parse_asset_list('BTC/USD')
        assert result == ['BTC/USD']
    
    def test_parse_multiple_assets(self):
        """Test parsing multiple assets."""
        result = parse_asset_list('BTC/USD,ETH/USD,SOL/USD')
        assert result == ['BTC/USD', 'ETH/USD', 'SOL/USD']
    
    def test_parse_with_whitespace(self):
        """Test parsing with extra whitespace."""
        result = parse_asset_list(' BTC/USD , ETH/USD , SOL/USD ')
        assert result == ['BTC/USD', 'ETH/USD', 'SOL/USD']
    
    def test_parse_case_normalization(self):
        """Test that symbols are converted to uppercase."""
        result = parse_asset_list('btc/usd,eth/usd')
        assert result == ['BTC/USD', 'ETH/USD']
    
    def test_parse_empty_string(self):
        """Test parsing empty string."""
        result = parse_asset_list('')
        assert result == []
    
    def test_parse_none(self):
        """Test parsing None."""
        result = parse_asset_list(None)
        assert result == []
    
    @patch('add_asset.logger')
    def test_parse_with_invalid_symbols(self, mock_logger):
        """Test parsing with some invalid symbols."""
        result = parse_asset_list('BTC/USD,INVALID,ETH/USD')
        
        assert result == ['BTC/USD', 'ETH/USD']
        mock_logger.error.assert_called_with("❌ Invalid asset symbol format: INVALID")
    
    def test_parse_all_invalid_symbols(self):
        """Test parsing with all invalid symbols."""
        result = parse_asset_list('INVALID1,INVALID2')
        assert result == [] 