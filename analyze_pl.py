#!/usr/bin/env python3
"""
DCA Trading Bot - P/L Analysis Script

This script analyzes both realized P/L from completed cycles and unrealized P/L 
from active positions. Uses dca_orders data to reinforce calculations where needed.
Integrates TradingView technical ratings for active cycles.

Usage: python analyze_pl.py [interval]
  interval: TradingView interval (1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1W, 1M)
            Default: 1h
"""

import sys
import os
import argparse
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db_utils import execute_query
from decimal import Decimal
from utils.alpaca_client_rest import get_trading_client
from datetime import datetime

# Global variable to store the configured interval
TRADINGVIEW_INTERVAL = None

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
    """Format numbers with commas for values >= 1,000 and dynamic decimal places for small currencies."""
    try:
        if isinstance(value, str):
            # Handle string values that might contain currency symbols
            clean_value = value.replace('$', '').replace(',', '')
            num_value = float(clean_value)
        else:
            num_value = float(value)
        
        # Dynamic decimal places for currency values
        if is_currency:
            if abs(num_value) >= 1000:
                # Large amounts: use 2 decimal places with commas
                return f"${num_value:,.2f}"
            elif abs(num_value) >= 1:
                # Medium amounts: use 2 decimal places
                return f"${num_value:.2f}"
            elif abs(num_value) >= 0.01:
                # Small amounts: use 4 decimal places
                return f"${num_value:.4f}"
            elif abs(num_value) >= 0.001:
                # Smaller amounts: use 6 decimal places
                return f"${num_value:.6f}"
            elif abs(num_value) >= 0.00001:
                # Very small amounts (like SHIB): use 10 decimal places
                return f"${num_value:.10f}"
            elif abs(num_value) >= 0.000001:
                # Extremely small amounts (like PEPE): use 12 decimal places
                return f"${num_value:.12f}"
            elif abs(num_value) > 0:
                # Ultra small amounts: use 14 decimal places
                return f"${num_value:.14f}"
            else:
                # Zero value
                return "$0.00"
        else:
            # Non-currency formatting
            if abs(num_value) >= 1000:
                return f"{num_value:,.{decimal_places}f}"
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
        col_widths.append(min(max(max_width + 2, 8), 20))
    
    # Print header
    header_line = ' | '.join(colored(str(headers[i]).ljust(col_widths[i]), Colors.BOLD) for i in range(len(headers)))
    print(header_line)
    print(colored('-' * (sum(col_widths) + (len(headers) - 1) * 3), Colors.BLUE))
    
    # Print rows
    for row in rows:
        row_line = ' | '.join(str(row[i] if i < len(row) else '').ljust(col_widths[i]) for i in range(len(headers)))
        print(row_line)

