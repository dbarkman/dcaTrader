#!/usr/bin/env python3
"""
DCA Trading Bot - Cycle Lifecycle Checker

This script analyzes the complete lifecycle of a specific trading cycle by examining:
1. Database cycle and asset information
2. Application logs for order placement and fills
3. Alpaca order history for verification

Usage: python check_cycle.py <cycle_id>
Example: python check_cycle.py 7
"""

import sys
import os
import re
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db_utils import execute_query
from utils.alpaca_client_rest import get_trading_client
from utils.formatting import format_price, format_quantity

def get_cycle_details(cycle_id):
    """Get complete cycle information from database."""
    query = """
    SELECT 
        c.id, c.asset_id, c.status, c.quantity, c.average_purchase_price,
        c.safety_orders, c.latest_order_id, c.latest_order_created_at, 
        c.last_order_fill_price, c.highest_trailing_price, c.completed_at, 
        c.created_at, c.updated_at, c.sell_price,
        a.asset_symbol, a.base_order_amount, a.safety_order_amount,
        a.take_profit_percent, a.ttp_enabled, a.ttp_deviation_percent,
        a.max_safety_orders, a.safety_order_deviation, a.cooldown_period,
        a.last_sell_price
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.id = %s
    """
    
    result = execute_query(query, (cycle_id,), fetch_one=True)
    return result

