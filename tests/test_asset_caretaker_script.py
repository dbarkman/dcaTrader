"""
Tests for the asset_caretaker.py script.
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from decimal import Decimal

# Add scripts directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / 'scripts'))

from asset_caretaker import (
    get_enabled_assets_without_cycles,
    create_watching_cycle,
    run_maintenance
)


class TestGetEnabledAssetsWithoutCycles:
    """Test finding enabled assets without cycles."""
    
    @patch('asset_caretaker.get_latest_cycle')
    @patch('asset_caretaker.get_all_enabled_assets')
    def test_no_enabled_assets(self, mock_get_all_enabled_assets, mock_get_latest_cycle):
        """Test when there are no enabled assets."""
        mock_get_all_enabled_assets.return_value = []
        
        result = get_enabled_assets_without_cycles()
        
        assert result == []
        mock_get_latest_cycle.assert_not_called()
    
    @patch('asset_caretaker.get_latest_cycle')
    @patch('asset_caretaker.get_all_enabled_assets')
    def test_all_assets_have_cycles(self, mock_get_all_enabled_assets, mock_get_latest_cycle):
        """Test when all enabled assets have cycles."""
        # Mock enabled assets
        mock_asset1 = MagicMock()
        mock_asset1.id = 1
        mock_asset1.asset_symbol = 'BTC/USD'
        
        mock_asset2 = MagicMock()
        mock_asset2.id = 2
        mock_asset2.asset_symbol = 'ETH/USD'
        
        mock_get_all_enabled_assets.return_value = [mock_asset1, mock_asset2]
        
        # Mock that both assets have cycles
        mock_cycle = MagicMock()
        mock_cycle.id = 100
        mock_get_latest_cycle.return_value = mock_cycle
        
        result = get_enabled_assets_without_cycles()
        
        assert result == []
        assert mock_get_latest_cycle.call_count == 2
    
    @patch('asset_caretaker.get_latest_cycle')
    @patch('asset_caretaker.get_all_enabled_assets')
    def test_some_assets_without_cycles(self, mock_get_all_enabled_assets, mock_get_latest_cycle):
        """Test when some assets don't have cycles."""
        # Mock enabled assets
        mock_asset1 = MagicMock()
        mock_asset1.id = 1
        mock_asset1.asset_symbol = 'BTC/USD'
        
        mock_asset2 = MagicMock()
        mock_asset2.id = 2
        mock_asset2.asset_symbol = 'ETH/USD'
        
        mock_asset3 = MagicMock()
        mock_asset3.id = 3
        mock_asset3.asset_symbol = 'SOL/USD'
        
        mock_get_all_enabled_assets.return_value = [mock_asset1, mock_asset2, mock_asset3]
        
        # Mock that only asset1 has a cycle
        def mock_get_cycle(asset_id):
            if asset_id == 1:
                mock_cycle = MagicMock()
                mock_cycle.id = 100
                return mock_cycle
            return None
        
        mock_get_latest_cycle.side_effect = mock_get_cycle
        
        result = get_enabled_assets_without_cycles()
        
        assert len(result) == 2
        assert result[0]['id'] == 2
        assert result[0]['symbol'] == 'ETH/USD'
        assert result[1]['id'] == 3
        assert result[1]['symbol'] == 'SOL/USD'
    
    @patch('asset_caretaker.get_latest_cycle')
    @patch('asset_caretaker.get_all_enabled_assets')
    @patch('asset_caretaker.logger')
    def test_database_error(self, mock_logger, mock_get_all_enabled_assets, mock_get_latest_cycle):
        """Test handling of database errors."""
        mock_get_all_enabled_assets.side_effect = Exception("Database error")
        
        result = get_enabled_assets_without_cycles()
        
        assert result == []
        mock_logger.error.assert_called_with("Error finding assets without cycles: Database error")


