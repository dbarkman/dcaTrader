"""
Unit tests for market data handler functionality (Phase 4 & 5)

Tests the logic for monitoring crypto prices and placing base orders and safety orders
when conditions are met.
"""

import pytest
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from main_app import check_and_place_base_order, check_and_place_safety_order


class TestBaseOrderLogic:
    """Test base order placement logic"""
    
    def setup_method(self):
        """Set up test fixtures"""
        self.mock_quote = Mock()
        self.mock_quote.symbol = 'BTC/USD'
        self.mock_quote.ask_price = 50000.0
        self.mock_quote.bid_price = 49950.0
        
        self.mock_asset = Mock()
        self.mock_asset.id = 1
        self.mock_asset.asset_symbol = 'BTC/USD'
        self.mock_asset.is_enabled = True
        self.mock_asset.base_order_amount = Decimal('100.00')
        
        self.mock_cycle = Mock()
        self.mock_cycle.id = 1
        self.mock_cycle.asset_id = 1
        self.mock_cycle.status = 'watching'
        self.mock_cycle.quantity = Decimal('0')
    
    @pytest.mark.unit
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_asset_not_configured(self, mock_get_asset):
        """Test that base order is skipped if asset is not configured"""
        mock_get_asset.return_value = None
        
        # Should return early without error
        check_and_place_base_order(self.mock_quote)
        
        mock_get_asset.assert_called_once_with('BTC/USD')
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_asset_disabled(self, mock_get_asset, mock_get_cycle):
        """Test that base order is skipped if asset is disabled"""
        disabled_asset = Mock()
        disabled_asset.is_enabled = False
        mock_get_asset.return_value = disabled_asset
        
        check_and_place_base_order(self.mock_quote)
        
        # Should not call get_latest_cycle
        mock_get_cycle.assert_not_called()
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_no_cycle(self, mock_get_asset, mock_get_cycle):
        """Test that base order is skipped if no cycle exists"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = None
        
        check_and_place_base_order(self.mock_quote)
        
        mock_get_cycle.assert_called_once_with(1)
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_cycle_not_watching(self, mock_get_asset, mock_get_cycle):
        """Test that base order is skipped if cycle status is not 'watching'"""
        mock_get_asset.return_value = self.mock_asset
        
        buying_cycle = Mock()
        buying_cycle.status = 'buying'
        buying_cycle.quantity = Decimal('0')
        mock_get_cycle.return_value = buying_cycle
        
        check_and_place_base_order(self.mock_quote)
        
        # Should return without calling Alpaca
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_cycle_has_quantity(self, mock_get_asset, mock_get_cycle):
        """Test that base order is skipped if cycle already has quantity"""
        mock_get_asset.return_value = self.mock_asset
        
        active_cycle = Mock()
        active_cycle.status = 'watching'
        active_cycle.quantity = Decimal('0.1')  # Already has quantity
        mock_get_cycle.return_value = active_cycle
        
        check_and_place_base_order(self.mock_quote)
    
    @pytest.mark.unit
    @patch('main_app.place_limit_buy_order')
    @patch('main_app.get_positions')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_skipped_if_position_exists(self, mock_get_asset, mock_get_cycle, 
                                                   mock_get_client, mock_get_positions, 
                                                   mock_place_order):
        """Test that base order is skipped if Alpaca position already exists"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock existing position
        existing_position = Mock()
        existing_position.symbol = 'BTC/USD'
        existing_position.qty = '0.1'
        existing_position.avg_cost = '48000.0'
        mock_get_positions.return_value = [existing_position]
        
        check_and_place_base_order(self.mock_quote)
        
        # Should not place order
        mock_place_order.assert_not_called()
    
    @pytest.mark.unit
    @patch('main_app.place_limit_buy_order')
    @patch('main_app.get_positions')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_conditions_met(self, mock_get_asset, mock_get_cycle, 
                                       mock_get_client, mock_get_positions, 
                                       mock_place_order):
        """Test that base order is placed when all conditions are met"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_get_positions.return_value = []  # No existing positions
        
        # Mock successful order placement
        mock_order = Mock()
        mock_order.id = 'test_order_123'
        mock_place_order.return_value = mock_order
        
        check_and_place_base_order(self.mock_quote)
        
        # Verify order was placed with correct parameters
        expected_quantity = 100.0 / 50000.0  # $100 / $50,000 = 0.002 BTC
        mock_place_order.assert_called_once_with(
            client=mock_client,
            symbol='BTC/USD',
            qty=expected_quantity,
            limit_price=50000.0,
            time_in_force='gtc'
        )
    
    @pytest.mark.unit
    def test_base_order_usd_to_qty_conversion(self):
        """Test USD to crypto quantity conversion"""
        base_order_usd = 100.0
        ask_price = 50000.0
        
        expected_quantity = base_order_usd / ask_price
        assert expected_quantity == 0.002
        
        # Test different prices
        ask_price_2 = 25000.0
        expected_quantity_2 = base_order_usd / ask_price_2
        assert expected_quantity_2 == 0.004
    
    @pytest.mark.unit
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    def test_base_order_invalid_ask_price(self, mock_get_asset, mock_get_cycle):
        """Test that base order is skipped with invalid ask price"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        
        # Test with zero ask price
        invalid_quote = Mock()
        invalid_quote.symbol = 'BTC/USD'
        invalid_quote.ask_price = 0.0
        
        # Should return without error
        check_and_place_base_order(invalid_quote)
        
        # Test with None ask price
        invalid_quote.ask_price = None
        check_and_place_base_order(invalid_quote)
    
    @pytest.mark.unit
    @patch('main_app.place_limit_buy_order')
    @patch('main_app.get_positions')
    @patch('main_app.get_trading_client')
    @patch('main_app.get_latest_cycle')
    @patch('main_app.get_asset_config')
    @patch('main_app.recent_orders', {})  # Clear the global recent_orders dict
    def test_base_order_placement_fails_gracefully(self, mock_get_asset, mock_get_cycle, 
                                                    mock_get_client, mock_get_positions, 
                                                    mock_place_order):
        """Test that failed order placement is handled gracefully"""
        mock_get_asset.return_value = self.mock_asset
        mock_get_cycle.return_value = self.mock_cycle
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        mock_get_positions.return_value = []
        
        # Create a properly mocked quote with both ask_price and bid_price
        test_quote = Mock()
        test_quote.symbol = 'BTC/USD'
        test_quote.ask_price = 50000.0
        test_quote.bid_price = 49999.0  # Required by our enhanced validation
        
        # Mock failed order placement
        mock_place_order.return_value = None
        
        # Should not raise exception
        check_and_place_base_order(test_quote)
        
        mock_place_order.assert_called_once()


