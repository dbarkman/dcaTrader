#!/usr/bin/env python3
"""
DCA Trading Bot - Status Reporter

This caretaker script sends hourly status alerts to Discord with portfolio metrics:
- Total Realized P/L from completed cycles
- Total Amount Currently Invested in active cycles

Designed to be run via cron every hour.
"""

import sys
import os
import logging
from datetime import datetime, timezone
from decimal import Decimal

# Add src directory to path
script_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(os.path.dirname(script_dir), 'src')
sys.path.insert(0, src_dir)

from config import get_config
from utils.db_utils import execute_query
from utils.discord_notifications import discord_trading_alert

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

config = get_config()


def calculate_portfolio_metrics() -> dict:
    """
    Calculate total realized P/L and total current investment.
    
    Returns:
        dict: Portfolio metrics including realized_pl, total_investment, active_cycles, completed_cycles
    """
    try:
        # Calculate Total Realized P/L from completed cycles
        completed_query = """
        SELECT 
            COUNT(*) as completed_cycles,
            SUM(CASE WHEN c.sell_price IS NOT NULL AND c.average_purchase_price IS NOT NULL
                THEN c.quantity * (c.sell_price - c.average_purchase_price) 
                ELSE 0 END) as total_realized_pl
        FROM dca_cycles c
        WHERE c.status = 'complete' AND c.completed_at IS NOT NULL
        """
        
        completed_result = execute_query(completed_query, fetch_one=True)
        
        total_realized_pl = Decimal('0')
        completed_cycles = 0
        
        if completed_result and completed_result['completed_cycles'] > 0:
            completed_cycles = completed_result['completed_cycles']
            total_realized_pl = Decimal(str(completed_result['total_realized_pl'] or '0'))
        
        # Calculate Total Current Investment from active cycles
        active_query = """
        SELECT 
            COUNT(*) as active_cycles,
            SUM(c.quantity * c.average_purchase_price) as total_current_investment
        FROM dca_cycles c
        WHERE c.status NOT IN ('complete', 'error') 
        AND c.quantity > 0
        """
        
        active_result = execute_query(active_query, fetch_one=True)
        
        total_current_investment = Decimal('0')
        active_cycles = 0
        
        if active_result and active_result['active_cycles'] > 0:
            active_cycles = active_result['active_cycles']
            total_current_investment = Decimal(str(active_result['total_current_investment'] or '0'))
        
        # Calculate total historical investment from completed cycles
        historical_query = """
        SELECT 
            SUM(c.quantity * c.average_purchase_price) as total_historical_investment
        FROM dca_cycles c
        WHERE c.status = 'complete' AND c.completed_at IS NOT NULL
        """
        
        historical_result = execute_query(historical_query, fetch_one=True)
        total_historical_investment = Decimal(str(historical_result['total_historical_investment'] or '0')) if historical_result else Decimal('0')
        
        # Total amount invested = current active investment + historical completed investment
        total_amount_invested = total_current_investment + total_historical_investment
        
        return {
            'total_realized_pl': total_realized_pl,
            'total_current_investment': total_current_investment,
            'total_historical_investment': total_historical_investment,
            'total_amount_invested': total_amount_invested,
            'active_cycles': active_cycles,
            'completed_cycles': completed_cycles
        }
        
    except Exception as e:
        logger.error(f"Error calculating portfolio metrics: {e}")
        raise


def send_status_alert() -> bool:
    """
    Send hourly status alert to Discord with portfolio metrics.
    
    Returns:
        bool: True if alert sent successfully, False otherwise
    """
    try:
        logger.info("Calculating portfolio metrics for status report...")
        
        # Get portfolio metrics
        metrics = calculate_portfolio_metrics()
        
        # Format values for display
        realized_pl = metrics['total_realized_pl']
        total_invested = metrics['total_amount_invested']
        current_investment = metrics['total_current_investment']
        
        # Determine P/L status emoji and color
        pl_status = "📈" if realized_pl >= 0 else "📉"
        pl_display = f"${realized_pl:,.2f}" if realized_pl >= 1 else f"${realized_pl:.6f}"
        
        # Format investment amounts
        total_invested_display = f"${total_invested:,.2f}" if total_invested >= 1 else f"${total_invested:.6f}"
        current_invested_display = f"${current_investment:,.2f}" if current_investment >= 1 else f"${current_investment:.6f}"
        
        # Calculate ROI percentage if we have investment
        roi_display = "N/A"
        if metrics['total_historical_investment'] > 0:
            roi_percent = (realized_pl / metrics['total_historical_investment']) * 100
            roi_display = f"{roi_percent:+.2f}%"
        
        # Create status alert details
        status_details = {
            'Total Realized P/L': f"{pl_status} {pl_display}",
            'Currently Invested': current_invested_display,
            'Total Amount Invested': total_invested_display,
            'ROI': roi_display,
            'Active Cycles': metrics['active_cycles'],
            'Completed Cycles': metrics['completed_cycles']
        }
        
        # Log the metrics
        logger.info(f"Portfolio Status - Realized P/L: {pl_display}, Total Invested: {total_invested_display}")
        
        # Send Discord alert (without user mention - just notification)
        success = discord_trading_alert(
            asset_symbol="PORTFOLIO",
            event_type="HOURLY STATUS REPORT",
            details=status_details,
            priority="normal"  # Normal priority = no user mention
        )
        
        if success:
            logger.info("✅ Hourly status alert sent successfully")
        else:
            logger.warning("❌ Failed to send hourly status alert")
        
        return success
        
    except Exception as e:
        logger.error(f"Error sending status alert: {e}")
        return False


def run_status_report():
    """
    Main function to run the status report.
    """
    try:
        logger.info("=== DCA Trading Bot - Hourly Status Report ===")
        
        # Check if Discord notifications are enabled
        if not config.discord_notifications_enabled:
            logger.info("Discord notifications not enabled, skipping status report")
            return True
        
        if not config.discord_trading_alerts_enabled:
            logger.info("Discord trading alerts not enabled, skipping status report")
            return True
        
        # Send status alert
        success = send_status_alert()
        
        if success:
            logger.info("Status report completed successfully")
            return True
        else:
            logger.error("Status report failed")
            return False
        
    except Exception as e:
        logger.error(f"Error in status report: {e}")
        return False


def main():
    """
    Entry point for the status reporter script.
    """
    try:
        success = run_status_report()
        sys.exit(0 if success else 1)
        
    except KeyboardInterrupt:
        logger.info("Status reporter interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error in status reporter: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main() 