#!/usr/bin/env python3
"""
Unit tests for the notifications module.
"""

import unittest
from unittest.mock import patch, MagicMock, call
import smtplib
import os
import sys
from datetime import datetime, timedelta

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from utils.notifications import (
    send_email_alert, send_trading_alert, send_system_alert, 
    verify_email_configuration, EmailRateLimiter,
    alert_order_placed, alert_order_filled, alert_cycle_completed,
    alert_system_error, alert_critical_error
)


class TestEmailRateLimiter(unittest.TestCase):
    """Test cases for the EmailRateLimiter class."""
    
    def test_rate_limiter_allows_initial_emails(self):
        """Test that rate limiter allows initial emails."""
        limiter = EmailRateLimiter(max_emails_per_hour=5)
        
        # Should allow first few emails
        for i in range(5):
            self.assertTrue(limiter.can_send_email())
            limiter.record_email_sent()
        
        # Should block the 6th email
        self.assertFalse(limiter.can_send_email())
    
    def test_rate_limiter_resets_after_time(self):
        """Test that rate limiter resets after time passes."""
        limiter = EmailRateLimiter(max_emails_per_hour=2)
        
        # Send max emails
        limiter.record_email_sent()
        limiter.record_email_sent()
        self.assertFalse(limiter.can_send_email())
        
        # Mock time passing (more than 1 hour)
        with patch('utils.notifications.datetime') as mock_datetime:
            future_time = datetime.now() + timedelta(hours=2)
            mock_datetime.now.return_value = future_time
            
            # Should allow emails again
            self.assertTrue(limiter.can_send_email())


