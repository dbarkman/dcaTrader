#!/usr/bin/env python3
"""
DCA Trading Bot - Notifications Utility

This module provides reusable notification functionality for the DCA trading bot.
Currently supports email notifications with SMTP, with graceful error handling
and proper configuration management.

Features:
- Email notifications via SMTP
- Template-based messaging
- Graceful error handling
- Configuration validation
- Rate limiting to prevent spam
- HTML and plain text support
"""

import smtplib
import email.message
import email.utils
import logging
import time
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import get_config

config = get_config()
logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Raised when notification sending fails."""
    pass


class EmailRateLimiter:
    """Simple rate limiter to prevent email spam."""
    
    def __init__(self, max_emails_per_hour: int = 10):
        """
        Initialize rate limiter.
        
        Args:
            max_emails_per_hour: Maximum emails to send per hour
        """
        self.max_emails_per_hour = max_emails_per_hour
        self.email_timestamps = []
    
    def can_send_email(self) -> bool:
        """Check if we can send an email without exceeding rate limit."""
        now = datetime.now()
        one_hour_ago = now - timedelta(hours=1)
        
        # Remove timestamps older than 1 hour
        self.email_timestamps = [ts for ts in self.email_timestamps if ts > one_hour_ago]
        
        return len(self.email_timestamps) < self.max_emails_per_hour
    
    def record_email_sent(self) -> None:
        """Record that an email was sent."""
        self.email_timestamps.append(datetime.now())


# Global rate limiter instance
_rate_limiter = EmailRateLimiter()


def send_email_alert(
    subject: str,
    body: str,
    html_body: Optional[str] = None,
    priority: str = "normal",
    bypass_rate_limit: bool = False
) -> bool:
    """
    Send an email alert using SMTP configuration.
    
    Args:
        subject: Email subject line
        body: Plain text email body
        html_body: Optional HTML email body
        priority: Email priority ('low', 'normal', 'high', 'critical')
        bypass_rate_limit: If True, bypass rate limiting (use for critical alerts)
    
    Returns:
        True if email was sent successfully, False otherwise
    
    Example:
        >>> success = send_email_alert(
        ...     "DCA Bot Alert",
        ...     "Base order placed for BTC/USD",
        ...     priority="normal"
        ... )
    """
    try:
        # Check if email alerts are configured
        if not config.email_alerts_enabled:
            logger.debug("Email alerts not configured, skipping notification")
            return False
        
        # Check rate limiting (unless bypassed for critical alerts)
        if not bypass_rate_limit and not _rate_limiter.can_send_email():
            logger.warning("Email rate limit exceeded, skipping notification")
            return False
        
        # Prepare subject with priority indicator
        priority_prefix = {
            'low': '',
            'normal': '',
            'high': '[HIGH] ',
            'critical': '[CRITICAL] '
        }.get(priority.lower(), '')
        
        full_subject = f"{priority_prefix}[DCA Bot] {subject}"
        
        # Create message
        if html_body:
            msg = MIMEMultipart('alternative')
            msg.attach(MIMEText(body, 'plain'))
            msg.attach(MIMEText(html_body, 'html'))
        else:
            msg = MIMEText(body, 'plain')
        
        msg['Subject'] = full_subject
        msg['From'] = config.alert_email_from
        msg['To'] = config.alert_email_to
        msg['Date'] = email.utils.formatdate(localtime=True)
        
        # Add metadata
        msg['X-DCA-Bot-Priority'] = priority
        msg['X-DCA-Bot-Timestamp'] = datetime.utcnow().isoformat()
        
        # Send email
        with smtplib.SMTP(config.smtp_server, config.smtp_port) as server:
            server.starttls()
            server.login(config.smtp_username, config.smtp_password)
            server.send_message(msg)
        
        # Record successful send
        if not bypass_rate_limit:
            _rate_limiter.record_email_sent()
        
        logger.info(f"Email alert sent successfully: {subject}")
        return True
        
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        return False
    except smtplib.SMTPRecipientsRefused as e:
        logger.error(f"SMTP recipients refused: {e}")
        return False
    except smtplib.SMTPServerDisconnected as e:
        logger.error(f"SMTP server disconnected: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending email alert: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email alert: {e}")
        return False


def send_trading_alert(
    asset_symbol: str,
    event_type: str,
    details: Dict[str, Any],
    priority: str = "normal"
) -> bool:
    """
    Send a trading-specific alert with standardized formatting.
    
    Args:
        asset_symbol: Trading pair symbol (e.g., 'BTC/USD')
        event_type: Type of trading event
        details: Dictionary of event details
        priority: Alert priority level
    
    Returns:
        True if alert was sent successfully, False otherwise
    """
    # Create formatted subject and body
    subject = f"{event_type} - {asset_symbol}"
    
    body_lines = [
        f"DCA Trading Bot Alert",
        f"",
        f"Asset: {asset_symbol}",
        f"Event: {event_type}",
        f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"",
        f"Details:"
    ]
    
    for key, value in details.items():
        body_lines.append(f"  {key}: {value}")
    
    body_lines.extend([
        f"",
        f"This is an automated message from the DCA Trading Bot.",
        f"Server: {config.db_host}",
        f"Trading Mode: {'Paper Trading' if config.is_paper_trading else 'LIVE TRADING'}"
    ])
    
    body = "\n".join(body_lines)
    
    return send_email_alert(subject, body, priority=priority)


def send_system_alert(
    component: str,
    message: str,
    error_details: Optional[str] = None,
    priority: str = "high"
) -> bool:
    """
    Send a system-level alert (errors, warnings, status changes).
    
    Args:
        component: System component name (e.g., 'watchdog', 'main_app')
        message: Alert message
        error_details: Optional error details or stack trace
        priority: Alert priority level
    
    Returns:
        True if alert was sent successfully, False otherwise
    """
    subject = f"System Alert - {component}"
    
    body_lines = [
        f"DCA Trading Bot System Alert",
        f"",
        f"Component: {component}",
        f"Message: {message}",
        f"Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
        f"Priority: {priority.upper()}",
        f""
    ]
    
    if error_details:
        body_lines.extend([
            f"Error Details:",
            f"{error_details}",
            f""
        ])
    
    body_lines.extend([
        f"System Information:",
        f"  Server: {config.db_host}",
        f"  Trading Mode: {'Paper Trading' if config.is_paper_trading else 'LIVE TRADING'}",
        f"  Dry Run: {config.dry_run_mode}",
        f"",
        f"This is an automated message from the DCA Trading Bot."
    ])
    
    body = "\n".join(body_lines)
    
    # Critical system alerts bypass rate limiting
    bypass_rate_limit = priority.lower() == 'critical'
    
    return send_email_alert(subject, body, priority=priority, bypass_rate_limit=bypass_rate_limit)


def send_daily_summary(summary_data: Dict[str, Any]) -> bool:
    """
    Send a daily summary email with trading activity.
    
    Args:
        summary_data: Dictionary containing daily summary information
    
    Returns:
        True if summary was sent successfully, False otherwise
    """
    subject = f"Daily Summary - {datetime.now().strftime('%Y-%m-%d')}"
    
    body_lines = [
        f"DCA Trading Bot Daily Summary",
        f"Date: {datetime.now().strftime('%Y-%m-%d')}",
        f"",
        f"Trading Activity:"
    ]
    
    # Add summary data
    for key, value in summary_data.items():
        body_lines.append(f"  {key}: {value}")
    
    body_lines.extend([
        f"",
        f"System Status:",
        f"  Trading Mode: {'Paper Trading' if config.is_paper_trading else 'LIVE TRADING'}",
        f"  Email Alerts: {'Enabled' if config.email_alerts_enabled else 'Disabled'}",
        f"  Dry Run Mode: {config.dry_run_mode}",
        f"",
        f"This is an automated daily summary from the DCA Trading Bot."
    ])
    
    body = "\n".join(body_lines)
    
    return send_email_alert(subject, body, priority="low")


def verify_email_configuration() -> bool:
    """
    Verify email configuration by sending a test message.
    
    Returns:
        True if test email was sent successfully, False otherwise
    """
    if not config.email_alerts_enabled:
        logger.warning("Email alerts not configured, cannot send test email")
        return False
    
    subject = "Test Email - Configuration Verification"
    body = f"""