def get_tradingview_rating(symbol):
    """Get TradingView technical rating and trend for a symbol."""
    try:
        # Import here to avoid dependency issues if not installed
        from tradingview_ta import TA_Handler, Interval, Exchange
        
        # Map string intervals to Interval constants
        interval_map = {
            '1m': Interval.INTERVAL_1_MINUTE,
            '5m': Interval.INTERVAL_5_MINUTES,
            '15m': Interval.INTERVAL_15_MINUTES,
            '30m': Interval.INTERVAL_30_MINUTES,
            '1h': Interval.INTERVAL_1_HOUR,
            '2h': Interval.INTERVAL_2_HOURS,
            '4h': Interval.INTERVAL_4_HOURS,
            '1d': Interval.INTERVAL_1_DAY,
            '1W': Interval.INTERVAL_1_WEEK,
            '1M': Interval.INTERVAL_1_MONTH
        }
        
        # Get the interval from global variable or default to 1h
        interval_str = TRADINGVIEW_INTERVAL or '1h'
        if interval_str not in interval_map:
            print(f'{colored(f"⚠️  Invalid interval {interval_str}. Using 1h default.", Colors.YELLOW)}')
            interval_str = '1h'
        
        tv_interval = interval_map[interval_str]
        
        # Convert symbol format and handle different quote currencies
        base_symbol = symbol.split('/')[0]
        quote_symbol = symbol.split('/')[1] if '/' in symbol else 'USD'
        
        # Special mappings for specific tokens that use different formats on TradingView
        symbol_mappings = {
            'PEPE/USD': ('PEPEUSDT', 'crypto', 'BINANCE'),
            'SHIB/USD': ('SHIBUSDT', 'crypto', 'BINANCE'), 
            'TRUMP/USD': ('TRUMPUSDT', 'crypto', 'BINANCE'),
            'DOGE/USD': ('DOGEUSDT', 'crypto', 'BINANCE'),
            'BTC/USD': ('BTCUSDT', 'crypto', 'BINANCE'),
            'ETH/USD': ('ETHUSDT', 'crypto', 'BINANCE'),
            'SOL/USD': ('SOLUSDT', 'crypto', 'BINANCE'),
            'AVAX/USD': ('AVAXUSDT', 'crypto', 'BINANCE'),
            'LINK/USD': ('LINKUSDT', 'crypto', 'BINANCE'),
            'UNI/USD': ('UNIUSDT', 'crypto', 'BINANCE'),
            'AAVE/USD': ('AAVEUSDT', 'crypto', 'BINANCE'),
            'DOT/USD': ('DOTUSDT', 'crypto', 'BINANCE'),
            'LTC/USD': ('LTCUSDT', 'crypto', 'BINANCE'),
            'BCH/USD': ('BCHUSDT', 'crypto', 'BINANCE'),
            'XRP/USD': ('XRPUSDT', 'crypto', 'BINANCE'),
        }
        
        # Check if we have a specific mapping
        if symbol in symbol_mappings:
            tv_symbol, screener, exchange = symbol_mappings[symbol]
        else:
            # Default logic for other symbols
            if quote_symbol == 'USD' and symbol.endswith('/USD'):
                # For crypto pairs, try USDT first as most crypto uses USDT on TradingView
                tv_symbol = f"{base_symbol}USDT"
                screener = "crypto"
                exchange = "BINANCE"
            else:
                # For non-crypto or other formats
                tv_symbol = symbol.replace('/', '')
                screener = "america"
                exchange = "NASDAQ"
        
        # Create handler
        handler = TA_Handler(
            symbol=tv_symbol,
            screener=screener,
            exchange=exchange,
            interval=tv_interval
        )
        
        # Get analysis
        analysis = handler.get_analysis()
        recommendation = analysis.summary.get('RECOMMENDATION', 'NEUTRAL')
        
        # Get moving averages trend (better indicator of overall trend)
        ma_recommendation = analysis.moving_averages.get('RECOMMENDATION', 'NEUTRAL')
        
        # Map recommendation to shorter format
        rating_map = {
            'STRONG_BUY': 'Strong Buy',
            'BUY': 'Buy',
            'NEUTRAL': 'Neutral',
            'SELL': 'Sell',
            'STRONG_SELL': 'Strong Sell'
        }
        
        # Map trend to emoji
        trend_map = {
            'STRONG_BUY': '📈',  # Strong uptrend
            'BUY': '↗️',         # Uptrend
            'NEUTRAL': '➡️',     # Sideways/neutral
            'SELL': '↘️',        # Downtrend
            'STRONG_SELL': '📉'  # Strong downtrend
        }
        
        rating = rating_map.get(recommendation, recommendation)
        trend = trend_map.get(ma_recommendation, '❓')
        
        return rating, trend
        
    except ImportError:
        print(f'{colored("⚠️  TradingView TA library not installed. Install with: pip install tradingview-ta", Colors.YELLOW)}')
        return 'N/A', '❓'
    except Exception as e:
        # If the primary attempt fails, try alternative mappings
        try:
            # Fallback: try with USD instead of USDT for some symbols
            if symbol.endswith('/USD'):
                fallback_symbol = symbol.replace('/', '')  # BTCUSD format
                handler = TA_Handler(
                    symbol=fallback_symbol,
                    screener="crypto",
                    exchange="COINBASE",  # Try Coinbase for USD pairs
                    interval=tv_interval
                )
                analysis = handler.get_analysis()
                recommendation = analysis.summary.get('RECOMMENDATION', 'NEUTRAL')
                ma_recommendation = analysis.moving_averages.get('RECOMMENDATION', 'NEUTRAL')
                
                rating_map = {
                    'STRONG_BUY': 'Strong Buy',
                    'BUY': 'Buy', 
                    'NEUTRAL': 'Neutral',
                    'SELL': 'Sell',
                    'STRONG_SELL': 'Strong Sell'
                }
                
                trend_map = {
                    'STRONG_BUY': '📈',
                    'BUY': '↗️',
                    'NEUTRAL': '➡️',
                    'SELL': '↘️',
                    'STRONG_SELL': '📉'
                }
                
                rating = rating_map.get(recommendation, recommendation)
                trend = trend_map.get(ma_recommendation, '❓')
                
                return rating, trend
        except:
            pass
            
        print(f'{colored(f"⚠️  Could not fetch TradingView rating for {symbol}: {e}", Colors.YELLOW)}')
        return 'N/A', '❓'

