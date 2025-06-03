#!/usr/bin/env python3
"""
DCA Trading Bot - Cycle Lifecycle Checker

This script analyzes the complete lifecycle of a specific trading cycle by examining:
1. Database cycle and asset information
2. Order history from dca_orders table
3. Alpaca order history for verification

Usage: python check_cycle.py <cycle_id>
Example: python check_cycle.py 7
"""

import sys
import os
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal

# Add src directory to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.db_utils import execute_query
from utils.alpaca_client_rest import get_trading_client
from utils.formatting import format_price, format_quantity

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def colored(text, color):
    """Apply color to text."""
    return f"{color}{text}{Colors.END}"

def format_number(value, is_currency=False, decimal_places=2):
    """Format numbers with commas for values >= 1,000."""
    try:
        if isinstance(value, str):
            # Handle string values that might contain currency symbols
            clean_value = value.replace('$', '').replace(',', '')
            num_value = float(clean_value)
        else:
            num_value = float(value)
        
        if abs(num_value) >= 1000:
            if is_currency:
                return f"${num_value:,.{decimal_places}f}"
            else:
                return f"{num_value:,.{decimal_places}f}"
        else:
            if is_currency:
                return f"${num_value:.{decimal_places}f}"
            else:
                return f"{num_value:.{decimal_places}f}"
    except (ValueError, TypeError):
        return str(value)

def print_grid(headers, rows, title=None):
    """Print a nicely formatted grid with headers and rows."""
    if title:
        print(f'\n{colored(title, Colors.CYAN + Colors.BOLD)}')
        print(colored('=' * len(title), Colors.CYAN))
    
    if not rows:
        print(colored('No data to display.', Colors.YELLOW))
        return
    
    # Calculate column widths with minimum and maximum constraints
    col_widths = []
    for i, header in enumerate(headers):
        max_width = len(str(header))
        for row in rows:
            if i < len(row):
                max_width = max(max_width, len(str(row[i])))
        # Add padding and set reasonable limits
        col_widths.append(min(max(max_width + 2, 8), 25))
    
    # Print header
    header_line = '|'.join(colored(str(headers[i]).ljust(col_widths[i]), Colors.BOLD) for i in range(len(headers)))
    print(header_line)
    print(colored('-' * sum(col_widths) + '-' * (len(headers) - 1), Colors.BLUE))
    
    # Print rows
    for row in rows:
        row_line = '|'.join(str(row[i] if i < len(row) else '').ljust(col_widths[i]) for i in range(len(headers)))
        print(row_line)

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

