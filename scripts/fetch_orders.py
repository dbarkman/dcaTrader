#!/usr/bin/env python3
"""
Fetch Orders Caretaker Script

Fetches recent orders from Alpaca API and upserts them into the dca_orders table.
Runs every 15 minutes via cron to maintain a complete order history.

This script fetches the most recent 100 orders each run (no pagination needed).
"""

import sys
import os
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import List, Optional, Any

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.alpaca_client_rest import get_trading_client
from utils.db_utils import get_db_connection
from utils.logging_config import setup_caretaker_logging

# Configuration
FETCH_LIMIT = 100  # Fetch most recent 100 orders

def convert_enum_to_string(value: Any) -> Optional[str]:
    """Convert enum values to strings, handle None."""
    if value is None:
        return None
    if hasattr(value, 'value'):
        return str(value.value)
    return str(value)

def convert_decimal_field(value: Any) -> Optional[Decimal]:
    """Convert string/float to Decimal, handle None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except:
        return None

def convert_datetime_field(value: Any) -> Optional[datetime]:
    """Convert datetime field, ensure timezone awareness."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Assume UTC if no timezone
            return value.replace(tzinfo=timezone.utc)
        return value
    return None

def serialize_legs(legs: Any) -> Optional[str]:
    """Serialize legs field to JSON string."""
    if legs is None:
        return None
    try:
        # Convert legs to serializable format
        if hasattr(legs, '__iter__') and not isinstance(legs, str):
            # It's a list or similar iterable
            serializable_legs = []
            for leg in legs:
                if hasattr(leg, '__dict__'):
                    # Convert object to dict
                    leg_dict = {}
                    for attr in dir(leg):
                        if not attr.startswith('_') and not callable(getattr(leg, attr)):
                            try:
                                value = getattr(leg, attr)
                                if hasattr(value, 'value'):  # Enum
                                    leg_dict[attr] = str(value.value)
                                elif isinstance(value, (str, int, float, bool)) or value is None:
                                    leg_dict[attr] = value
                                else:
                                    leg_dict[attr] = str(value)
                            except:
                                pass
                    serializable_legs.append(leg_dict)
                else:
                    serializable_legs.append(str(leg))
            return json.dumps(serializable_legs)
        else:
            return json.dumps(str(legs))
    except Exception as e:
        # Logger is not available at module level, just return None on error
        return None

def order_to_dict(order) -> dict:
    """Convert order object to dictionary for database insertion."""
    return {
        'id': str(order.id),
        'client_order_id': str(order.client_order_id),
        'asset_id': str(order.asset_id) if order.asset_id else None,
        'symbol': order.symbol,
        'asset_class': convert_enum_to_string(order.asset_class),
        'order_class': convert_enum_to_string(order.order_class),
        'order_type': convert_enum_to_string(order.order_type),
        'type': convert_enum_to_string(order.type),
        'side': convert_enum_to_string(order.side),
        'position_intent': convert_enum_to_string(order.position_intent),
        'qty': convert_decimal_field(order.qty),
        'notional': convert_decimal_field(order.notional),
        'filled_qty': convert_decimal_field(order.filled_qty),
        'filled_avg_price': convert_decimal_field(order.filled_avg_price),
        'limit_price': convert_decimal_field(order.limit_price),
        'stop_price': convert_decimal_field(order.stop_price),
        'trail_price': convert_decimal_field(order.trail_price),
        'trail_percent': convert_decimal_field(order.trail_percent),
        'ratio_qty': convert_decimal_field(order.ratio_qty),
        'hwm': convert_decimal_field(order.hwm),
        'status': convert_enum_to_string(order.status),
        'time_in_force': convert_enum_to_string(order.time_in_force),
        'extended_hours': bool(order.extended_hours),
        'created_at': convert_datetime_field(order.created_at),
        'updated_at': convert_datetime_field(order.updated_at),
        'submitted_at': convert_datetime_field(order.submitted_at),
        'filled_at': convert_datetime_field(order.filled_at),
        'canceled_at': convert_datetime_field(order.canceled_at),
        'expired_at': convert_datetime_field(order.expired_at),
        'expires_at': convert_datetime_field(order.expires_at),
        'failed_at': convert_datetime_field(order.failed_at),
        'replaced_at': convert_datetime_field(order.replaced_at),
        'replaced_by': str(order.replaced_by) if order.replaced_by else None,
        'replaces': str(order.replaces) if order.replaces else None,
        'legs': serialize_legs(order.legs)
    }

def upsert_order(cursor, order_data: dict) -> bool:
    """Upsert order data into dca_orders table."""
    try:
        # Build the upsert query
        columns = list(order_data.keys())
        placeholders = ', '.join(['%s'] * len(columns))
        column_list = ', '.join(columns)
        
        # Build ON DUPLICATE KEY UPDATE clause
        update_clauses = []
        for col in columns:
            if col != 'id':  # Don't update the primary key
                update_clauses.append(f"{col} = VALUES({col})")
        update_clause = ', '.join(update_clauses)
        
        query = f"""
        INSERT INTO dca_orders ({column_list})
        VALUES ({placeholders})
        ON DUPLICATE KEY UPDATE {update_clause}
        """
        
        values = [order_data[col] for col in columns]
        cursor.execute(query, values)
        return True
        
    except Exception as e:
        logger.error(f"Failed to upsert order {order_data.get('id', 'unknown')}: {e}")
        return False

def fetch_recent_orders(client) -> List:
    """Fetch recent orders from Alpaca API."""
    try:
        from alpaca.trading.requests import GetOrdersRequest
        from alpaca.trading.enums import QueryOrderStatus
        
        # Build request for most recent orders
        request = GetOrdersRequest(
            status=QueryOrderStatus.ALL,
            limit=FETCH_LIMIT
        )
        
        orders = client.get_orders(filter=request)
        logger.info(f"Fetched {len(orders)} orders from Alpaca API")
        return orders
        
    except Exception as e:
        logger.error(f"Failed to fetch orders from Alpaca: {e}")
        return []

def main():
    """Main function."""
    global logger
    logger = setup_caretaker_logging('fetch_orders')
    
    logger.info("🔄 Starting fetch_orders caretaker")
    
    # Get Alpaca client
    client = get_trading_client()
    if not client:
        logger.error("❌ Could not initialize Alpaca client")
        return
    
    # Get database connection
    connection = get_db_connection()
    if not connection:
        logger.error("❌ Could not connect to database")
        return
    
    try:
        cursor = connection.cursor(dictionary=True)
        
        # Fetch recent orders
        logger.info(f"📊 Fetching most recent {FETCH_LIMIT} orders")
        orders = fetch_recent_orders(client)
        
        if not orders:
            logger.warning("No orders fetched")
            return
        
        # Upsert all orders
        total_upserted = 0
        for order in orders:
            order_data = order_to_dict(order)
            if upsert_order(cursor, order_data):
                total_upserted += 1
        
        connection.commit()
        logger.info(f"✅ Upserted {total_upserted}/{len(orders)} orders")
        logger.info("✅ fetch_orders caretaker completed successfully")
        
    except Exception as e:
        logger.error(f"❌ Error in fetch_orders caretaker: {e}")
        connection.rollback()
    finally:
        connection.close()

if __name__ == "__main__":
    main() 