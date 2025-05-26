#!/usr/bin/env python3
"""
Cleanup script for cycles with positions too small for take-profit orders.

This script identifies cycles where the quantity is below Alpaca's minimum order size
and provides options to handle them.
"""

import sys
import os
from decimal import Decimal
from datetime import datetime, timezone

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.db_utils import execute_query
from models.cycle_data import update_cycle
from utils.alpaca_client_rest import get_trading_client, get_positions

# Alpaca's minimum order quantity for crypto
MIN_ORDER_QTY = Decimal('0.000000002')

def get_tiny_position_cycles():
    """Get all cycles with positions too small for take-profit orders."""
    query = """
    SELECT dc.id, da.asset_symbol, dc.status, dc.quantity, dc.average_purchase_price, 
           dc.safety_orders, dc.created_at
    FROM dca_cycles dc 
    JOIN dca_assets da ON dc.asset_id = da.id 
    WHERE dc.status = 'watching' 
    AND dc.quantity > 0 
    AND dc.quantity < %s
    ORDER BY da.asset_symbol, dc.created_at
    """
    
    return execute_query(query, (MIN_ORDER_QTY,), fetch_all=True)

def get_alpaca_positions_summary():
    """Get summary of current Alpaca positions."""
    client = get_trading_client()
    if not client:
        print("❌ Could not get Alpaca client")
        return {}
    
    positions = get_positions(client)
    position_map = {}
    
    for pos in positions:
        # Convert symbol format (PEPEUSD -> PEPE/USD)
        symbol = pos.symbol
        if len(symbol) > 3 and '/' not in symbol:
            # Add slash for crypto pairs (assuming last 3 chars are USD)
            symbol = f"{symbol[:-3]}/{symbol[-3:]}"
        
        position_map[symbol] = {
            'qty': Decimal(str(pos.qty)),
            'avg_price': Decimal(str(pos.avg_entry_price)),
            'market_value': Decimal(str(pos.market_value))
        }
    
    return position_map

def main():
    print("🔍 Tiny Position Cleanup Tool")
    print("=" * 50)
    print(f"Minimum order quantity: {MIN_ORDER_QTY}")
    print()
    
    # Get cycles with tiny positions
    tiny_cycles = get_tiny_position_cycles()
    
    if not tiny_cycles:
        print("✅ No cycles found with positions below minimum order size")
        return
    
    print(f"Found {len(tiny_cycles)} cycles with tiny positions:")
    print()
    
    # Get Alpaca positions for comparison
    alpaca_positions = get_alpaca_positions_summary()
    
    for cycle in tiny_cycles:
        symbol = cycle['asset_symbol']
        cycle_id = cycle['id']
        status = cycle['status']
        quantity = Decimal(str(cycle['quantity']))
        avg_price = Decimal(str(cycle['average_purchase_price']))
        safety_orders = cycle['safety_orders']
        created_at = cycle['created_at']
        
        print(f"📊 Cycle {cycle_id} - {symbol}")
        print(f"   Status: {status}")
        print(f"   DB Quantity: {quantity}")
        print(f"   Avg Price: ${avg_price:.10f}")
        print(f"   Safety Orders: {safety_orders}")
        print(f"   Created: {created_at}")
        
        # Check Alpaca position
        if symbol in alpaca_positions:
            alpaca_qty = alpaca_positions[symbol]['qty']
            alpaca_avg = alpaca_positions[symbol]['avg_price']
            market_value = alpaca_positions[symbol]['market_value']
            
            print(f"   Alpaca Qty: {alpaca_qty}")
            print(f"   Alpaca Avg: ${alpaca_avg:.10f}")
            print(f"   Market Value: ${market_value:.2f}")
            
            if alpaca_qty != quantity:
                print(f"   ⚠️  Quantity mismatch: DB={quantity}, Alpaca={alpaca_qty}")
        else:
            print(f"   ❌ No corresponding Alpaca position found")
        
        print()
    
    print("Options:")
    print("1. Mark tiny position cycles as 'complete' (recommended)")
    print("2. Reset tiny position cycles to 'watching' with zero quantity")
    print("3. Do nothing (manual review)")
    print()
    
    choice = input("Enter your choice (1-3): ").strip()
    
    if choice == '1':
        mark_cycles_complete(tiny_cycles)
    elif choice == '2':
        reset_cycles_to_zero(tiny_cycles)
    elif choice == '3':
        print("No action taken. Manual review recommended.")
    else:
        print("Invalid choice. No action taken.")

def mark_cycles_complete(cycles):
    """Mark cycles as complete."""
    print(f"\n🔄 Marking {len(cycles)} cycles as complete...")
    
    for cycle in cycles:
        cycle_id = cycle['id']
        symbol = cycle['asset_symbol']
        
        updates = {
            'status': 'complete',
            'completed_at': datetime.now(timezone.utc)
        }
        
        success = update_cycle(cycle_id, updates)
        if success:
            print(f"   ✅ Cycle {cycle_id} ({symbol}) marked as complete")
        else:
            print(f"   ❌ Failed to update cycle {cycle_id} ({symbol})")
    
    print("\n✅ Cleanup completed. These cycles are now marked as complete.")
    print("💡 New 'watching' cycles will be created automatically for these assets.")

def reset_cycles_to_zero(cycles):
    """Reset cycles to zero quantity."""
    print(f"\n🔄 Resetting {len(cycles)} cycles to zero quantity...")
    
    for cycle in cycles:
        cycle_id = cycle['id']
        symbol = cycle['asset_symbol']
        
        updates = {
            'quantity': Decimal('0'),
            'average_purchase_price': Decimal('0'),
            'safety_orders': 0,
            'last_order_fill_price': None
        }
        
        success = update_cycle(cycle_id, updates)
        if success:
            print(f"   ✅ Cycle {cycle_id} ({symbol}) reset to zero")
        else:
            print(f"   ❌ Failed to update cycle {cycle_id} ({symbol})")
    
    print("\n✅ Reset completed. These cycles are now ready for new base orders.")

if __name__ == "__main__":
    main() 