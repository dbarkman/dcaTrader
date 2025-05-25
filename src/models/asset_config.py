"""
Asset configuration model for the DCA trading bot.
Handles the dca_assets table data and operations.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import List, Optional
from mysql.connector import Error

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils.db_utils import execute_query

logger = logging.getLogger(__name__)


@dataclass
class DcaAsset:
    """
    Represents a DCA asset configuration from the dca_assets table.
    """
    id: int
    asset_symbol: str
    is_enabled: bool
    base_order_amount: Decimal
    safety_order_amount: Decimal
    max_safety_orders: int
    safety_order_deviation: Decimal
    take_profit_percent: Decimal
    cooldown_period: int
    buy_order_price_deviation_percent: Decimal
    last_sell_price: Optional[Decimal]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> 'DcaAsset':
        """
        Create a DcaAsset instance from a database row dictionary.
        
        Args:
            data: Dictionary containing database row data
            
        Returns:
            DcaAsset: New instance with data from the dictionary
        """
        return cls(
            id=data['id'],
            asset_symbol=data['asset_symbol'],
            is_enabled=bool(data['is_enabled']),
            base_order_amount=Decimal(str(data['base_order_amount'])),
            safety_order_amount=Decimal(str(data['safety_order_amount'])),
            max_safety_orders=data['max_safety_orders'],
            safety_order_deviation=Decimal(str(data['safety_order_deviation'])),
            take_profit_percent=Decimal(str(data['take_profit_percent'])),
            cooldown_period=data['cooldown_period'],
            buy_order_price_deviation_percent=Decimal(str(data['buy_order_price_deviation_percent'])),
            last_sell_price=Decimal(str(data['last_sell_price'])) if data['last_sell_price'] is not None else None,
            created_at=data['created_at'],
            updated_at=data['updated_at']
        )


def get_asset_config(asset_symbol: str) -> Optional[DcaAsset]:
    """
    Fetches an asset's configuration by its symbol.
    
    Args:
        asset_symbol: The asset symbol to fetch (e.g., 'BTC/USD')
        
    Returns:
        DcaAsset: Asset configuration if found, None otherwise
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        SELECT id, asset_symbol, is_enabled, base_order_amount, safety_order_amount,
               max_safety_orders, safety_order_deviation, take_profit_percent,
               cooldown_period, buy_order_price_deviation_percent, last_sell_price,
               created_at, updated_at
        FROM dca_assets 
        WHERE asset_symbol = %s
        """
        
        result = execute_query(query, (asset_symbol,), fetch_one=True)
        
        if result:
            logger.debug(f"Found asset configuration for {asset_symbol}")
            return DcaAsset.from_dict(result)
        else:
            logger.debug(f"No asset configuration found for {asset_symbol}")
            return None
            
    except Error as e:
        logger.error(f"Error fetching asset config for {asset_symbol}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching asset config for {asset_symbol}: {e}")
        raise


def get_asset_config_by_id(asset_id: int) -> Optional[DcaAsset]:
    """
    Fetches an asset's configuration by its ID.
    
    Args:
        asset_id: The asset ID to fetch
        
    Returns:
        DcaAsset: Asset configuration if found, None otherwise
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        SELECT id, asset_symbol, is_enabled, base_order_amount, safety_order_amount,
               max_safety_orders, safety_order_deviation, take_profit_percent,
               cooldown_period, buy_order_price_deviation_percent, last_sell_price,
               created_at, updated_at
        FROM dca_assets 
        WHERE id = %s
        """
        
        result = execute_query(query, (asset_id,), fetch_one=True)
        
        if result:
            logger.debug(f"Found asset configuration for ID {asset_id}")
            return DcaAsset.from_dict(result)
        else:
            logger.debug(f"No asset configuration found for ID {asset_id}")
            return None
            
    except Error as e:
        logger.error(f"Error fetching asset config for ID {asset_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching asset config for ID {asset_id}: {e}")
        raise


def get_all_enabled_assets() -> List[DcaAsset]:
    """
    Fetches all enabled assets from the database.
    
    Returns:
        List[DcaAsset]: List of enabled asset configurations
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        SELECT id, asset_symbol, is_enabled, base_order_amount, safety_order_amount,
               max_safety_orders, safety_order_deviation, take_profit_percent,
               cooldown_period, buy_order_price_deviation_percent, last_sell_price,
               created_at, updated_at
        FROM dca_assets 
        WHERE is_enabled = TRUE
        ORDER BY asset_symbol
        """
        
        results = execute_query(query, fetch_all=True)
        
        if results:
            assets = [DcaAsset.from_dict(row) for row in results]
            logger.debug(f"Found {len(assets)} enabled assets")
            return assets
        else:
            logger.debug("No enabled assets found")
            return []
            
    except Error as e:
        logger.error(f"Error fetching enabled assets: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching enabled assets: {e}")
        raise


def update_asset_config(asset_id: int, updates: dict) -> bool:
    """
    Updates specified fields of an asset configuration.
    
    Args:
        asset_id: ID of the asset to update
        updates: Dictionary of column_name: new_value pairs
        
    Returns:
        bool: True if update was successful
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    if not updates:
        logger.warning("No updates provided for asset config update")
        return False
        
    try:
        # Build the SET clause dynamically
        set_clauses = []
        params = []
        
        for column, value in updates.items():
            set_clauses.append(f"{column} = %s")
            params.append(value)
        
        # Add the asset_id for the WHERE clause
        params.append(asset_id)
        
        query = f"""
        UPDATE dca_assets 
        SET {', '.join(set_clauses)}
        WHERE id = %s
        """
        
        rows_affected = execute_query(query, params, commit=True)
        
        if rows_affected and rows_affected > 0:
            logger.info(f"Updated asset {asset_id} with {len(updates)} fields")
            return True
        else:
            logger.warning(f"No rows affected when updating asset {asset_id}")
            return False
            
    except Error as e:
        logger.error(f"Error updating asset {asset_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating asset {asset_id}: {e}")
        raise 