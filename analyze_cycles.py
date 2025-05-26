#!/usr/bin/env python3
"""
Analyze DCA cycles with safety orders and compare with Alpaca positions
to verify trigger price calculations are accurate.
"""

import sys
import os
from decimal import Decimal

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db_utils import execute_query
from utils.alpaca_client_rest import get_trading_client, get_positions

def get_cycles_with_safety_orders():
    """Get all cycles that have safety orders placed."""
    query = """
    SELECT 
        da.asset_symbol,
        dc.id as cycle_id,
        dc.status,
        dc.quantity,
        dc.average_purchase_price,
        dc.last_order_fill_price,
        dc.safety_orders,
        da.safety_order_deviation,
        da.take_profit_percent,
        da.max_safety_orders
    FROM dca_cycles dc
    JOIN dca_assets da ON dc.asset_id = da.id
    WHERE dc.safety_orders > 0 
      AND dc.status = 'watching'
      AND dc.quantity > 0
    ORDER BY dc.safety_orders DESC, da.asset_symbol
    """
    
    return execute_query(query, fetch_all=True)

def calculate_trigger_prices(cycle):
    """Calculate the next safety order and take-profit trigger prices."""
    last_fill_price = cycle['last_order_fill_price']
    avg_purchase_price = cycle['average_purchase_price']
    safety_deviation = cycle['safety_order_deviation']
    take_profit_percent = cycle['take_profit_percent']
    
    # Next safety order trigger (price must drop below this)
    safety_trigger = None
    if last_fill_price and safety_deviation:
        safety_trigger = last_fill_price * (Decimal('1') - safety_deviation / Decimal('100'))
    
    # Take-profit trigger (price must rise above this)
    take_profit_trigger = None
    if avg_purchase_price and take_profit_percent:
        take_profit_trigger = avg_purchase_price * (Decimal('1') + take_profit_percent / Decimal('100'))
    
    return safety_trigger, take_profit_trigger

def get_alpaca_position_data():
    """Get current Alpaca positions."""
    try:
        client = get_trading_client()
        if not client:
            print("❌ Could not get Alpaca trading client")
            return {}
        
        positions = get_positions(client)
        
        # Convert to dict keyed by symbol (with slash format)
        position_data = {}
        for pos in positions:
            # Convert BTCUSD -> BTC/USD format for comparison
            symbol = pos.symbol
            if len(symbol) >= 6 and symbol.endswith('USD'):
                base = symbol[:-3]
                formatted_symbol = f"{base}/USD"
                position_data[formatted_symbol] = {
                    'qty': Decimal(str(pos.qty)),
                    'avg_entry_price': Decimal(str(pos.avg_entry_price)),
                    'market_value': Decimal(str(pos.market_value)) if hasattr(pos, 'market_value') else None,
                    'unrealized_pl': Decimal(str(pos.unrealized_pl)) if hasattr(pos, 'unrealized_pl') else None
                }
        
        return position_data
        
    except Exception as e:
        print(f"❌ Error fetching Alpaca positions: {e}")
        return {}

def analyze_cycle_accuracy():
    """Main analysis function."""
    print("🔍 Analyzing DCA Cycles with Safety Orders vs Alpaca Positions")
    print("=" * 80)
    
    # Get cycles with safety orders
    cycles = get_cycles_with_safety_orders()
    if not cycles:
        print("ℹ️  No cycles with safety orders found")
        return
    
    # Get Alpaca positions
    alpaca_positions = get_alpaca_position_data()
    
    print(f"📊 Found {len(cycles)} cycles with safety orders")
    print(f"📊 Found {len(alpaca_positions)} Alpaca positions")
    print()
    
    for cycle in cycles:
        symbol = cycle['asset_symbol']
        cycle_id = cycle['cycle_id']
        
        print(f"🔄 Cycle {cycle_id}: {symbol}")
        print(f"   Status: {cycle['status']}")
        print(f"   Safety Orders: {cycle['safety_orders']}/{cycle['max_safety_orders']}")
        
        # Database values
        db_qty = cycle['quantity']
        db_avg_price = cycle['average_purchase_price']
        db_last_fill = cycle['last_order_fill_price']
        
        print(f"   📊 DB Quantity: {db_qty}")
        
        # Use higher precision for micro-cap tokens
        if db_avg_price and db_avg_price < Decimal('0.01'):
            print(f"   💰 DB Avg Price: ${db_avg_price:.10f}")
        else:
            print(f"   💰 DB Avg Price: ${db_avg_price:.4f}")
            
        if db_last_fill and db_last_fill < Decimal('0.01'):
            print(f"   📈 DB Last Fill: ${db_last_fill:.10f}")
        else:
            print(f"   📈 DB Last Fill: ${db_last_fill:.4f}")
        
        # Calculate trigger prices
        safety_trigger, take_profit_trigger = calculate_trigger_prices(cycle)
        
        if safety_trigger:
            if safety_trigger < Decimal('0.01'):
                print(f"   🛡️  Next Safety Trigger: ${safety_trigger:.10f} (if price drops {cycle['safety_order_deviation']}%)")
            else:
                print(f"   🛡️  Next Safety Trigger: ${safety_trigger:.4f} (if price drops {cycle['safety_order_deviation']}%)")
        
        if take_profit_trigger:
            if take_profit_trigger < Decimal('0.01'):
                print(f"   💰 Take-Profit Trigger: ${take_profit_trigger:.10f} (if price rises {cycle['take_profit_percent']}%)")
            else:
                print(f"   💰 Take-Profit Trigger: ${take_profit_trigger:.4f} (if price rises {cycle['take_profit_percent']}%)")
        
        # Compare with Alpaca
        alpaca_pos = alpaca_positions.get(symbol)
        if alpaca_pos:
            alpaca_qty = alpaca_pos['qty']
            alpaca_avg = alpaca_pos['avg_entry_price']
            
            print(f"   🏦 Alpaca Quantity: {alpaca_qty}")
            
            if alpaca_avg < Decimal('0.01'):
                print(f"   🏦 Alpaca Avg Price: ${alpaca_avg:.10f}")
            else:
                print(f"   🏦 Alpaca Avg Price: ${alpaca_avg:.4f}")
            
            # Check for discrepancies
            qty_diff = abs(db_qty - alpaca_qty)
            price_diff = abs(db_avg_price - alpaca_avg)
            
            if qty_diff > Decimal('0.0001'):  # Allow small rounding differences
                print(f"   ⚠️  QUANTITY MISMATCH: DB={db_qty}, Alpaca={alpaca_qty}, Diff={qty_diff}")
            
            if price_diff > Decimal('0.01'):  # Allow $0.01 difference
                print(f"   ⚠️  PRICE MISMATCH: DB=${db_avg_price:.4f}, Alpaca=${alpaca_avg:.4f}, Diff=${price_diff:.4f}")
            
            if qty_diff <= Decimal('0.0001') and price_diff <= Decimal('0.01'):
                print(f"   ✅ Position data matches Alpaca")
                
            # Show P&L if available
            if alpaca_pos['unrealized_pl']:
                pl_pct = (alpaca_pos['unrealized_pl'] / (alpaca_qty * alpaca_avg)) * 100
                print(f"   📈 Unrealized P&L: ${alpaca_pos['unrealized_pl']:.2f} ({pl_pct:.2f}%)")
        else:
            print(f"   ❌ No Alpaca position found for {symbol}")
        
        print()

if __name__ == "__main__":
    analyze_cycle_accuracy() 