def get_current_price(symbol, client):
    """Get current bid price for a symbol."""
    try:
        from alpaca.data.historical import CryptoHistoricalDataClient
        from alpaca.data.requests import CryptoLatestQuoteRequest
        
        data_client = CryptoHistoricalDataClient()
        request = CryptoLatestQuoteRequest(symbol_or_symbols=[symbol])
        quotes = data_client.get_crypto_latest_quote(request)
        
        if symbol in quotes:
            return Decimal(str(quotes[symbol].bid_price))
        return None
    except Exception:
        return None

def validate_cycle_with_orders(cycle_id, symbol):
    """Validate cycle data using dca_orders table for reinforcement."""
    try:
        # Get orders related to this cycle (if we can match by symbol and timeframe)
        orders_query = '''
        SELECT 
            COUNT(*) as order_count,
            SUM(CASE WHEN side = 'BUY' AND status = 'FILLED' THEN filled_qty ELSE 0 END) as total_buy_qty,
            AVG(CASE WHEN side = 'BUY' AND status = 'FILLED' THEN filled_avg_price ELSE NULL END) as avg_buy_price,
            MAX(created_at) as latest_order_time
        FROM dca_orders 
        WHERE symbol = %s 
        AND status = 'FILLED' 
        AND side = 'BUY'
        AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
        '''
        
        order_data = execute_query(orders_query, (symbol,), fetch_one=True)
        
        if order_data and order_data['order_count'] > 0:
            return {
                'order_count': order_data['order_count'],
                'total_qty': Decimal(str(order_data['total_buy_qty'] or '0')),
                'avg_price': Decimal(str(order_data['avg_buy_price'] or '0')),
                'latest_time': order_data['latest_order_time']
            }
        return None
    except Exception:
        return None

def analyze_completed_cycles():
    """Analyze P/L for completed cycles"""
    print(f'\n{colored("=== COMPLETED CYCLES ANALYSIS ===", Colors.HEADER + Colors.BOLD)}')
    
    completed_query = '''
    SELECT 
        COUNT(*) as total_cycles,
        SUM(c.quantity * c.average_purchase_price) as total_invested,
        AVG(c.quantity * c.average_purchase_price) as avg_invested_per_cycle,
        SUM(CASE WHEN c.sell_price IS NOT NULL 
            THEN c.quantity * (c.sell_price - c.average_purchase_price) 
            ELSE 0 END) as total_realized_pl,
        COUNT(CASE WHEN c.sell_price IS NOT NULL THEN 1 END) as cycles_with_sell_price
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status = 'complete'
    '''
    
    completed_results = execute_query(completed_query, fetch_one=True)
    
    if completed_results and completed_results['total_cycles']:
        total_cycles = completed_results['total_cycles']
        total_invested = Decimal(str(completed_results['total_invested']))
        avg_per_cycle = Decimal(str(completed_results['avg_invested_per_cycle']))
        total_realized_pl = Decimal(str(completed_results['total_realized_pl'] or '0'))
        cycles_with_sell_price = completed_results['cycles_with_sell_price']
        
        print(f'📋 Total Completed Cycles: {colored(str(total_cycles), Colors.BLUE)}')
        print(f'💰 Total Amount Invested: {colored(format_number(total_invested, is_currency=True), Colors.BLUE)}')
        print(f'📊 Average per Cycle: {colored(format_number(avg_per_cycle, is_currency=True), Colors.BLUE)}')
        
        # Color code P/L
        pl_color = Colors.GREEN if total_realized_pl >= 0 else Colors.RED
        print(f'💵 Total Realized P/L: {colored(format_number(total_realized_pl, is_currency=True), pl_color)}')
        
        # Calculate and display ROI
        if total_invested > 0:
            roi_percent = (total_realized_pl / total_invested) * 100
            roi_color = Colors.GREEN if roi_percent >= 0 else Colors.RED
            print(f'📈 ROI: {colored(f"{roi_percent:+.2f}%", roi_color)}')
        else:
            print(f'📈 ROI: {colored("N/A", Colors.YELLOW)}')
        
        print(f'📈 Cycles with sell_price data: {colored(f"{cycles_with_sell_price}/{total_cycles}", Colors.BLUE)}')
        
        if cycles_with_sell_price < total_cycles:
            missing_cycles = total_cycles - cycles_with_sell_price
            print(f'{colored(f"⚠️  {missing_cycles} cycles missing sell_price data (older cycles)", Colors.YELLOW)}')
        
        return total_realized_pl, total_cycles
    else:
        print(f'{colored("📋 No completed cycles found.", Colors.YELLOW)}')
        return Decimal('0'), 0

