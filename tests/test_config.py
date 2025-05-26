#!/usr/bin/env python3
"""
Unit tests for the configuration module.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add src directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from config import Config, ConfigurationError, get_config


class TestConfig(unittest.TestCase):
    """Test cases for the Config class."""
    
    def setUp(self):
        """Set up test environment."""
        # Mock environment variables for testing
        self.test_env = {
            'APCA_API_KEY_ID': 'test_api_key',
            'APCA_API_SECRET_KEY': 'test_api_secret',
            'APCA_API_BASE_URL': 'https://paper-api.alpaca.markets',
            'DB_HOST': 'localhost',
            'DB_USER': 'test_user',
            'DB_PASSWORD': 'test_password',
            'DB_NAME': 'test_db',
            'DB_PORT': '3306',
            'ORDER_COOLDOWN_SECONDS': '10',
            'STALE_ORDER_THRESHOLD_MINUTES': '15',
            'TESTING_MODE': 'true',
            'DRY_RUN': 'false',
            'SMTP_SERVER': 'smtp.test.com',
            'SMTP_PORT': '587',
            'SMTP_USERNAME': 'test@test.com',
            'SMTP_PASSWORD': 'test_password',
            'ALERT_EMAIL_FROM': 'from@test.com',
            'ALERT_EMAIL_TO': 'to@test.com',
            'LOG_LEVEL': 'DEBUG',
            'LOG_DIR': 'test_logs',
            'LOG_MAX_BYTES': '5242880',
            'LOG_BACKUP_COUNT': '3'
        }
    
    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_dotenv')
    def test_missing_required_config_raises_error(self, mock_load_dotenv):
        """Test that missing required configuration raises ConfigurationError."""
        with self.assertRaises(ConfigurationError) as context:
            Config()
        
        self.assertIn("Missing required configuration", str(context.exception))
    
    @patch.dict(os.environ, {}, clear=True)
    @patch('config.load_dotenv')
    def test_partial_required_config_raises_error(self, mock_load_dotenv):
        """Test that partial required configuration raises ConfigurationError."""
        # Only provide some required variables
        partial_env = {
            'APCA_API_KEY_ID': 'test_key',
            'DB_HOST': 'localhost'
        }
        
        with patch.dict(os.environ, partial_env):
            with self.assertRaises(ConfigurationError) as context:
                Config()
            
            self.assertIn("Missing required configuration", str(context.exception))
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_valid_config_loads_successfully(self, mock_logger, mock_load_dotenv):
        """Test that valid configuration loads successfully."""
        with patch.dict(os.environ, self.test_env):
            config = Config()
            
            # Test required properties
            self.assertEqual(config.alpaca_api_key, 'test_api_key')
            self.assertEqual(config.alpaca_api_secret, 'test_api_secret')
            self.assertEqual(config.alpaca_base_url, 'https://paper-api.alpaca.markets')
            self.assertEqual(config.db_host, 'localhost')
            self.assertEqual(config.db_user, 'test_user')
            self.assertEqual(config.db_password, 'test_password')
            self.assertEqual(config.db_name, 'test_db')
            self.assertEqual(config.db_port, 3306)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_paper_trading_detection(self, mock_logger, mock_load_dotenv):
        """Test paper trading detection based on base URL."""
        # Test paper trading URL
        paper_env = self.test_env.copy()
        paper_env['APCA_API_BASE_URL'] = 'https://paper-api.alpaca.markets'
        
        with patch.dict(os.environ, paper_env):
            config = Config()
            self.assertTrue(config.is_paper_trading)
        
        # Test live trading URL
        live_env = self.test_env.copy()
        live_env['APCA_API_BASE_URL'] = 'https://api.alpaca.markets'
        
        with patch.dict(os.environ, live_env):
            config = Config()
            self.assertFalse(config.is_paper_trading)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_integer_config_parsing(self, mock_logger, mock_load_dotenv):
        """Test integer configuration parsing with defaults."""
        with patch.dict(os.environ, self.test_env):
            config = Config()
            
            self.assertEqual(config.order_cooldown_seconds, 10)
            self.assertEqual(config.stale_order_threshold_minutes, 15)
            self.assertEqual(config.smtp_port, 587)
            self.assertEqual(config.log_max_bytes, 5242880)
            self.assertEqual(config.log_backup_count, 3)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_integer_config_defaults(self, mock_logger, mock_load_dotenv):
        """Test integer configuration defaults when not provided."""
        # Remove integer configs from environment
        env_without_integers = {k: v for k, v in self.test_env.items() 
                               if k not in ['ORDER_COOLDOWN_SECONDS', 'STALE_ORDER_THRESHOLD_MINUTES', 
                                          'SMTP_PORT', 'LOG_MAX_BYTES', 'LOG_BACKUP_COUNT']}
        
        with patch.dict(os.environ, env_without_integers):
            config = Config()
            
            # Test defaults
            self.assertEqual(config.order_cooldown_seconds, 5)
            self.assertEqual(config.stale_order_threshold_minutes, 5)
            self.assertEqual(config.smtp_port, 587)
            self.assertEqual(config.log_max_bytes, 10 * 1024 * 1024)  # 10MB
            self.assertEqual(config.log_backup_count, 5)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_boolean_config_parsing(self, mock_logger, mock_load_dotenv):
        """Test boolean configuration parsing."""
        with patch.dict(os.environ, self.test_env):
            config = Config()
            
            self.assertTrue(config.testing_mode)  # 'true'
            self.assertFalse(config.dry_run_mode)  # 'false'
        
        # Test various boolean values
        bool_test_cases = [
            ('true', True), ('1', True), ('yes', True), ('on', True),
            ('false', False), ('0', False), ('no', False), ('off', False),
            ('invalid', False)  # Default to False for invalid values
        ]
        
        for value, expected in bool_test_cases:
            test_env = self.test_env.copy()
            test_env['TESTING_MODE'] = value
            
            with patch.dict(os.environ, test_env):
                config = Config()
                self.assertEqual(config.testing_mode, expected, f"Failed for value: {value}")
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_email_alerts_enabled(self, mock_logger, mock_load_dotenv):
        """Test email alerts enabled detection."""
        # Test with all email config present
        with patch.dict(os.environ, self.test_env, clear=True):
            config = Config()
            self.assertTrue(config.email_alerts_enabled)
        
        # Test with missing email config
        env_without_email = {k: v for k, v in self.test_env.items() 
                            if not k.startswith('SMTP_') and not k.startswith('ALERT_EMAIL_')}
        
        with patch.dict(os.environ, env_without_email, clear=True):
            config = Config()
            self.assertFalse(config.email_alerts_enabled)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_log_dir_creation(self, mock_logger, mock_load_dotenv):
        """Test that log directory is created."""
        with patch.dict(os.environ, self.test_env):
            with patch('pathlib.Path.mkdir') as mock_mkdir:
                config = Config()
                log_dir = config.log_dir
                
                # Verify mkdir was called (may be called multiple times due to property access)
                mock_mkdir.assert_called_with(exist_ok=True)
                self.assertEqual(str(log_dir), 'test_logs')
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_invalid_integer_uses_default(self, mock_logger, mock_load_dotenv):
        """Test that invalid integer values use defaults and log warnings."""
        invalid_env = self.test_env.copy()
        invalid_env['ORDER_COOLDOWN_SECONDS'] = 'invalid_number'
        
        with patch.dict(os.environ, invalid_env):
            config = Config()
            
            # Should use default value
            self.assertEqual(config.order_cooldown_seconds, 5)
            
            # Should have logged a warning
            mock_logger.warning.assert_called()
    
    def test_get_config_function(self):
        """Test the get_config convenience function."""
        # This should return the global config instance
        config_instance = get_config()
        self.assertIsInstance(config_instance, Config)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_convenience_functions(self, mock_logger, mock_load_dotenv):
        """Test convenience functions for backward compatibility."""
        from config import get_alpaca_credentials, get_db_credentials, get_email_config
        
        with patch.dict(os.environ, self.test_env):
            # Test Alpaca credentials
            key, secret, base_url = get_alpaca_credentials()
            self.assertEqual(key, 'test_api_key')
            self.assertEqual(secret, 'test_api_secret')
            self.assertEqual(base_url, 'https://paper-api.alpaca.markets')
            
            # Test DB credentials
            db_creds = get_db_credentials()
            expected_db_creds = {
                'host': 'localhost',
                'user': 'test_user',
                'password': 'test_password',
                'database': 'test_db',
                'port': 3306
            }
            self.assertEqual(db_creds, expected_db_creds)
            
            # Test email config
            email_config = get_email_config()
            expected_email_config = {
                'smtp_server': 'smtp.test.com',
                'smtp_port': '587',
                'smtp_username': 'test@test.com',
                'smtp_password': 'test_password',
                'from_email': 'from@test.com',
                'to_email': 'to@test.com'
            }
            self.assertEqual(email_config, expected_email_config)
    
    @patch('config.load_dotenv')
    @patch('config.logger')
    def test_email_config_disabled_when_incomplete(self, mock_logger, mock_load_dotenv):
        """Test that email config returns None when incomplete."""
        from config import get_email_config
        
        # Test with incomplete email config
        incomplete_env = {k: v for k, v in self.test_env.items() 
                         if k != 'SMTP_PASSWORD'}  # Missing password
        
        with patch.dict(os.environ, incomplete_env, clear=True):
            email_config = get_email_config()
            self.assertIsNone(email_config)


if __name__ == '__main__':
    unittest.main() 