class TestCreateWatchingCycle:
    """Test creating watching cycles."""
    
    @patch('asset_caretaker.logger')
    def test_create_watching_cycle_dry_run(self, mock_logger):
        """Test dry run mode."""
        result = create_watching_cycle(1, 'BTC/USD', dry_run=True)
        
        assert result is True
        mock_logger.info.assert_called_with("[DRY RUN] Would create watching cycle for BTC/USD (ID: 1)")
    
    @patch('asset_caretaker.create_cycle')
    @patch('asset_caretaker.logger')
    def test_create_watching_cycle_success(self, mock_logger, mock_create_cycle):
        """Test successful cycle creation."""
        mock_new_cycle = MagicMock()
        mock_new_cycle.id = 123
        mock_create_cycle.return_value = mock_new_cycle
        
        result = create_watching_cycle(1, 'BTC/USD', dry_run=False)
        
        assert result is True
        mock_create_cycle.assert_called_once_with(
            asset_id=1,
            status='watching',
            quantity=Decimal('0'),
            average_purchase_price=Decimal('0'),
            safety_orders=0,
            latest_order_id=None,
            latest_order_created_at=None,
            last_order_fill_price=None,
            completed_at=None
        )
        mock_logger.info.assert_called_with("✅ Created watching cycle 123 for BTC/USD (asset ID: 1)")
    
    @patch('asset_caretaker.create_cycle')
    @patch('asset_caretaker.logger')
    def test_create_watching_cycle_failure(self, mock_logger, mock_create_cycle):
        """Test failed cycle creation."""
        mock_create_cycle.return_value = None
        
        result = create_watching_cycle(1, 'BTC/USD', dry_run=False)
        
        assert result is False
        mock_logger.error.assert_called_with("❌ Failed to create watching cycle for BTC/USD (asset ID: 1)")
    
    @patch('asset_caretaker.create_cycle')
    @patch('asset_caretaker.logger')
    def test_create_watching_cycle_exception(self, mock_logger, mock_create_cycle):
        """Test exception handling during cycle creation."""
        mock_create_cycle.side_effect = Exception("Database error")
        
        result = create_watching_cycle(1, 'BTC/USD', dry_run=False)
        
        assert result is False
        mock_logger.error.assert_called_with("❌ Error creating watching cycle for BTC/USD: Database error")


class TestRunMaintenance:
    """Test the main maintenance function."""
    
    @patch('asset_caretaker.get_enabled_assets_without_cycles')
    @patch('asset_caretaker.logger')
    def test_run_maintenance_no_assets_need_cycles(self, mock_logger, mock_get_assets):
        """Test when no assets need cycles."""
        mock_get_assets.return_value = []
        
        result = run_maintenance()
        
        assert result == {
            'assets_checked': 0,
            'cycles_created': 0,
            'errors': 0
        }
        mock_logger.info.assert_any_call("✅ All enabled assets have cycles - no maintenance needed")
    
    @patch('asset_caretaker.create_watching_cycle')
    @patch('asset_caretaker.get_enabled_assets_without_cycles')
    @patch('asset_caretaker.logger')
    def test_run_maintenance_success(self, mock_logger, mock_get_assets, mock_create_cycle):
        """Test successful maintenance run."""
        # Mock assets without cycles
        mock_get_assets.return_value = [
            {'id': 1, 'symbol': 'BTC/USD'},
            {'id': 2, 'symbol': 'ETH/USD'}
        ]
        
        # Mock successful cycle creation
        mock_create_cycle.return_value = True
        
        result = run_maintenance()
        
        assert result == {
            'assets_checked': 2,
            'cycles_created': 2,
            'errors': 0
        }
        
        # Verify create_watching_cycle was called for each asset
        assert mock_create_cycle.call_count == 2
        mock_create_cycle.assert_any_call(1, 'BTC/USD', False)
        mock_create_cycle.assert_any_call(2, 'ETH/USD', False)
    
    @patch('asset_caretaker.create_watching_cycle')
    @patch('asset_caretaker.get_enabled_assets_without_cycles')
    @patch('asset_caretaker.logger')
    def test_run_maintenance_partial_success(self, mock_logger, mock_get_assets, mock_create_cycle):
        """Test maintenance with some failures."""
        # Mock assets without cycles
        mock_get_assets.return_value = [
            {'id': 1, 'symbol': 'BTC/USD'},
            {'id': 2, 'symbol': 'ETH/USD'},
            {'id': 3, 'symbol': 'SOL/USD'}
        ]
        
        # Mock mixed success/failure
        def mock_create_result(asset_id, symbol, dry_run):
            return asset_id != 2  # Fail for asset_id 2
        
        mock_create_cycle.side_effect = mock_create_result
        
        result = run_maintenance()
        
        assert result == {
            'assets_checked': 3,
            'cycles_created': 2,
            'errors': 1
        }
    
    @patch('asset_caretaker.create_watching_cycle')
    @patch('asset_caretaker.get_enabled_assets_without_cycles')
    @patch('asset_caretaker.logger')
    def test_run_maintenance_dry_run(self, mock_logger, mock_get_assets, mock_create_cycle):
        """Test dry run mode."""
        # Mock assets without cycles
        mock_get_assets.return_value = [
            {'id': 1, 'symbol': 'BTC/USD'}
        ]
        
        # Mock successful cycle creation
        mock_create_cycle.return_value = True
        
        result = run_maintenance(dry_run=True)
        
        assert result == {
            'assets_checked': 1,
            'cycles_created': 1,
            'errors': 0
        }
        
        # Verify dry_run=True was passed
        mock_create_cycle.assert_called_once_with(1, 'BTC/USD', True) 