def analyze_active_cycles_summary():
    """Analyze unrealized P/L for active cycles - summary only"""
    print(f'\n{colored("=== ACTIVE CYCLES SUMMARY ===", Colors.HEADER + Colors.BOLD)}')
    
    active_query = '''
    SELECT 
        COUNT(*) as total_active,
        SUM(c.quantity * c.average_purchase_price) as total_invested
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status NOT IN ('complete', 'error') AND c.quantity > 0
    '''
    
    active_results = execute_query(active_query, fetch_one=True)
    
    if active_results and active_results['total_active']:
        total_active = active_results['total_active']
        total_invested = Decimal(str(active_results['total_invested']))
        
        print(f'📊 Total Active Cycles: {colored(str(total_active), Colors.BLUE)}')
        print(f'💵 Total Invested in Active Cycles: {colored(format_number(total_invested, is_currency=True), Colors.BLUE)}')
        
        return total_invested
    else:
        print(f'{colored("📊 No active cycles found.", Colors.YELLOW)}')
        return Decimal('0')

def analyze_active_cycles_detail():
    """Detailed analysis of each active cycle with current P/L and TradingView ratings"""
    active_query = '''
    SELECT 
        a.asset_symbol,
        c.id as cycle_id,
        c.status,
        c.quantity,
        c.average_purchase_price,
        c.safety_orders,
        c.last_order_fill_price,
        c.created_at as cycle_created_at
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status NOT IN ('complete', 'error') AND c.quantity > 0
    ORDER BY a.asset_symbol
    '''
    
    active_results = execute_query(active_query, fetch_all=True)
    
    if not active_results:
        print(f'\n{colored("=== ACTIVE CYCLES DETAIL ===", Colors.HEADER + Colors.BOLD)}')
        print(f'{colored("No active cycles found.", Colors.YELLOW)}')
        return
    
    # Get Alpaca client for price fetching
    try:
        client = get_trading_client()
    except Exception as e:
        print(f'{colored(f"❌ Unable to connect to Alpaca API: {e}", Colors.RED)}')
        print(f'{colored("Cannot fetch current prices for detailed analysis.", Colors.YELLOW)}')
        return
    
    cycle_data = []
    
    print(f'\n{colored("📊 Fetching TradingView technical ratings...", Colors.BLUE)}')
    
    for row in active_results:
        symbol = row['asset_symbol']
        cycle_id = row['cycle_id']
        status = row['status']
        quantity = Decimal(str(row['quantity']))
        avg_price = Decimal(str(row['average_purchase_price']))
        safety_orders = row['safety_orders']
        last_fill_price = Decimal(str(row['last_order_fill_price'])) if row['last_order_fill_price'] else None
        cycle_created_at = row['cycle_created_at']
        
        # Get first buy order price and timestamp from dca_orders table
        first_buy_query = '''
        SELECT 
            filled_avg_price as first_buy_price,
            created_at as first_buy_time
        FROM dca_orders 
        WHERE symbol = %s 
        AND side = 'BUY' 
        AND status = 'FILLED'
        AND created_at >= %s
        ORDER BY created_at ASC
        LIMIT 1
        '''
        
        first_buy_result = execute_query(first_buy_query, (symbol, cycle_created_at), fetch_one=True)
        
        if first_buy_result:
            first_buy_price = Decimal(str(first_buy_result['first_buy_price']))
            first_buy_time = first_buy_result['first_buy_time']
        else:
            # Fallback to average price if no order found
            first_buy_price = avg_price
            first_buy_time = cycle_created_at
        
        # Calculate age since first buy order
        if first_buy_time:
            age_delta = datetime.now() - first_buy_time
            days = age_delta.days
            hours, remainder = divmod(age_delta.seconds, 3600)
            minutes, _ = divmod(remainder, 60)
            age_str = f"{days:02d}:{hours:02d}:{minutes:02d}"
        else:
            age_str = "N/A"
        
        # Get current price
        current_price = get_current_price(symbol, client)
        
        # Get TradingView rating
        tech_rating, trend = get_tradingview_rating(symbol)
        
        if current_price and quantity > 0 and avg_price > 0:
            # Calculate current values
            cost_basis = quantity * avg_price
            current_value = quantity * current_price
            unrealized_pl = current_value - cost_basis
            unrealized_pct = (unrealized_pl / cost_basis * 100) if cost_basis > 0 else 0
            
            cycle_data.append({
                'symbol': symbol,
                'status': status,
                'quantity': format_number(quantity, decimal_places=6),
                'safety_orders': safety_orders,
                'first_buy_price': format_number(first_buy_price, is_currency=True),
                'avg_price': format_number(avg_price, is_currency=True),
                'last_fill': format_number(last_fill_price, is_currency=True) if last_fill_price else 'N/A',
                'age': age_str,
                'current_value': format_number(current_value, is_currency=True),
                'pl_pct': f'{unrealized_pct:+.2f}%',
                'tech_rating': tech_rating,
                'trend': trend,
                'unrealized_pct': unrealized_pct  # For sorting
            })
        else:
            # Handle cases where we can't get current price
            cycle_data.append({
                'symbol': symbol,
                'status': status,
                'quantity': format_number(quantity, decimal_places=6),
                'safety_orders': safety_orders,
                'first_buy_price': format_number(first_buy_price, is_currency=True),
                'avg_price': format_number(avg_price, is_currency=True),
                'last_fill': format_number(last_fill_price, is_currency=True) if last_fill_price else 'N/A',
                'age': age_str,
                'current_value': 'N/A',
                'pl_pct': 'N/A',
                'tech_rating': tech_rating,
                'trend': trend,
                'unrealized_pct': 0  # For sorting
            })
    
    # Sort by P/L % (highest to lowest)
    cycle_data.sort(key=lambda x: x['unrealized_pct'], reverse=True)
    
    # Prepare grid data with updated headers
    headers = ['Asset', 'Status', 'Quantity', 'SOs', 'Buy Order $', 'Avg Price', 'Last Fill', 'Age (D:H:M)', 'Current Value', 'P/L %', 'Tech Rating', 'Trend']
    rows = []
    
    for cycle in cycle_data:
        rows.append([
            cycle['symbol'],
            cycle['status'],
            cycle['quantity'],
            cycle['safety_orders'],
            cycle['first_buy_price'],
            cycle['avg_price'],
            cycle['last_fill'],
            cycle['age'],
            cycle['current_value'],
            cycle['pl_pct'],
            cycle['tech_rating'],
            cycle['trend']
        ])
    
    print_grid(headers, rows, '=== ACTIVE CYCLES DETAIL ===')