def search_logs_for_cycle(cycle_id, symbol):
    """Search application logs for all entries related to a specific cycle."""
    print(f"\n📋 Searching logs for cycle {cycle_id} ({symbol})...")
    
    log_file = Path('logs/main.log')
    if not log_file.exists():
        print(f"   ⚠️ Log file {log_file} not found")
        return []
    
    entries = []
    cycle_patterns = [
        rf"cycle {cycle_id}\b",
        rf"Cycle {cycle_id}\b",
        rf"CYCLE_START.*{symbol}",
        rf"CYCLE_COMPLETE.*{symbol}",
        rf"CYCLE_CONTINUE.*{symbol}",
        rf"CYCLE_ERROR.*{symbol}"
    ]
    
    try:
        with open(log_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                # Check if line mentions our cycle or symbol lifecycle events
                for pattern in cycle_patterns:
                    if re.search(pattern, line, re.IGNORECASE):
                        entries.append({
                            'line_num': line_num,
                            'timestamp': line[:19] if len(line) > 19 else 'Unknown',
                            'line': line.strip(),
                            'type': classify_log_entry(line)
                        })
                        break
    
    except Exception as e:
        print(f"   ❌ Error reading log file: {e}")
        return []
    
    # Sort by timestamp
    entries.sort(key=lambda x: x['timestamp'])
    print(f"   📝 Found {len(entries)} log entries")
    return entries

def classify_log_entry(line):
    """Classify log entry type for better organization."""
    line_lower = line.lower()
    
    if 'order placed' in line_lower or 'placing' in line_lower:
        return 'ORDER_PLACEMENT'
    elif 'order filled' in line_lower or 'fill' in line_lower:
        return 'ORDER_FILL'
    elif 'trade update' in line_lower:
        return 'TRADE_UPDATE'
    elif 'cycle_start' in line_lower:
        return 'CYCLE_START'
    elif 'cycle_complete' in line_lower:
        return 'CYCLE_COMPLETE'
    elif 'cycle_continue' in line_lower:
        return 'CYCLE_CONTINUE'
    elif 'error' in line_lower:
        return 'ERROR'
    elif 'updated cycle' in line_lower:
        return 'CYCLE_UPDATE'
    else:
        return 'OTHER'

def get_alpaca_orders_for_cycle(client, symbol, start_date, end_date=None):
    """Get Alpaca orders for the cycle timeframe."""
    if not client:
        return []
    
    try:
        # Get all orders for the symbol in the timeframe
        orders = client.get_orders()
        
        # Filter by symbol and timeframe
        symbol_alpaca = symbol.replace('/', '')  # Convert BTC/USD to BTCUSD
        relevant_orders = []
        
        for order in orders:
            if order.symbol == symbol_alpaca:
                order_time = order.created_at.replace(tzinfo=None) if order.created_at.tzinfo else order.created_at
                
                # Check if order is in our timeframe
                if start_date <= order_time:
                    if end_date is None or order_time <= end_date:
                        relevant_orders.append(order)
        
        return relevant_orders
        
    except Exception as e:
        print(f"   ❌ Error fetching Alpaca orders: {e}")
        return []

def analyze_cycle_profitability(cycle):
    """Calculate detailed profitability metrics."""
    if not cycle['sell_price'] or not cycle['average_purchase_price']:
        return None
    
    buy_price = Decimal(str(cycle['average_purchase_price']))
    sell_price = Decimal(str(cycle['sell_price']))
    quantity = Decimal(str(cycle['quantity']))
    
    # Calculate metrics
    profit_per_unit = sell_price - buy_price
    total_profit = profit_per_unit * quantity
    profit_percentage = (profit_per_unit / buy_price) * 100
    total_investment = buy_price * quantity
    roi = (total_profit / total_investment) * 100
    
    # Calculate expected vs actual profit
    expected_profit_pct = Decimal(str(cycle['take_profit_percent']))
    profit_vs_expected = profit_percentage - expected_profit_pct
    
    return {
        'profit_per_unit': profit_per_unit,
        'total_profit': total_profit,
        'profit_percentage': profit_percentage,
        'total_investment': total_investment,
        'roi': roi,
        'expected_profit_pct': expected_profit_pct,
        'profit_vs_expected': profit_vs_expected
    }

def print_cycle_overview(cycle):
    """Print comprehensive cycle overview."""
    print(f"\n{'='*80}")
    print(f"🔍 CYCLE {cycle['id']} - {cycle['asset_symbol']} LIFECYCLE ANALYSIS")
    print(f"{'='*80}")
    
    # Basic Information
    print(f"\n📊 BASIC INFORMATION:")
    print(f"   Cycle ID: {cycle['id']}")
    print(f"   Asset: {cycle['asset_symbol']}")
    print(f"   Status: {cycle['status']}")
    print(f"   Created: {cycle['created_at']}")
    if cycle['completed_at']:
        duration = cycle['completed_at'] - cycle['created_at']
        print(f"   Completed: {cycle['completed_at']}")
        print(f"   Duration: {duration}")
    else:
        print(f"   Completed: Not completed")
    
    # Trading Details
    print(f"\n💰 TRADING DETAILS:")
    print(f"   Quantity: {cycle['quantity']}")
    print(f"   Average Purchase Price: ${cycle['average_purchase_price']}")
    if cycle['sell_price']:
        print(f"   Sell Price: ${cycle['sell_price']}")
    print(f"   Safety Orders Used: {cycle['safety_orders']}/{cycle['max_safety_orders']}")
    if cycle['last_order_fill_price']:
        print(f"   Last Order Fill Price: ${cycle['last_order_fill_price']}")
    if cycle['highest_trailing_price']:
        print(f"   Highest Trailing Price: ${cycle['highest_trailing_price']}")
    
    # Asset Configuration
    print(f"\n⚙️ ASSET CONFIGURATION:")
    print(f"   Base Order Amount: ${cycle['base_order_amount']}")
    print(f"   Safety Order Amount: ${cycle['safety_order_amount']}")
    print(f"   Take Profit %: {cycle['take_profit_percent']}%")
    print(f"   Safety Order Deviation: {cycle['safety_order_deviation']}%")
    print(f"   TTP Enabled: {cycle['ttp_enabled']}")
    if cycle['ttp_enabled'] and cycle['ttp_deviation_percent']:
        print(f"   TTP Deviation %: {cycle['ttp_deviation_percent']}%")
    print(f"   Cooldown Period: {cycle['cooldown_period']} seconds")

def print_log_analysis(log_entries):
    """Print organized log analysis."""
    print(f"\n📋 LOG ANALYSIS:")
    
    if not log_entries:
        print("   No log entries found")
        return
    
    # Group entries by type
    by_type = {}
    for entry in log_entries:
        entry_type = entry['type']
        if entry_type not in by_type:
            by_type[entry_type] = []
        by_type[entry_type].append(entry)
    
    # Print summary
    print(f"   Total Entries: {len(log_entries)}")
    for entry_type, entries in by_type.items():
        print(f"   {entry_type}: {len(entries)} entries")
    
    # Print chronological timeline
    print(f"\n📅 CHRONOLOGICAL TIMELINE:")
    for i, entry in enumerate(log_entries, 1):
        print(f"   {i:2d}. {entry['timestamp']} - {entry['type']}")
        # Show key parts of the log line
        line = entry['line']
        if len(line) > 120:
            line = line[:117] + "..."
        print(f"       {line}")
    
    # Highlight key lifecycle events
    key_events = [e for e in log_entries if e['type'] in ['CYCLE_START', 'CYCLE_COMPLETE', 'CYCLE_CONTINUE']]
    if key_events:
        print(f"\n🎯 KEY LIFECYCLE EVENTS:")
        for event in key_events:
            print(f"   • {event['timestamp']} - {event['type']}")

def print_alpaca_analysis(orders, symbol):
    """Print Alpaca order analysis."""
    print(f"\n🏦 ALPACA ORDER ANALYSIS:")
    
    if not orders:
        print("   No Alpaca orders found for this timeframe")
        return
    
    print(f"   Found {len(orders)} orders for {symbol}")
    
    # Separate buy and sell orders
    buy_orders = [o for o in orders if str(o.side).lower() == 'buy']
    sell_orders = [o for o in orders if str(o.side).lower() == 'sell']
    
    print(f"   Buy Orders: {len(buy_orders)}")
    print(f"   Sell Orders: {len(sell_orders)}")
    
    # Analyze each order
    print(f"\n📋 ORDER DETAILS:")
    for i, order in enumerate(orders, 1):
        side_emoji = '🛒' if str(order.side).lower() == 'buy' else '💰'
        status_emoji = '✅' if str(order.status) == 'filled' else '❌' if str(order.status) == 'canceled' else '⏳'
        
        print(f"   {i}. {side_emoji} {status_emoji} {order.id}")
        print(f"      Side: {order.side} | Status: {order.status}")
        print(f"      Quantity: {order.qty}")
        if hasattr(order, 'limit_price') and order.limit_price:
            print(f"      Limit Price: ${order.limit_price}")
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            print(f"      Filled Price: ${order.filled_avg_price}")
        print(f"      Created: {order.created_at}")
        if hasattr(order, 'filled_at') and order.filled_at:
            print(f"      Filled: {order.filled_at}")
        print()

def print_profitability_analysis(cycle):
    """Print detailed profitability analysis."""
    print(f"\n📈 PROFITABILITY ANALYSIS:")
    
    profitability = analyze_cycle_profitability(cycle)
    if not profitability:
        print("   Cannot calculate profitability - missing price data")
        return
    
    print(f"   Total Investment: ${profitability['total_investment']:.2f}")
    print(f"   Total Profit: ${profitability['total_profit']:.2f}")
    print(f"   Profit Percentage: {profitability['profit_percentage']:.2f}%")
    print(f"   ROI: {profitability['roi']:.2f}%")
    print(f"   Expected Profit: {profitability['expected_profit_pct']:.2f}%")
    print(f"   vs Expected: {profitability['profit_vs_expected']:+.2f}%")
    
    # Performance assessment
    if profitability['profit_vs_expected'] >= 0:
        print(f"   🎯 Performance: ✅ Met or exceeded target")
    else:
        print(f"   🎯 Performance: ⚠️ Below target (likely TTP exit)")

def print_unrealized_pnl_analysis(cycle):
    """Print unrealized P&L analysis for active cycles with positions."""
    if cycle['quantity'] <= 0 or not cycle['average_purchase_price']:
        return
    
    print(f"\n📊 UNREALIZED P&L ANALYSIS:")
    print("   (Note: Based on current market price estimates)")
    
    # Calculate take-profit target price
    avg_price = Decimal(str(cycle['average_purchase_price']))
    take_profit_pct = Decimal(str(cycle['take_profit_percent']))
    target_price = avg_price * (Decimal('1') + take_profit_pct / Decimal('100'))
    
    quantity = Decimal(str(cycle['quantity']))
    total_investment = avg_price * quantity
    
    print(f"   Average Purchase Price: ${avg_price:.4f}")
    print(f"   Current Position: {quantity} {cycle['asset_symbol'].split('/')[0]}")
    print(f"   Total Investment: ${total_investment:.2f}")
    print(f"   Take-Profit Target: ${target_price:.4f} ({take_profit_pct}% gain)")
    
    # Show TTP info if enabled
    if cycle['ttp_enabled'] and cycle['highest_trailing_price']:
        peak_price = Decimal(str(cycle['highest_trailing_price']))
        ttp_deviation = Decimal(str(cycle['ttp_deviation_percent']))
        ttp_sell_trigger = peak_price * (Decimal('1') - ttp_deviation / Decimal('100'))
        
        print(f"   TTP Peak Price: ${peak_price:.4f}")
        print(f"   TTP Sell Trigger: ${ttp_sell_trigger:.4f} ({ttp_deviation}% below peak)")
        
        if cycle['status'] == 'trailing':
            print(f"   🎯 Status: TTP ACTIVE - Trailing the market")
        else:
            print(f"   🎯 Status: Waiting for take-profit trigger (${target_price:.4f})")
    else:
        print(f"   🎯 Status: Waiting for take-profit trigger (${target_price:.4f})")
    
    # Calculate distance to target
    price_needed_gain = target_price - avg_price
    price_needed_pct = (price_needed_gain / avg_price) * 100
    
    print(f"   Price Gain Needed: ${price_needed_gain:.4f} ({price_needed_pct:.2f}%)")
    
    # Estimate potential profit at target
    potential_profit = price_needed_gain * quantity
    print(f"   Potential Profit at Target: ${potential_profit:.2f}")

def print_cycle_summary(cycle, log_entries, orders, profitability):
    """Print overall cycle summary and assessment."""
    print(f"\n{'='*80}")
    print(f"📊 CYCLE SUMMARY & ASSESSMENT")
    print(f"{'='*80}")
    
    # Lifecycle completeness
    print(f"\n🔄 LIFECYCLE COMPLETENESS:")
    
    has_start = any(e['type'] == 'CYCLE_START' for e in log_entries)
    has_completion = cycle['status'] == 'complete'
    has_orders = len(orders) > 0
    has_profitability = profitability is not None
    
    print(f"   ✅ Cycle Start Logged: {'Yes' if has_start else 'No'}")
    print(f"   ✅ Cycle Completed: {'Yes' if has_completion else 'No'}")
    print(f"   ✅ Alpaca Orders Found: {'Yes' if has_orders else 'No'}")
    print(f"   ✅ Profitability Data: {'Yes' if has_profitability else 'No'}")
    
    # Overall assessment
    print(f"\n🎯 OVERALL ASSESSMENT:")
    
    if has_completion and has_profitability:
        if profitability['total_profit'] > 0:
            print(f"   Status: ✅ SUCCESSFUL CYCLE")
            print(f"   Result: Profitable trade completed successfully")
        else:
            print(f"   Status: ⚠️ COMPLETED BUT UNPROFITABLE")
            print(f"   Result: Cycle completed but resulted in loss")
    elif cycle['status'] in ['watching', 'buying', 'selling', 'trailing']:
        print(f"   Status: ⏳ ACTIVE CYCLE")
        print(f"   Result: Cycle is still in progress")
    elif cycle['status'] == 'cooldown':
        print(f"   Status: ❄️ COOLDOWN PERIOD")
        print(f"   Result: Cycle completed, waiting for next opportunity")
    elif cycle['status'] == 'error':
        print(f"   Status: ❌ ERROR STATE")
        print(f"   Result: Cycle encountered an error")
    else:
        print(f"   Status: ❓ UNKNOWN STATE")
        print(f"   Result: Cycle in unexpected state: {cycle['status']}")
    
    # Data consistency check
    print(f"\n🔍 DATA CONSISTENCY:")
    
    issues = []
    
    # Check for required fields based on status
    if cycle['status'] == 'complete':
        if not cycle['completed_at']:
            issues.append("Missing completed_at timestamp")
        if not cycle['sell_price']:
            issues.append("Missing sell_price")
    
    if cycle['quantity'] > 0:
        if not cycle['average_purchase_price'] or cycle['average_purchase_price'] <= 0:
            issues.append("Invalid average_purchase_price")
    
    if cycle['safety_orders'] > cycle['max_safety_orders']:
        issues.append(f"Safety orders ({cycle['safety_orders']}) exceed maximum ({cycle['max_safety_orders']})")
    
    if issues:
        print(f"   ⚠️ Issues Found:")
        for issue in issues:
            print(f"      • {issue}")
    else:
        print(f"   ✅ No data consistency issues found")

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Analyze DCA trading cycle lifecycle')
    parser.add_argument('cycle_id', type=int, help='Cycle ID to analyze')
    parser.add_argument('--no-alpaca', action='store_true', help='Skip Alpaca order analysis')
    
    args = parser.parse_args()
    cycle_id = args.cycle_id
    
    print(f"🔍 DCA Trading Bot - Cycle {cycle_id} Lifecycle Analysis")
    print("=" * 60)
    
    # Get cycle details from database
    print(f"\n📊 Loading cycle {cycle_id} from database...")
    cycle = get_cycle_details(cycle_id)
    
    if not cycle:
        print(f"❌ Cycle {cycle_id} not found in database")
        sys.exit(1)
    
    print(f"✅ Found cycle {cycle_id} for {cycle['asset_symbol']}")
    
    # Print cycle overview
    print_cycle_overview(cycle)
    
    # Search logs for cycle activity
    log_entries = search_logs_for_cycle(cycle_id, cycle['asset_symbol'])
    print_log_analysis(log_entries)
    
    # Get Alpaca orders if requested
    orders = []
    if not args.no_alpaca:
        print(f"\n🏦 Fetching Alpaca orders for {cycle['asset_symbol']}...")
        client = get_trading_client()
        if client:
            # Use cycle timeframe for order search
            start_date = cycle['created_at'] - timedelta(hours=1)  # Start 1 hour before cycle
            end_date = cycle['completed_at'] + timedelta(hours=1) if cycle['completed_at'] else datetime.now()
            
            orders = get_alpaca_orders_for_cycle(client, cycle['asset_symbol'], start_date, end_date)
            print_alpaca_analysis(orders, cycle['asset_symbol'])
        else:
            print("   ⚠️ Could not initialize Alpaca client")
    else:
        print(f"\n🏦 Skipping Alpaca order analysis (--no-alpaca)")
    
    # Profitability analysis
    profitability = None
    if cycle['status'] == 'complete':
        profitability = analyze_cycle_profitability(cycle)
        print_profitability_analysis(cycle)
    else:
        # For active cycles, show unrealized P&L analysis
        print_unrealized_pnl_analysis(cycle)
    
    # Final summary
    print_cycle_summary(cycle, log_entries, orders, profitability)
    
    print(f"\n🎉 Analysis complete for cycle {cycle_id}")

if __name__ == "__main__":
    main() 