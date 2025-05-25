"""
Cycle data model for the DCA trading bot.
Handles the dca_cycles table data and operations.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional
from mysql.connector import Error

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from utils.db_utils import execute_query

logger = logging.getLogger(__name__)


@dataclass
class DcaCycle:
    """
    Represents a DCA trading cycle from the dca_cycles table.
    """
    id: int
    asset_id: int
    status: str
    quantity: Decimal
    average_purchase_price: Decimal
    safety_orders: int
    latest_order_id: Optional[str]
    latest_order_created_at: Optional[datetime]
    last_order_fill_price: Optional[Decimal]
    completed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_dict(cls, data: dict) -> 'DcaCycle':
        """
        Create a DcaCycle instance from a database row dictionary.
        
        Args:
            data: Dictionary containing database row data
            
        Returns:
            DcaCycle: New instance with data from the dictionary
        """
        return cls(
            id=data['id'],
            asset_id=data['asset_id'],
            status=data['status'],
            quantity=Decimal(str(data['quantity'])),
            average_purchase_price=Decimal(str(data['average_purchase_price'])),
            safety_orders=data['safety_orders'],
            latest_order_id=data['latest_order_id'],
            latest_order_created_at=data['latest_order_created_at'],
            last_order_fill_price=Decimal(str(data['last_order_fill_price'])) if data['last_order_fill_price'] is not None else None,
            completed_at=data['completed_at'],
            created_at=data['created_at'],
            updated_at=data['updated_at']
        )


def get_latest_cycle(asset_id: int) -> Optional[DcaCycle]:
    """
    Fetches the most recent cycle for a given asset_id.
    
    Args:
        asset_id: The asset ID to fetch the latest cycle for
        
    Returns:
        DcaCycle: Latest cycle if found, None otherwise
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        SELECT id, asset_id, status, quantity, average_purchase_price,
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               completed_at, created_at, updated_at
        FROM dca_cycles 
        WHERE asset_id = %s
        ORDER BY id DESC
        LIMIT 1
        """
        
        result = execute_query(query, (asset_id,), fetch_one=True)
        
        if result:
            logger.debug(f"Found latest cycle for asset {asset_id}: cycle ID {result['id']}")
            return DcaCycle.from_dict(result)
        else:
            logger.debug(f"No cycles found for asset {asset_id}")
            return None
            
    except Error as e:
        logger.error(f"Error fetching latest cycle for asset {asset_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching latest cycle for asset {asset_id}: {e}")
        raise


def create_cycle(
    asset_id: int,
    status: str,
    quantity: Decimal = Decimal('0'),
    average_purchase_price: Decimal = Decimal('0'),
    safety_orders: int = 0,
    latest_order_id: Optional[str] = None,
    latest_order_created_at: Optional[datetime] = None,
    last_order_fill_price: Optional[Decimal] = None,
    completed_at: Optional[datetime] = None
) -> DcaCycle:
    """
    Inserts a new cycle record and returns the created DcaCycle object.
    
    Args:
        asset_id: ID of the asset this cycle belongs to
        status: Initial status of the cycle
        quantity: Initial quantity (default: 0)
        average_purchase_price: Initial average purchase price (default: 0)
        safety_orders: Initial safety order count (default: 0)
        latest_order_id: ID of the latest order (default: None)
        latest_order_created_at: Timestamp when the latest order was created (default: None)
        last_order_fill_price: Price of the last order fill (default: None)
        completed_at: Completion timestamp (default: None)
        
    Returns:
        DcaCycle: The newly created cycle with ID and timestamps from DB
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        INSERT INTO dca_cycles (
            asset_id, status, quantity, average_purchase_price,
            safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price, completed_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            asset_id,
            status,
            quantity,
            average_purchase_price,
            safety_orders,
            latest_order_id,
            latest_order_created_at,
            last_order_fill_price,
            completed_at
        )
        
        cycle_id = execute_query(query, params, commit=True)
        
        if cycle_id:
            logger.info(f"Created new cycle {cycle_id} for asset {asset_id} with status '{status}'")
            
            # Fetch the complete cycle record with timestamps
            fetch_query = """
            SELECT id, asset_id, status, quantity, average_purchase_price,
                   safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
                   completed_at, created_at, updated_at
            FROM dca_cycles 
            WHERE id = %s
            """
            
            result = execute_query(fetch_query, (cycle_id,), fetch_one=True)
            
            if result:
                return DcaCycle.from_dict(result)
            else:
                raise Error(f"Failed to fetch newly created cycle {cycle_id}")
        else:
            raise Error("Failed to create new cycle - no ID returned")
            
    except Error as e:
        logger.error(f"Error creating cycle for asset {asset_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error creating cycle for asset {asset_id}: {e}")
        raise


def update_cycle(cycle_id: int, updates: dict) -> bool:
    """
    Updates specified fields of a cycle.
    
    Args:
        cycle_id: ID of the cycle to update
        updates: Dictionary of column_name: new_value pairs
        
    Returns:
        bool: True if update was successful
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    if not updates:
        logger.warning("No updates provided for cycle update")
        return False
        
    try:
        # Build the SET clause dynamically
        set_clauses = []
        params = []
        
        for column, value in updates.items():
            set_clauses.append(f"{column} = %s")
            params.append(value)
        
        # Add the cycle_id for the WHERE clause
        params.append(cycle_id)
        
        query = f"""
        UPDATE dca_cycles 
        SET {', '.join(set_clauses)}
        WHERE id = %s
        """
        
        rows_affected = execute_query(query, params, commit=True)
        
        if rows_affected and rows_affected > 0:
            logger.info(f"Updated cycle {cycle_id} with {len(updates)} fields")
            return True
        else:
            logger.warning(f"No rows affected when updating cycle {cycle_id}")
            return False
            
    except Error as e:
        logger.error(f"Error updating cycle {cycle_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error updating cycle {cycle_id}: {e}")
        raise


def get_cycle_by_id(cycle_id: int) -> Optional[DcaCycle]:
    """
    Fetches a cycle by its ID.
    
    Args:
        cycle_id: The cycle ID to fetch
        
    Returns:
        DcaCycle: Cycle if found, None otherwise
        
    Raises:
        mysql.connector.Error: If database query fails
    """
    try:
        query = """
        SELECT id, asset_id, status, quantity, average_purchase_price,
               safety_orders, latest_order_id, latest_order_created_at, last_order_fill_price,
               completed_at, created_at, updated_at
        FROM dca_cycles 
        WHERE id = %s
        """
        
        result = execute_query(query, (cycle_id,), fetch_one=True)
        
        if result:
            logger.debug(f"Found cycle {cycle_id}")
            return DcaCycle.from_dict(result)
        else:
            logger.debug(f"No cycle found with ID {cycle_id}")
            return None
            
    except Error as e:
        logger.error(f"Error fetching cycle {cycle_id}: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error fetching cycle {cycle_id}: {e}")
        raise 