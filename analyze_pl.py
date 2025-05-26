#!/usr/bin/env python3
"""
DCA Trading Bot - P/L Analysis Script

This script analyzes both realized P/L from completed cycles and unrealized P/L 
from active positions. Run this anytime to get a comprehensive view of your 
trading performance.

Usage: python analyze_pl.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from utils.db_utils import execute_query
from decimal import Decimal
from utils.alpaca_client_rest import get_trading_client, get_latest_crypto_price

def analyze_completed_cycles():
    """Analyze P/L for completed cycles"""
    print('=== COMPLETED CYCLES ANALYSIS ===')
    
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
        
        print(f'📋 Total Completed Cycles: {total_cycles}')
        print(f'💰 Total Amount Invested: ${total_invested:.2f}')
        print(f'📊 Average per Cycle: ${avg_per_cycle:.2f}')
        print(f'💵 Total Realized P/L: ${total_realized_pl:.2f}')
        print(f'📈 Cycles with sell_price data: {cycles_with_sell_price}/{total_cycles}')
        
        if cycles_with_sell_price < total_cycles:
            missing_cycles = total_cycles - cycles_with_sell_price
            print(f'⚠️  {missing_cycles} cycles missing sell_price data (older cycles)')
        
        return total_realized_pl, total_cycles
    else:
        print('📋 No completed cycles found.')
        return Decimal('0'), 0

def analyze_active_cycles():
    """Analyze unrealized P/L for active cycles"""
    print('\n\n=== ACTIVE CYCLES UNREALIZED P/L ===')
    
    active_query = '''
    SELECT 
        a.asset_symbol,
        c.quantity,
        c.average_purchase_price,
        c.safety_orders,
        c.created_at,
        c.status
    FROM dca_cycles c
    JOIN dca_assets a ON c.asset_id = a.id
    WHERE c.status IN ('watching', 'buying') AND c.quantity > 0
    ORDER BY a.asset_symbol, c.created_at
    '''
    
    active_results = execute_query(active_query, fetch_all=True)
    
    if active_results:
        total_unrealized_pl = Decimal('0')
        total_invested = Decimal('0')
        position_data = []
        
        # Get Alpaca client for price fetching
        try:
            client = get_trading_client()
        except Exception as e:
            print(f'❌ Unable to connect to Alpaca API: {e}')
            print('Cannot fetch current prices for unrealized P/L calculation.')
            return Decimal('0'), Decimal('0')
        
        for row in active_results:
            symbol = row['asset_symbol']
            quantity = Decimal(str(row['quantity']))
            avg_price = Decimal(str(row['average_purchase_price']))
            safety_orders = row['safety_orders']
            status = row['status']
            
            if quantity > 0 and avg_price > 0:
                # Get current bid price (what we could actually sell at)
                try:
                    from alpaca.data.historical import CryptoHistoricalDataClient
                    from alpaca.data.requests import CryptoLatestQuoteRequest
                    
                    data_client = CryptoHistoricalDataClient()
                    request = CryptoLatestQuoteRequest(symbol_or_symbols=[symbol])
                    quotes = data_client.get_crypto_latest_quote(request)
                    
                    if symbol in quotes:
                        current_price = Decimal(str(quotes[symbol].bid_price))  # Use bid price for realistic P/L
                        
                        # Calculate unrealized P/L
                        cost_basis = quantity * avg_price
                        current_value = quantity * current_price
                        unrealized_pl = current_value - cost_basis
                        unrealized_pct = (unrealized_pl / cost_basis * 100) if cost_basis > 0 else 0
                        
                        position_data.append({
                            'symbol': symbol,
                            'cost_basis': cost_basis,
                            'unrealized_pl': unrealized_pl,
                            'unrealized_pct': unrealized_pct,
                            'safety_orders': safety_orders
                        })
                        
                        total_unrealized_pl += unrealized_pl
                        total_invested += cost_basis
                    else:
                        print(f'⚠️  {symbol}: Unable to get current price')
                except Exception as e:
                    print(f'⚠️  {symbol}: Error getting price - {e}')
        
        # Sort positions for top performers and bags
        position_data.sort(key=lambda x: x['unrealized_pl'], reverse=True)
        
        print(f'📊 Active Positions: {len(position_data)} assets')
        print(f'💵 Total Invested: ${total_invested:.2f}')
        print(f'📈 Total Unrealized P/L: ${total_unrealized_pl:.2f}')
        if total_invested > 0:
            unrealized_pct = (total_unrealized_pl / total_invested * 100)
            print(f'🎯 Unrealized Return: {unrealized_pct:+.2f}%')
        
        # Show top 3 performers
        if position_data:
            print(f'\n🚀 TOP 3 PERFORMERS:')
            for i, pos in enumerate(position_data[:3]):
                if pos['unrealized_pl'] > 0:
                    print(f'  {i+1}. {pos["symbol"]}: +${pos["unrealized_pl"]:.2f} ({pos["unrealized_pct"]:+.2f}%)')
                else:
                    break
            
            # Show top 3 bags (worst performers)
            bags = [pos for pos in position_data if pos['unrealized_pl'] < 0]
            if bags:
                print(f'\n📉 TOP 3 BAGS:')
                bags.sort(key=lambda x: x['unrealized_pl'])  # Sort by worst first
                for i, pos in enumerate(bags[:3]):
                    print(f'  {i+1}. {pos["symbol"]}: ${pos["unrealized_pl"]:.2f} ({pos["unrealized_pct"]:+.2f}%)')
        
        return total_unrealized_pl, total_invested
    else:
        print('No active cycles with positions found.')
        return Decimal('0'), Decimal('0')

def get_cycle_counts():
    """Get counts of cycles by status"""
    status_query = '''
    SELECT 
        status,
        COUNT(*) as count
    FROM dca_cycles 
    GROUP BY status
    ORDER BY count DESC
    '''
    
    status_results = execute_query(status_query, fetch_all=True)
    return {row['status']: row['count'] for row in status_results} if status_results else {}

def main():
    """Main analysis function"""
    print('🤖 DCA TRADING BOT - P/L ANALYSIS')
    print('=' * 50)
    
    try:
        # Get cycle status counts
        cycle_counts = get_cycle_counts()
        
        # Analyze completed cycles
        realized_pl, completed_cycles = analyze_completed_cycles()
        
        # Analyze active cycles
        unrealized_pl, total_invested = analyze_active_cycles()
        
        # Overall summary
        print('\n\n=== 📊 OVERALL PORTFOLIO SUMMARY ===')
        total_pl = realized_pl + unrealized_pl
        print(f'💰 Realized P/L (Completed): ${realized_pl:.2f}')
        print(f'📈 Unrealized P/L (Active): ${unrealized_pl:.2f}')
        print(f'🎯 Total P/L: ${total_pl:.2f}')
        print(f'💵 Active Investment: ${total_invested:.2f}')
        
        print(f'\n=== 📋 CYCLE STATUS SUMMARY ===')
        for status, count in cycle_counts.items():
            print(f'{status.title()}: {count}')
        
        # Performance metrics
        if total_invested > 0:
            total_return_pct = (total_pl / total_invested * 100)
            print(f'\n🚀 Total Return: {total_return_pct:+.2f}%')
        
        if completed_cycles > 0:
            avg_per_cycle = realized_pl / completed_cycles
            print(f'📊 Average per Completed Cycle: ${avg_per_cycle:.2f}')
        
    except Exception as e:
        print(f'❌ Error running analysis: {e}')
        print('Make sure the DCA bot database is accessible and configured properly.')

if __name__ == '__main__':
    main() 