def get_orders_for_cycle(cycle_id, symbol, start_date, end_date=None):
    """Get orders from dca_orders table for the cycle timeframe."""
    print(f"\n{colored('📋 Fetching orders from dca_orders table...', Colors.BLUE)}")
    
    # For completed cycles, use a tighter time window to avoid picking up orders from subsequent cycles
    if end_date:
        # Add only 15 minutes buffer after completion instead of 1 hour to avoid next cycle orders
        from datetime import timedelta
        tight_end_date = end_date - timedelta(minutes=45)  # Reduce the 1-hour buffer to 15 minutes
        
        query = """
        SELECT 
            id,
            symbol,
            side,
            status,
            order_type,
            qty,
            filled_qty,
            filled_avg_price,
            limit_price,
            created_at,
            filled_at,
            canceled_at,
            client_order_id
        FROM dca_orders 
        WHERE symbol = %s
        AND created_at BETWEEN %s AND %s
        ORDER BY created_at ASC
        """
        params = (symbol, start_date, tight_end_date)
        print(f"   Using tight time window: {start_date.strftime('%Y-%m-%d %H:%M:%S')} to {tight_end_date.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        # For active cycles, use the original logic
        query = """
        SELECT 
            id,
            symbol,
            side,
            status,
            order_type,
            qty,
            filled_qty,
            filled_avg_price,
            limit_price,
            created_at,
            filled_at,
            canceled_at,
            client_order_id
        FROM dca_orders 
        WHERE symbol = %s
        AND created_at >= %s
        ORDER BY created_at ASC
        """
        params = (symbol, start_date)
        print(f"   Using open time window: {start_date.strftime('%Y-%m-%d %H:%M:%S')} onwards")
    
    try:
        orders = execute_query(query, params, fetch_all=True)
        
        # Additional filtering: Remove orders that are clearly from subsequent cycles
        if end_date and orders:
            filtered_orders = []
            cycle_sell_found = False
            
            for order in orders:
                # If we find a SELL order, mark that the cycle likely ended
                if order['side'].lower() == 'sell' and order['status'] == 'filled':
                    filtered_orders.append(order)
                    cycle_sell_found = True
                    cycle_sell_time = order['filled_at'] or order['created_at']
                    print(f"   Found cycle SELL order at {cycle_sell_time}")
                # Include BUY orders that happened before the sell or within reasonable time
                elif order['side'].lower() == 'buy':
                    if not cycle_sell_found:
                        # No sell found yet, include all buy orders
                        filtered_orders.append(order)
                    else:
                        # Sell found, only include buy orders that happened before or very close to sell time
                        order_time = order['filled_at'] or order['created_at']
                        if order_time <= cycle_sell_time + timedelta(minutes=2):  # 2 minute grace period
                            filtered_orders.append(order)
                        else:
                            print(f"   Excluding BUY order from {order_time} (after cycle completion)")
                else:
                    # Include other order types (canceled, etc.)
                    filtered_orders.append(order)
            
            orders = filtered_orders
        
        print(f"   {colored(f'✅ Found {len(orders)} orders for {symbol}', Colors.GREEN)}")
        return orders
    except Exception as e:
        print(f"   {colored(f'❌ Error fetching orders: {e}', Colors.RED)}")
        return []

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
        print(f"   {colored(f'❌ Error fetching Alpaca orders: {e}', Colors.RED)}")
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
    print(f"\n{colored('='*80, Colors.HEADER)}")
    cycle_title = f"🔍 CYCLE {cycle['id']} - {cycle['asset_symbol']} LIFECYCLE ANALYSIS"
    print(f"{colored(cycle_title, Colors.HEADER + Colors.BOLD)}")
    print(f"{colored('='*80, Colors.HEADER)}")
    
    # Basic Information
    print(f"\n{colored('📊 BASIC INFORMATION:', Colors.CYAN + Colors.BOLD)}")
    print(f"   Cycle ID: {colored(str(cycle['id']), Colors.YELLOW)}")
    print(f"   Asset: {colored(cycle['asset_symbol'], Colors.YELLOW)}")
    
    # Color code status
    status_color = Colors.GREEN if cycle['status'] == 'complete' else Colors.YELLOW if cycle['status'] in ['watching', 'buying'] else Colors.RED
    print(f"   Status: {colored(cycle['status'], status_color)}")
    
    print(f"   Created: {colored(str(cycle['created_at']), Colors.BLUE)}")
    if cycle['completed_at']:
        duration = cycle['completed_at'] - cycle['created_at']
        print(f"   Completed: {colored(str(cycle['completed_at']), Colors.BLUE)}")
        print(f"   Duration: {colored(str(duration), Colors.BLUE)}")
    else:
        print(f"   Completed: {colored('Not completed', Colors.YELLOW)}")
    
    # Trading Details
    print(f"\n{colored('💰 TRADING DETAILS:', Colors.CYAN + Colors.BOLD)}")
    print(f"   Quantity: {colored(format_number(cycle['quantity'], decimal_places=6), Colors.GREEN)}")
    avg_price_text = format_number(cycle['average_purchase_price'], is_currency=True)
    print(f"   Average Purchase Price: {colored(avg_price_text, Colors.GREEN)}")
    if cycle['sell_price']:
        sell_price_text = format_number(cycle['sell_price'], is_currency=True)
        print(f"   Sell Price: {colored(sell_price_text, Colors.GREEN)}")
    
    safety_color = Colors.RED if cycle['safety_orders'] >= cycle['max_safety_orders'] else Colors.YELLOW if cycle['safety_orders'] > 0 else Colors.GREEN
    safety_text = f"{cycle['safety_orders']}/{cycle['max_safety_orders']}"
    print(f"   Safety Orders Used: {colored(safety_text, safety_color)}")
    
    if cycle['last_order_fill_price']:
        last_fill_text = format_number(cycle['last_order_fill_price'], is_currency=True)
        print(f"   Last Order Fill Price: {colored(last_fill_text, Colors.BLUE)}")
    if cycle['highest_trailing_price']:
        trailing_text = format_number(cycle['highest_trailing_price'], is_currency=True)
        print(f"   Highest Trailing Price: {colored(trailing_text, Colors.BLUE)}")

def print_orders_analysis(orders, symbol):
    """Print organized order analysis using grid format."""
    print(f"\n{colored('📋 ORDER ANALYSIS:', Colors.CYAN + Colors.BOLD)}")
    
    if not orders:
        print(f"   {colored('No orders found for this timeframe', Colors.YELLOW)}")
        return
    
    # Summary statistics
    buy_orders = [o for o in orders if o['side'].lower() == 'buy']
    sell_orders = [o for o in orders if o['side'].lower() == 'sell']
    filled_orders = [o for o in orders if o['status'] == 'filled']
    canceled_orders = [o for o in orders if o['status'] == 'canceled']
    
    print(f"   {colored(f'Total Orders: {len(orders)}', Colors.BLUE)}")
    print(f"   {colored(f'Buy Orders: {len(buy_orders)}', Colors.GREEN)} | {colored(f'Sell Orders: {len(sell_orders)}', Colors.RED)}")
    print(f"   {colored(f'Filled: {len(filled_orders)}', Colors.GREEN)} | {colored(f'Canceled: {len(canceled_orders)}', Colors.YELLOW)}")
    
    # Prepare grid data
    headers = ['Order ID', 'Side', 'Status', 'Type', 'Quantity', 'Filled Qty', 'Limit Price', 'Fill Price', 'Created', 'Filled/Canceled']
    rows = []
    
    for order in orders:
        # Truncate order ID for display
        order_id = order['id'][:8] + '...' if len(order['id']) > 8 else order['id']
        
        # Format quantities and prices
        qty = format_number(float(order['qty']), decimal_places=6) if order['qty'] else 'N/A'
        filled_qty = format_number(float(order['filled_qty']), decimal_places=6) if order['filled_qty'] else '0'
        limit_price = format_number(float(order['limit_price']), is_currency=True) if order['limit_price'] else 'N/A'
        fill_price = format_number(float(order['filled_avg_price']), is_currency=True) if order['filled_avg_price'] else 'N/A'
        
        # Format timestamps
        created = order['created_at'].strftime('%m/%d %H:%M') if order['created_at'] else 'N/A'
        
        # Determine final timestamp
        if order['filled_at']:
            final_time = order['filled_at'].strftime('%m/%d %H:%M')
        elif order['canceled_at']:
            final_time = order['canceled_at'].strftime('%m/%d %H:%M')
        else:
            final_time = 'N/A'
        
        rows.append([
            order_id,
            order['side'].upper(),
            order['status'].upper(),
            order['order_type'] or 'N/A',
            qty,
            filled_qty,
            limit_price,
            fill_price,
            created,
            final_time
        ])
    
    print_grid(headers, rows, f'\n📊 ORDER DETAILS FOR {symbol}')
    
    # Calculate total filled amounts
    total_buy_qty = sum(float(o['filled_qty'] or 0) for o in buy_orders if o['status'] == 'filled')
    total_sell_qty = sum(float(o['filled_qty'] or 0) for o in sell_orders if o['status'] == 'filled')
    
    if total_buy_qty > 0 or total_sell_qty > 0:
        print(f"\n{colored('📈 FILL SUMMARY:', Colors.CYAN + Colors.BOLD)}")
        if total_buy_qty > 0:
            print(f"   {colored(f'Total Bought: {format_number(total_buy_qty, decimal_places=6)}', Colors.GREEN)}")
        if total_sell_qty > 0:
            print(f"   {colored(f'Total Sold: {format_number(total_sell_qty, decimal_places=6)}', Colors.RED)}")
        
        net_position = total_buy_qty - total_sell_qty
        if net_position != 0:
            color = Colors.GREEN if net_position > 0 else Colors.RED
            sign = '+' if net_position > 0 else ''
            print(f"   {colored(f'Net Position: {sign}{format_number(net_position, decimal_places=6)}', color)}")

def print_alpaca_analysis(orders, symbol):
    """Print Alpaca order analysis."""
    print(f"\n{colored('🏦 ALPACA ORDER ANALYSIS:', Colors.CYAN + Colors.BOLD)}")
    
    if not orders:
        print(f"   {colored('No Alpaca orders found for this timeframe', Colors.YELLOW)}")
        return
    
    print(f"   {colored(f'Found {len(orders)} orders for {symbol}', Colors.GREEN)}")
    
    # Separate buy and sell orders
    buy_orders = [o for o in orders if str(o.side).lower() == 'buy']
    sell_orders = [o for o in orders if str(o.side).lower() == 'sell']
    
    print(f"   {colored(f'Buy Orders: {len(buy_orders)}', Colors.GREEN)} | {colored(f'Sell Orders: {len(sell_orders)}', Colors.RED)}")
    
    # Analyze each order
    print(f"\n{colored('📋 ORDER DETAILS:', Colors.BLUE)}")
    for i, order in enumerate(orders, 1):
        side_emoji = '🛒' if str(order.side).lower() == 'buy' else '💰'
        status_emoji = '✅' if str(order.status) == 'filled' else '❌' if str(order.status) == 'canceled' else '⏳'
        
        print(f"   {i}. {side_emoji} {status_emoji} {order.id}")
        print(f"      Side: {colored(str(order.side), Colors.GREEN if str(order.side).lower() == 'buy' else Colors.RED)} | Status: {colored(str(order.status), Colors.GREEN if str(order.status) == 'filled' else Colors.YELLOW)}")
        print(f"      Quantity: {colored(str(order.qty), Colors.BLUE)}")
        if hasattr(order, 'limit_price') and order.limit_price:
            print(f"      Limit Price: {colored(f'${order.limit_price}', Colors.BLUE)}")
        if hasattr(order, 'filled_avg_price') and order.filled_avg_price:
            print(f"      Filled Price: {colored(f'${order.filled_avg_price}', Colors.GREEN)}")
        print(f"      Created: {colored(str(order.created_at), Colors.BLUE)}")
        if hasattr(order, 'filled_at') and order.filled_at:
            print(f"      Filled: {colored(str(order.filled_at), Colors.GREEN)}")
        print()

def print_profitability_analysis(cycle):
    """Print detailed profitability analysis."""
    print(f"\n{colored('📈 PROFITABILITY ANALYSIS:', Colors.CYAN + Colors.BOLD)}")
    
    profitability = analyze_cycle_profitability(cycle)
    if not profitability:
        print(f"   {colored('Cannot calculate profitability - missing price data', Colors.YELLOW)}")
        return
    
    # Color code profit/loss
    profit_color = Colors.GREEN if profitability['total_profit'] > 0 else Colors.RED
    
    total_investment_text = format_number(profitability['total_investment'], is_currency=True)
    total_profit_text = format_number(profitability['total_profit'], is_currency=True)
    profit_pct_text = f"{profitability['profit_percentage']:.2f}%"
    roi_text = f"{profitability['roi']:.2f}%"
    expected_text = f"{profitability['expected_profit_pct']:.2f}%"
    vs_expected_text = f"{profitability['profit_vs_expected']:+.2f}%"
    
    print(f"   Total Investment: {colored(total_investment_text, Colors.BLUE)}")
    print(f"   Total Profit: {colored(total_profit_text, profit_color)}")
    print(f"   Profit Percentage: {colored(profit_pct_text, profit_color)}")
    print(f"   ROI: {colored(roi_text, profit_color)}")
    print(f"   Expected Profit: {colored(expected_text, Colors.BLUE)}")
    
    vs_expected_color = Colors.GREEN if profitability['profit_vs_expected'] >= 0 else Colors.YELLOW
    print(f"   vs Expected: {colored(vs_expected_text, vs_expected_color)}")
    
    # Performance assessment
    if profitability['profit_vs_expected'] >= 0:
        print(f"   🎯 Performance: {colored('✅ Met or exceeded target', Colors.GREEN)}")
    else:
        print(f"   🎯 Performance: {colored('⚠️ Below target (likely TTP exit)', Colors.YELLOW)}")

def print_unrealized_pnl_analysis(cycle):
    """Print unrealized P&L analysis for active cycles with positions."""
    if cycle['quantity'] <= 0 or not cycle['average_purchase_price']:
        return
    
    print(f"\n{colored('📊 UNREALIZED P&L ANALYSIS:', Colors.CYAN + Colors.BOLD)}")
    print(f"   {colored('(Note: Based on current market price estimates)', Colors.YELLOW)}")
    
    # Calculate take-profit target price
    avg_price = Decimal(str(cycle['average_purchase_price']))
    take_profit_pct = Decimal(str(cycle['take_profit_percent']))
    target_price = avg_price * (Decimal('1') + take_profit_pct / Decimal('100'))
    
    quantity = Decimal(str(cycle['quantity']))
    total_investment = avg_price * quantity
    
    avg_price_text = format_number(avg_price, is_currency=True, decimal_places=4)
    asset_symbol = cycle['asset_symbol'].split('/')[0]
    position_text = f"{format_number(quantity, decimal_places=6)} {asset_symbol}"
    investment_text = format_number(total_investment, is_currency=True)
    target_text = f"{format_number(target_price, is_currency=True, decimal_places=4)} ({take_profit_pct}% gain)"
    
    print(f"   Average Purchase Price: {colored(avg_price_text, Colors.BLUE)}")
    print(f"   Current Position: {colored(position_text, Colors.GREEN)}")
    print(f"   Total Investment: {colored(investment_text, Colors.BLUE)}")
    print(f"   Take-Profit Target: {colored(target_text, Colors.GREEN)}")
    
    # Show TTP info if enabled
    if cycle['ttp_enabled'] and cycle['highest_trailing_price']:
        peak_price = Decimal(str(cycle['highest_trailing_price']))
        ttp_deviation = Decimal(str(cycle['ttp_deviation_percent']))
        ttp_sell_trigger = peak_price * (Decimal('1') - ttp_deviation / Decimal('100'))
        
        peak_text = format_number(peak_price, is_currency=True, decimal_places=4)
        trigger_text = f"{format_number(ttp_sell_trigger, is_currency=True, decimal_places=4)} ({ttp_deviation}% below peak)"
        
        print(f"   TTP Peak Price: {colored(peak_text, Colors.YELLOW)}")
        print(f"   TTP Sell Trigger: {colored(trigger_text, Colors.YELLOW)}")
        
        if cycle['status'] == 'trailing':
            print(f"   🎯 Status: {colored('TTP ACTIVE - Trailing the market', Colors.YELLOW)}")
        else:
            status_text = f"Waiting for take-profit trigger ({target_text})"
            print(f"   🎯 Status: {colored(status_text, Colors.BLUE)}")
    else:
        status_text = f"Waiting for take-profit trigger ({target_text})"
        print(f"   🎯 Status: {colored(status_text, Colors.BLUE)}")
    
    # Calculate distance to target
    price_needed_gain = target_price - avg_price
    price_needed_pct = (price_needed_gain / avg_price) * 100
    
    gain_text = f"{format_number(price_needed_gain, is_currency=True, decimal_places=4)} ({price_needed_pct:.2f}%)"
    print(f"   Price Gain Needed: {colored(gain_text, Colors.CYAN)}")
    
    # Estimate potential profit at target
    potential_profit = price_needed_gain * quantity
    profit_text = format_number(potential_profit, is_currency=True)
    print(f"   Potential Profit at Target: {colored(profit_text, Colors.GREEN)}")

def print_cycle_summary(cycle, orders, alpaca_orders, profitability):
    """Print overall cycle summary and assessment."""
    print(f"\n{colored('='*80, Colors.HEADER)}")
    print(f"{colored('📊 CYCLE SUMMARY & ASSESSMENT', Colors.HEADER + Colors.BOLD)}")
    print(f"{colored('='*80, Colors.HEADER)}")
    
    # Lifecycle completeness
    print(f"\n{colored('🔄 LIFECYCLE COMPLETENESS:', Colors.CYAN + Colors.BOLD)}")
    
    has_completion = cycle['status'] == 'complete'
    has_orders = len(orders) > 0
    has_alpaca_orders = len(alpaca_orders) > 0
    has_profitability = profitability is not None
    
    print(f"   ✅ Cycle Completed: {colored('Yes' if has_completion else 'No', Colors.GREEN if has_completion else Colors.YELLOW)}")
    print(f"   ✅ DCA Orders Found: {colored('Yes' if has_orders else 'No', Colors.GREEN if has_orders else Colors.YELLOW)}")
    print(f"   ✅ Alpaca Orders Found: {colored('Yes' if has_alpaca_orders else 'No', Colors.GREEN if has_alpaca_orders else Colors.YELLOW)}")
    print(f"   ✅ Profitability Data: {colored('Yes' if has_profitability else 'No', Colors.GREEN if has_profitability else Colors.YELLOW)}")
    
    # Overall assessment
    print(f"\n{colored('🎯 OVERALL ASSESSMENT:', Colors.CYAN + Colors.BOLD)}")
    
    if has_completion and has_profitability:
        if profitability['total_profit'] > 0:
            print(f"   Status: {colored('✅ SUCCESSFUL CYCLE', Colors.GREEN)}")
            print(f"   Result: {colored('Profitable trade completed successfully', Colors.GREEN)}")
        else:
            print(f"   Status: {colored('⚠️ COMPLETED BUT UNPROFITABLE', Colors.YELLOW)}")
            print(f"   Result: {colored('Cycle completed but resulted in loss', Colors.YELLOW)}")
    elif cycle['status'] in ['watching', 'buying', 'selling', 'trailing']:
        print(f"   Status: {colored('⏳ ACTIVE CYCLE', Colors.BLUE)}")
        print(f"   Result: {colored('Cycle is still in progress', Colors.BLUE)}")
    elif cycle['status'] == 'cooldown':
        print(f"   Status: {colored('❄️ COOLDOWN PERIOD', Colors.CYAN)}")
        print(f"   Result: {colored('Cycle completed, waiting for next opportunity', Colors.CYAN)}")
    elif cycle['status'] == 'error':
        print(f"   Status: {colored('❌ ERROR STATE', Colors.RED)}")
        print(f"   Result: {colored('Cycle encountered an error', Colors.RED)}")
    else:
        print(f"   Status: {colored('❓ UNKNOWN STATE', Colors.YELLOW)}")
        unknown_state_text = f"Cycle in unexpected state: {cycle['status']}"
        print(f"   Result: {colored(unknown_state_text, Colors.YELLOW)}")
    
    # Data consistency check
    print(f"\n{colored('🔍 DATA CONSISTENCY:', Colors.CYAN + Colors.BOLD)}")
    
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
        print(f"   {colored('⚠️ Issues Found:', Colors.YELLOW)}")
        for issue in issues:
            print(f"      • {colored(issue, Colors.YELLOW)}")
    else:
        print(f"   {colored('✅ No data consistency issues found', Colors.GREEN)}")

def main():
    """Main function."""
    parser = argparse.ArgumentParser(description='Analyze DCA trading cycle lifecycle')
    parser.add_argument('cycle_id', type=int, help='Cycle ID to analyze')
    parser.add_argument('--no-alpaca', action='store_true', help='Skip Alpaca order analysis')
    
    args = parser.parse_args()
    cycle_id = args.cycle_id
    
    print(f"{colored('🔍 DCA Trading Bot - Cycle', Colors.HEADER + Colors.BOLD)} {colored(str(cycle_id), Colors.YELLOW + Colors.BOLD)} {colored('Lifecycle Analysis', Colors.HEADER + Colors.BOLD)}")
    print(colored("=" * 60, Colors.HEADER))
    
    # Get cycle details from database
    loading_text = f"📊 Loading cycle {cycle_id} from database..."
    print(f"\n{colored(loading_text, Colors.BLUE)}")
    cycle = get_cycle_details(cycle_id)
    
    if not cycle:
        error_text = f"❌ Cycle {cycle_id} not found in database"
        print(f"{colored(error_text, Colors.RED)}")
        sys.exit(1)
    
    found_text = f"✅ Found cycle {cycle_id} for {cycle['asset_symbol']}"
    print(f"{colored(found_text, Colors.GREEN)}")
    
    # Print cycle overview
    print_cycle_overview(cycle)
    
    # Get orders from dca_orders table
    start_date = cycle['created_at'] - timedelta(hours=1)  # Start 1 hour before cycle
    end_date = cycle['completed_at'] + timedelta(hours=1) if cycle['completed_at'] else datetime.now()
    
    orders = get_orders_for_cycle(cycle_id, cycle['asset_symbol'], start_date, end_date)
    print_orders_analysis(orders, cycle['asset_symbol'])
    
    # Get Alpaca orders if requested
    alpaca_orders = []
    if not args.no_alpaca:
        alpaca_text = f"🏦 Fetching Alpaca orders for {cycle['asset_symbol']}..."
        print(f"\n{colored(alpaca_text, Colors.BLUE)}")
        client = get_trading_client()
        if client:
            alpaca_orders = get_alpaca_orders_for_cycle(client, cycle['asset_symbol'], start_date, end_date)
            print_alpaca_analysis(alpaca_orders, cycle['asset_symbol'])
        else:
            print(f"   {colored('⚠️ Could not initialize Alpaca client', Colors.YELLOW)}")
    else:
        print(f"\n{colored('🏦 Skipping Alpaca order analysis (--no-alpaca)', Colors.BLUE)}")
    
    # Profitability analysis
    profitability = None
    if cycle['status'] == 'complete':
        profitability = analyze_cycle_profitability(cycle)
        print_profitability_analysis(cycle)
    else:
        # For active cycles, show unrealized P&L analysis
        print_unrealized_pnl_analysis(cycle)
    
    # Final summary
    print_cycle_summary(cycle, orders, alpaca_orders, profitability)
    
    complete_text = f"🎉 Analysis complete for cycle {cycle_id}"
    print(f"\n{colored(complete_text, Colors.GREEN + Colors.BOLD)}")

if __name__ == "__main__":
    main() 