DCA Trading Bot Email Configuration Test

This is a test email to verify that email notifications are working correctly.

Configuration:
  SMTP Server: {config.smtp_server}
  SMTP Port: {config.smtp_port}
  From: {config.alert_email_from}
  To: {config.alert_email_to}

Timestamp: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}

If you received this email, your email configuration is working correctly.
"""
    
    success = send_email_alert(subject, body, priority="low", bypass_rate_limit=True)
    
    if success:
        logger.info("Test email sent successfully")
    else:
        logger.error("Failed to send test email")
    
    return success


# Convenience functions for common alert types
def alert_order_placed(asset_symbol: str, order_type: str, order_id: str, quantity: float, price: float) -> bool:
    """Send alert for order placement."""
    return send_trading_alert(
        asset_symbol,
        f"{order_type.upper()} ORDER PLACED",
        {
            'Order ID': order_id,
            'Quantity': f"{quantity:.8f}",
            'Price': f"${price:,.2f}",
            'Total Value': f"${quantity * price:,.2f}"
        }
    )


def alert_order_filled(asset_symbol: str, order_type: str, order_id: str, fill_price: float, quantity: float) -> bool:
    """Send alert for order fill."""
    return send_trading_alert(
        asset_symbol,
        f"{order_type.upper()} ORDER FILLED",
        {
            'Order ID': order_id,
            'Fill Price': f"${fill_price:,.2f}",
            'Quantity': f"{quantity:.8f}",
            'Total Value': f"${quantity * fill_price:,.2f}"
        }
    )


def alert_cycle_completed(asset_symbol: str, profit: float, profit_percent: float) -> bool:
    """Send alert for completed trading cycle."""
    return send_trading_alert(
        asset_symbol,
        "CYCLE COMPLETED",
        {
            'Profit': f"${profit:,.2f}",
            'Profit Percentage': f"{profit_percent:.2f}%",
            'Status': 'Profitable' if profit > 0 else 'Loss'
        },
        priority="normal"
    )


def alert_system_error(component: str, error_message: str, error_details: Optional[str] = None) -> bool:
    """Send alert for system errors."""
    return send_system_alert(
        component,
        f"Error: {error_message}",
        error_details,
        priority="high"
    )


def alert_critical_error(component: str, error_message: str, error_details: Optional[str] = None) -> bool:
    """Send alert for critical system errors."""
    return send_system_alert(
        component,
        f"CRITICAL ERROR: {error_message}",
        error_details,
        priority="critical"
    ) 