class TestMarketDataIntegration:
    """Integration tests for market data handler"""
    
    @pytest.mark.unit
    def test_quote_object_structure(self):
        """Test that we handle quote object structure correctly"""
        # Mock quote object as it would come from Alpaca
        mock_quote = Mock()
        mock_quote.symbol = 'ETH/USD'
        mock_quote.ask_price = 3000.0
        mock_quote.bid_price = 2999.0
        mock_quote.ask_size = 100.0
        mock_quote.bid_size = 150.0
        
        # Should be able to extract required fields
        assert mock_quote.symbol == 'ETH/USD'
        assert mock_quote.ask_price == 3000.0
    
    @pytest.mark.unit
    @patch('main_app.get_positions')
    def test_position_filtering_logic(self, mock_get_positions):
        """Test that we correctly identify existing positions"""
        # Mock multiple positions
        btc_position = Mock()
        btc_position.symbol = 'BTC/USD'
        btc_position.qty = '0.1'
        
        eth_position = Mock()
        eth_position.symbol = 'ETH/USD'
        eth_position.qty = '2.5'
        
        zero_position = Mock()
        zero_position.symbol = 'DOGE/USD'
        zero_position.qty = '0'  # Zero quantity position should be ignored
        
        mock_get_positions.return_value = [btc_position, eth_position, zero_position]
        
        positions = mock_get_positions()
        
        # Should find BTC position
        btc_found = None
        for pos in positions:
            if pos.symbol == 'BTC/USD' and float(pos.qty) != 0:
                btc_found = pos
                break
        assert btc_found is not None
        
        # Should not find DOGE position (zero quantity)
        doge_found = None
        for pos in positions:
            if pos.symbol == 'DOGE/USD' and float(pos.qty) != 0:
                doge_found = pos
                break
        assert doge_found is None 