def analyze_completed_cycles_by_asset():
    """Analyze completed cycles P/L by asset"""
    completed_query = '''
    SELECT 
        a.asset_symbol,
        COUNT(*) as cycle_count,
        SUM(c.quantity * c.average_purchase_price) as total_invested,
        SUM(CASE WHEN c.sell_price IS NOT NULL 
            THEN c.quantity * (c.sell_price - c.average_purchase_price) 
            ELSE 0 END) as total_realized_pl
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status = 'complete'
    GROUP BY a.asset_symbol, a.id
    HAVING COUNT(*) > 0
    ORDER BY total_realized_pl DESC
    '''
    
    completed_results = execute_query(completed_query, fetch_all=True)
    
    if not completed_results:
        print(f'\n{colored("=== COMPLETED CYCLES BY ASSET ===", Colors.HEADER + Colors.BOLD)}')
        print(f'{colored("No completed cycles found.", Colors.YELLOW)}')
        return
    
    # Prepare grid data with P/L % calculation for sorting
    asset_data = []
    
    for row in completed_results:
        symbol = row['asset_symbol']
        cycle_count = row['cycle_count']
        total_invested = Decimal(str(row['total_invested']))
        total_pl = Decimal(str(row['total_realized_pl'] or '0'))
        
        # Calculate percentage
        pl_pct = (total_pl / total_invested * 100) if total_invested > 0 else 0
        
        asset_data.append({
            'symbol': symbol,
            'cycle_count': cycle_count,
            'total_pl': total_pl,
            'pl_pct': pl_pct,
            'pl_pct_display': f'{pl_pct:+.2f}%',
            'pl_display': format_number(total_pl, is_currency=True)
        })
    
    # Sort by P/L % (highest to lowest)
    asset_data.sort(key=lambda x: x['pl_pct'], reverse=True)
    
    # Prepare grid data
    headers = ['Asset', 'Cycles', 'P/L ($)', 'P/L (%)']
    rows = []
    
    for asset in asset_data:
        rows.append([
            asset['symbol'],
            asset['cycle_count'],
            asset['pl_display'],
            asset['pl_pct_display']
        ])
    
    print_grid(headers, rows, '=== COMPLETED CYCLES BY ASSET ===')
    
    # Check for error cycles with P/L impact
    error_query = '''
    SELECT 
        COUNT(*) as error_cycles,
        SUM(CASE WHEN c.sell_price IS NOT NULL 
            THEN c.quantity * (c.sell_price - c.average_purchase_price) 
            ELSE 0 END) as error_pl
    FROM dca_cycles c
    WHERE c.status = 'error' AND c.quantity > 0
    '''
    
    error_results = execute_query(error_query, fetch_one=True)
    
    if error_results and error_results['error_cycles'] > 0:
        error_cycles = error_results['error_cycles']
        error_pl = Decimal(str(error_results['error_pl'] or '0'))
        
        if error_pl != 0:
            error_color = Colors.GREEN if error_pl > 0 else Colors.RED
            error_text = f'⚠️  Error Cycles Impact: {error_cycles} cycles with {format_number(error_pl, is_currency=True)} P/L impact'
            print(f'\n{colored(error_text, error_color)}')