class TestEmailAlerts(unittest.TestCase):
    """Test cases for email alert functions."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock configuration
        self.mock_config = MagicMock()
        self.mock_config.email_alerts_enabled = True
        self.mock_config.smtp_server = 'smtp.test.com'
        self.mock_config.smtp_port = 587
        self.mock_config.smtp_username = 'test@test.com'
        self.mock_config.smtp_password = 'test_password'
        self.mock_config.alert_email_from = 'from@test.com'
        self.mock_config.alert_email_to = 'to@test.com'
        self.mock_config.db_host = 'test_host'
        self.mock_config.is_paper_trading = True
        self.mock_config.dry_run_mode = False
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._rate_limiter')
    @patch('utils.notifications.smtplib.SMTP')
    def test_send_email_alert_success(self, mock_smtp, mock_rate_limiter, mock_config):
        """Test successful email alert sending."""
        mock_config.email_alerts_enabled = True
        mock_rate_limiter.can_send_email.return_value = True
        
        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        result = send_email_alert("Test Subject", "Test Body")
        
        self.assertTrue(result)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()
        mock_rate_limiter.record_email_sent.assert_called_once()
    
    @patch('utils.notifications.config')
    def test_send_email_alert_disabled(self, mock_config):
        """Test email alert when alerts are disabled."""
        mock_config.email_alerts_enabled = False
        
        result = send_email_alert("Test Subject", "Test Body")
        
        self.assertFalse(result)
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._rate_limiter')
    def test_send_email_alert_rate_limited(self, mock_rate_limiter, mock_config):
        """Test email alert when rate limited."""
        mock_config.email_alerts_enabled = True
        mock_rate_limiter.can_send_email.return_value = False
        
        result = send_email_alert("Test Subject", "Test Body")
        
        self.assertFalse(result)
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._rate_limiter')
    @patch('utils.notifications.smtplib.SMTP')
    def test_send_email_alert_smtp_auth_error(self, mock_smtp, mock_rate_limiter, mock_config):
        """Test email alert with SMTP authentication error."""
        mock_config.email_alerts_enabled = True
        mock_rate_limiter.can_send_email.return_value = True
        
        # Mock SMTP authentication error
        mock_server = MagicMock()
        mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, "Authentication failed")
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        result = send_email_alert("Test Subject", "Test Body")
        
        self.assertFalse(result)
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._rate_limiter')
    @patch('utils.notifications.smtplib.SMTP')
    def test_send_email_alert_smtp_recipients_refused(self, mock_smtp, mock_rate_limiter, mock_config):
        """Test email alert with SMTP recipients refused error."""
        mock_config.email_alerts_enabled = True
        mock_rate_limiter.can_send_email.return_value = True
        
        # Mock SMTP recipients refused error
        mock_server = MagicMock()
        mock_server.send_message.side_effect = smtplib.SMTPRecipientsRefused({})
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        result = send_email_alert("Test Subject", "Test Body")
        
        self.assertFalse(result)
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._rate_limiter')
    @patch('utils.notifications.smtplib.SMTP')
    def test_send_email_alert_bypass_rate_limit(self, mock_smtp, mock_rate_limiter, mock_config):
        """Test email alert bypassing rate limit for critical alerts."""
        mock_config.email_alerts_enabled = True
        mock_rate_limiter.can_send_email.return_value = False  # Rate limited
        
        # Mock SMTP server
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        
        # Should succeed when bypassing rate limit
        result = send_email_alert("Critical Alert", "Critical Body", bypass_rate_limit=True)
        
        self.assertTrue(result)
        mock_server.send_message.assert_called_once()
        # Should not record email sent when bypassing rate limit
        mock_rate_limiter.record_email_sent.assert_not_called()
    
    @patch('utils.notifications.config')
    @patch('utils.notifications.send_email_alert')
    def test_send_trading_alert(self, mock_send_email, mock_config):
        """Test trading alert formatting."""
        mock_config.trading_alerts_enabled = True
        mock_send_email.return_value = True
        
        result = send_trading_alert(
            "BTC/USD",
            "BASE_ORDER_PLACED",
            {"order_id": "123", "quantity": "0.001", "price": "$50000"},
            priority="normal"
        )
        
        self.assertTrue(result)
        mock_send_email.assert_called_once()
        
        # Check the call arguments
        call_args = mock_send_email.call_args
        subject = call_args[0][0]
        body = call_args[0][1]
        
        self.assertEqual(subject, "BASE_ORDER_PLACED - BTC/USD")
        self.assertIn("BTC/USD", body)
        self.assertIn("BASE_ORDER_PLACED", body)
        self.assertIn("order_id: 123", body)
    
    @patch('utils.notifications._is_test_mode')
    @patch('utils.notifications.send_email_alert')
    def test_send_system_alert(self, mock_send_email, mock_is_test_mode):
        """Test system alert formatting."""
        mock_is_test_mode.return_value = False  # Disable test mode for this test
        mock_send_email.return_value = True
        
        result = send_system_alert(
            "main_app",
            "Application started",
            error_details="Stack trace here",
            priority="high"
        )
        
        self.assertTrue(result)
        mock_send_email.assert_called_once()
        
        # Check the call arguments
        call_args = mock_send_email.call_args
        subject = call_args[0][0]
        body = call_args[0][1]
        
        self.assertEqual(subject, "System Alert - main_app")
        self.assertIn("main_app", body)
        self.assertIn("Application started", body)
        self.assertIn("Stack trace here", body)
    
    @patch('utils.notifications._is_test_mode')
    @patch('utils.notifications.send_email_alert')
    def test_critical_system_alert_bypasses_rate_limit(self, mock_send_email, mock_is_test_mode):
        """Test that critical system alerts bypass rate limiting."""
        mock_is_test_mode.return_value = False  # Disable test mode for this test
        mock_send_email.return_value = True
        
        send_system_alert(
            "main_app",
            "Critical error",
            priority="critical"
        )
        
        # Check that bypass_rate_limit=True was passed
        call_args = mock_send_email.call_args
        kwargs = call_args[1]
        self.assertTrue(kwargs.get('bypass_rate_limit', False))
    
    @patch('utils.notifications.config')
    @patch('utils.notifications.send_email_alert')
    def test_test_email_configuration_success(self, mock_send_email, mock_config):
        """Test email configuration test when successful."""
        mock_config.email_alerts_enabled = True
        mock_send_email.return_value = True
        
        result = verify_email_configuration()
        
        self.assertTrue(result)
        mock_send_email.assert_called_once()
        
        # Check that it was called with bypass_rate_limit=True
        call_args = mock_send_email.call_args
        kwargs = call_args[1]
        self.assertTrue(kwargs.get('bypass_rate_limit', False))
    
    @patch('utils.notifications.config')
    def test_test_email_configuration_disabled(self, mock_config):
        """Test email configuration test when disabled."""
        mock_config.email_alerts_enabled = False
        
        result = verify_email_configuration()
        
        self.assertFalse(result)
    
    @patch('utils.notifications.config')
    @patch('utils.notifications._is_test_mode')
    @patch('utils.notifications.send_trading_alert')
    def test_convenience_alert_functions(self, mock_send_trading, mock_is_test_mode, mock_config):
        """Test convenience alert functions."""
        mock_is_test_mode.return_value = False  # Disable test mode for this test
        mock_config.trading_alerts_enabled = True
        mock_send_trading.return_value = True
        
        # Test order placed alert
        result = alert_order_placed("BTC/USD", "BASE", "order123", 0.001, 50000)
        self.assertTrue(result)
        
        # Test order filled alert
        result = alert_order_filled("BTC/USD", "BASE", "order123", 50000, 0.001)
        self.assertTrue(result)
        
        # Test cycle completed alert
        result = alert_cycle_completed("BTC/USD", 100.0, 2.5)
        self.assertTrue(result)
        
        # Verify calls were made
        self.assertEqual(mock_send_trading.call_count, 3)
    
    @patch('utils.notifications._is_test_mode')
    @patch('utils.notifications.send_system_alert')
    def test_convenience_system_alert_functions(self, mock_send_system, mock_is_test_mode):
        """Test convenience system alert functions."""
        mock_is_test_mode.return_value = False  # Disable test mode for this test
        mock_send_system.return_value = True
        
        # Test system error alert
        result = alert_system_error("main_app", "Database connection failed", "Error details")
        self.assertTrue(result)
        
        # Test critical error alert
        result = alert_critical_error("main_app", "Application crashed", "Stack trace")
        self.assertTrue(result)
        
        # Verify calls were made with correct priorities
        calls = mock_send_system.call_args_list
        self.assertEqual(len(calls), 2)
        
        # First call should be high priority
        self.assertEqual(calls[0][1]['priority'], 'high')
        
        # Second call should be critical priority
        self.assertEqual(calls[1][1]['priority'], 'critical')


if __name__ == '__main__':
    unittest.main() 