def analyze_market_sentiment():
    """Analyze overall crypto market sentiment using assets with active cycles."""
    print(f'\n{colored("=== 🌍 CRYPTO MARKET SENTIMENT (1H) ===", Colors.HEADER + Colors.BOLD)}')
    
    # Get all assets that currently have active cycles
    active_assets_query = '''
    SELECT DISTINCT a.asset_symbol
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status NOT IN ('complete', 'error') AND c.quantity > 0
    ORDER BY a.asset_symbol
    '''
    
    try:
        active_assets_results = execute_query(active_assets_query, fetch_all=True)
        if not active_assets_results:
            print(f'{colored("❌ No active cycles found for market sentiment analysis", Colors.RED)}')
            return
        
        active_assets = [row['asset_symbol'] for row in active_assets_results]
        
    except Exception as e:
        print(f'{colored(f"❌ Error fetching active assets: {e}", Colors.RED)}')
        return
    
    sentiment_data = []
    
    print(f'{colored(f"📊 Analyzing TradingView recommendation scores for {len(active_assets)} active assets...", Colors.BLUE)}')
    
    for symbol in active_assets:
        try:
            # Get the full analysis including indicators
            from tradingview_ta import TA_Handler, Interval
            
            # Map string intervals to Interval constants
            interval_map = {
                '1m': Interval.INTERVAL_1_MINUTE,
                '5m': Interval.INTERVAL_5_MINUTES,
                '15m': Interval.INTERVAL_15_MINUTES,
                '30m': Interval.INTERVAL_30_MINUTES,
                '1h': Interval.INTERVAL_1_HOUR,
                '2h': Interval.INTERVAL_2_HOURS,
                '4h': Interval.INTERVAL_4_HOURS,
                '1d': Interval.INTERVAL_1_DAY,
                '1W': Interval.INTERVAL_1_WEEK,
                '1M': Interval.INTERVAL_1_MONTH
            }
            
            # Get the interval from global variable or default to 1h
            interval_str = TRADINGVIEW_INTERVAL or '1h'
            if interval_str not in interval_map:
                interval_str = '1h'
            
            tv_interval = interval_map[interval_str]
            
            # Convert symbol format for TradingView
            base_symbol = symbol.split('/')[0]
            tv_symbol = f"{base_symbol}USDT"
            
            handler = TA_Handler(
                symbol=tv_symbol,
                screener="crypto",
                exchange="BINANCE",
                interval=tv_interval
            )
            
            analysis = handler.get_analysis()
            
            # Extract TradingView's recommendation scores
            recommend_all = analysis.indicators.get('Recommend.All', 0)  # Overall score (-1 to +1)
            recommend_ma = analysis.indicators.get('Recommend.MA', 0)    # Moving averages score
            recommend_other = analysis.indicators.get('Recommend.Other', 0)  # Oscillators score
            
            # Extract key sentiment indicators
            rsi = analysis.indicators.get('RSI', 50)  # RSI (0-100)
            adx = analysis.indicators.get('ADX', 0)   # Trend strength (0-100)
            
            # Get basic rating for display
            rating, trend = get_tradingview_rating(symbol)
            
            sentiment_data.append({
                'symbol': symbol,
                'rating': rating,
                'trend': trend,
                'recommend_all': recommend_all,
                'recommend_ma': recommend_ma,
                'recommend_other': recommend_other,
                'rsi': rsi,
                'adx': adx
            })
            
        except Exception as e:
            print(f'   {colored(f"⚠️ Could not analyze {symbol}: {e}", Colors.YELLOW)}')
            continue
    
    if not sentiment_data:
        print(f'{colored("❌ Unable to analyze market sentiment", Colors.RED)}')
        return
    
    # Calculate market-wide metrics using TradingView scores
    avg_recommend_all = sum(d['recommend_all'] for d in sentiment_data) / len(sentiment_data)
    avg_recommend_ma = sum(d['recommend_ma'] for d in sentiment_data) / len(sentiment_data)
    avg_recommend_other = sum(d['recommend_other'] for d in sentiment_data) / len(sentiment_data)
    avg_rsi = sum(d['rsi'] for d in sentiment_data) / len(sentiment_data)
    avg_adx = sum(d['adx'] for d in sentiment_data) / len(sentiment_data)
    
    # Determine overall market sentiment based on TradingView's composite score
    if avg_recommend_all > 0.3:
        market_sentiment = "🚀 BULLISH"
        sentiment_color = Colors.GREEN
    elif avg_recommend_all > 0.1:
        market_sentiment = "📈 MODERATELY BULLISH"
        sentiment_color = Colors.GREEN
    elif avg_recommend_all > -0.1:
        market_sentiment = "⚖️ NEUTRAL"
        sentiment_color = Colors.YELLOW
    elif avg_recommend_all > -0.3:
        market_sentiment = "📉 MODERATELY BEARISH"
        sentiment_color = Colors.RED
    else:
        market_sentiment = "🐻 BEARISH"
        sentiment_color = Colors.RED
    
    # RSI interpretation
    if avg_rsi > 70:
        rsi_status = "🔴 OVERBOUGHT"
        rsi_color = Colors.RED
    elif avg_rsi > 60:
        rsi_status = "🟡 APPROACHING OVERBOUGHT"
        rsi_color = Colors.YELLOW
    elif avg_rsi < 30:
        rsi_status = "🟢 OVERSOLD"
        rsi_color = Colors.GREEN
    elif avg_rsi < 40:
        rsi_status = "🟡 APPROACHING OVERSOLD"
        rsi_color = Colors.YELLOW
    else:
        rsi_status = "⚪ NEUTRAL"
        rsi_color = Colors.BLUE
    
    # Trend strength interpretation
    if avg_adx > 40:
        trend_strength = "💪 VERY STRONG TRENDS"
        trend_color = Colors.GREEN
    elif avg_adx > 25:
        trend_strength = "📈 STRONG TRENDS"
        trend_color = Colors.GREEN
    elif avg_adx > 15:
        trend_strength = "📊 MODERATE TRENDS"
        trend_color = Colors.YELLOW
    else:
        trend_strength = "😴 WEAK TRENDS"
        trend_color = Colors.RED
    
    # Display enhanced market overview
    print(f'\n{colored("📈 PORTFOLIO SENTIMENT OVERVIEW:", Colors.CYAN + Colors.BOLD)}')
    print(f'   Overall Sentiment: {colored(market_sentiment, sentiment_color + Colors.BOLD)}')
    print(f'   TradingView Score: {colored(f"{avg_recommend_all:+.3f}", sentiment_color)} (Range: -1.0 to +1.0)')
    print(f'   Active Assets Analyzed: {colored(str(len(sentiment_data)), Colors.BLUE)}')
    
    print(f'\n{colored("📊 DETAILED BREAKDOWN:", Colors.CYAN + Colors.BOLD)}')
    print(f'   Moving Averages: {colored(f"{avg_recommend_ma:+.3f}", Colors.GREEN if avg_recommend_ma > 0 else Colors.RED)}')
    print(f'   Oscillators: {colored(f"{avg_recommend_other:+.3f}", Colors.GREEN if avg_recommend_other > 0 else Colors.RED)}')
    print(f'   Average RSI: {colored(f"{avg_rsi:.1f}", rsi_color)} - {rsi_status}')
    print(f'   Trend Strength (ADX): {colored(f"{avg_adx:.1f}", trend_color)} - {trend_strength}')
    
    # Count bullish vs bearish assets using TradingView scores
    bullish_assets = [d for d in sentiment_data if d['recommend_all'] > 0.1]
    bearish_assets = [d for d in sentiment_data if d['recommend_all'] < -0.1]
    neutral_assets = [d for d in sentiment_data if -0.1 <= d['recommend_all'] <= 0.1]
    
    print(f'\n{colored("🎯 YOUR PORTFOLIO DISTRIBUTION:", Colors.CYAN + Colors.BOLD)}')
    print(f'   Bullish Positions: {colored(str(len(bullish_assets)), Colors.GREEN)} ({len(bullish_assets)/len(sentiment_data)*100:.0f}%)')
    print(f'   Neutral Positions: {colored(str(len(neutral_assets)), Colors.YELLOW)} ({len(neutral_assets)/len(sentiment_data)*100:.0f}%)')
    print(f'   Bearish Positions: {colored(str(len(bearish_assets)), Colors.RED)} ({len(bearish_assets)/len(sentiment_data)*100:.0f}%)')

def main():
    """Main analysis function"""
    print()  # Empty line for spacing after command prompt
    print(f'{colored("🤖 DCA TRADING BOT - P/L ANALYSIS", Colors.HEADER + Colors.BOLD)}')
    print(colored('=' * 50, Colors.HEADER))
    
    # Display TradingView interval info
    interval_str = TRADINGVIEW_INTERVAL or '1h'
    print(f'{colored(f"📊 TradingView Interval: {interval_str}", Colors.BLUE)}')
    print()
    
    try:
        # Analyze completed cycles
        realized_pl, completed_cycles = analyze_completed_cycles()
        
        # Analyze active cycles summary
        active_invested = analyze_active_cycles_summary()
        
        # Detailed active cycles analysis
        analyze_active_cycles_detail()
        
        # Completed cycles by asset
        analyze_completed_cycles_by_asset()
        
        # Market sentiment analysis
        analyze_market_sentiment()
        
        # Overall summary
        print(f'\n{colored("=== 📊 OVERALL PORTFOLIO SUMMARY ===", Colors.HEADER + Colors.BOLD)}')
        
        # Color code realized P/L
        realized_color = Colors.GREEN if realized_pl >= 0 else Colors.RED
        print(f'💰 Realized P/L (Completed): {colored(format_number(realized_pl, is_currency=True), realized_color)}')
        
        # Calculate and display ROI for overall summary
        # Get total historical investment for ROI calculation
        historical_query = """
        SELECT 
            SUM(c.quantity * c.average_purchase_price) as total_historical_investment
        FROM dca_cycles c
        WHERE c.status = 'complete' AND c.completed_at IS NOT NULL
        """
        historical_result = execute_query(historical_query, fetch_one=True)
        total_historical_investment = Decimal(str(historical_result['total_historical_investment'] or '0')) if historical_result else Decimal('0')
        
        if total_historical_investment > 0:
            roi_percent = (realized_pl / total_historical_investment) * 100
            roi_color = Colors.GREEN if roi_percent >= 0 else Colors.RED
            print(f'📈 ROI: {colored(f"{roi_percent:+.2f}%", roi_color)}')
        else:
            print(f'📈 ROI: {colored("N/A", Colors.YELLOW)}')
        
        print(f'💵 Active Investment: {colored(format_number(active_invested, is_currency=True), Colors.BLUE)}')
        print(f'📋 Completed Cycles: {colored(str(completed_cycles), Colors.BLUE)}')
        
    except Exception as e:
        print(f'{colored(f"❌ Error running analysis: {e}", Colors.RED)}')
        print(f'{colored("Make sure the DCA bot database is accessible and configured properly.", Colors.YELLOW)}')

if __name__ == '__main__':
    # Valid intervals for TradingView
    valid_intervals = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1W', '1M']
    
    intervals_str = ', '.join(valid_intervals)
    epilog_text = """
Examples:
  python analyze_pl.py       # Use default 1h interval
  python analyze_pl.py 4h    # Use 4-hour interval  
  python analyze_pl.py 1d    # Use daily interval

Valid intervals: """ + intervals_str + """
    """
    
    parser = argparse.ArgumentParser(
        description='DCA Trading Bot P/L Analysis with configurable TradingView interval',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=epilog_text
    )
    
    help_text = f'TradingView interval (default: 1h). Valid options: {intervals_str}'
    parser.add_argument(
        'interval', 
        nargs='?', 
        default='1h', 
        help=help_text
    )
    args = parser.parse_args()
    
    # Validate interval
    if args.interval not in valid_intervals:
        print(colored(f"❌ Invalid interval: {args.interval}", Colors.RED))
        print(colored(f"Valid intervals: {intervals_str}", Colors.YELLOW))
        sys.exit(1)
    
    # Set the global variable
    TRADINGVIEW_INTERVAL = args.interval
    
    main() 