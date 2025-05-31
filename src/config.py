#!/usr/bin/env python3
"""
DCA Trading Bot - Configuration Management

This module provides centralized configuration loading from environment variables
with proper validation, type conversion, and defaults. All other modules should
import configuration from here rather than using os.getenv directly.

Features:
- Type-safe configuration loading
- Validation of required settings
- Sensible defaults for optional settings
- Clear error messages for missing configuration
- Support for different environments (paper/live trading)
"""

import os
import logging
from typing import Optional, Union
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)


class ConfigurationError(Exception):
    """Raised when configuration is invalid or missing."""
    pass


class Config:
    """Centralized configuration management for the DCA Trading Bot."""
    
    def __init__(self):
        """Initialize configuration and validate required settings."""
        self._validate_required_settings()
        self._log_configuration_summary()
    
    # =============================================================================
    # ALPACA API CONFIGURATION
    # =============================================================================
    
    @property
    def alpaca_api_key(self) -> str:
        """Alpaca API Key ID."""
        return self._get_required_env('APCA_API_KEY_ID')
    
    @property
    def alpaca_api_secret(self) -> str:
        """Alpaca API Secret Key."""
        return self._get_required_env('APCA_API_SECRET_KEY')
    
    @property
    def alpaca_base_url(self) -> str:
        """Alpaca API Base URL (paper or live trading)."""
        return os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    
    @property
    def is_paper_trading(self) -> bool:
        """True if using paper trading, False for live trading."""
        return 'paper-api' in self.alpaca_base_url.lower()
    
    # =============================================================================
    # DATABASE CONFIGURATION
    # =============================================================================
    
    @property
    def db_host(self) -> str:
        """Database host."""
        return self._get_required_env('DB_HOST')
    
    @property
    def db_user(self) -> str:
        """Database username."""
        return self._get_required_env('DB_USER')
    
    @property
    def db_password(self) -> str:
        """Database password."""
        return self._get_required_env('DB_PASSWORD')
    
    @property
    def db_name(self) -> str:
        """Database name."""
        return self._get_required_env('DB_NAME')
    
    @property
    def db_port(self) -> int:
        """Database port."""
        return self._get_int_env('DB_PORT', 3306)
    
    # =============================================================================
    # ORDER MANAGEMENT CONFIGURATION
    # =============================================================================
    
    @property
    def order_cooldown_seconds(self) -> int:
        """Cooldown period between orders to prevent duplicates."""
        return self._get_int_env('ORDER_COOLDOWN_SECONDS', 5)
    
    @property
    def stale_order_threshold_minutes(self) -> int:
        """Minutes after which an order is considered stale."""
        return self._get_int_env('STALE_ORDER_THRESHOLD_MINUTES', 5)
    
    @property
    def testing_mode(self) -> bool:
        """Enable testing mode with aggressive pricing."""
        return self._get_bool_env('TESTING_MODE', False)
    
    @property
    def dry_run_mode(self) -> bool:
        """Enable dry run mode (no actual orders placed)."""
        return self._get_bool_env('DRY_RUN', False)
    
    # =============================================================================
    # EMAIL ALERT CONFIGURATION
    # =============================================================================
    
    @property
    def smtp_server(self) -> Optional[str]:
        """SMTP server for email alerts."""
        return os.getenv('SMTP_SERVER')
    
    @property
    def smtp_port(self) -> int:
        """SMTP port for email alerts."""
        return self._get_int_env('SMTP_PORT', 587)
    
    @property
    def smtp_username(self) -> Optional[str]:
        """SMTP username for email alerts."""
        return os.getenv('SMTP_USERNAME')
    
    @property
    def smtp_password(self) -> Optional[str]:
        """SMTP password for email alerts."""
        return os.getenv('SMTP_PASSWORD')
    
    @property
    def alert_email_from(self) -> Optional[str]:
        """From email address for alerts."""
        return os.getenv('ALERT_EMAIL_FROM')
    
    @property
    def alert_email_to(self) -> Optional[str]:
        """To email address for alerts."""
        return os.getenv('ALERT_EMAIL_TO')
    
    @property
    def email_alerts_enabled(self) -> bool:
        """True if email alerts are properly configured."""
        return all([
            self.smtp_server,
            self.smtp_username,
            self.smtp_password,
            self.alert_email_from,
            self.alert_email_to
        ])
    
    @property
    def trading_alerts_enabled(self) -> bool:
        """True if trading alerts should be sent (separate from system alerts)."""
        return self._get_bool_env('TRADING_ALERTS_ENABLED', True)
    
    # =============================================================================
    # DISCORD WEBHOOK CONFIGURATION
    # =============================================================================
    
    @property
    def discord_webhook_url(self) -> Optional[str]:
        """Discord webhook URL for notifications."""
        return os.getenv('DISCORD_WEBHOOK_URL')
    
    @property
    def discord_user_id(self) -> Optional[str]:
        """Discord user ID for mentions (optional)."""
        return os.getenv('DISCORD_USER_ID')
    
    @property
    def discord_notifications_enabled(self) -> bool:
        """True if Discord notifications are enabled and configured."""
        return bool(self.discord_webhook_url and self._get_bool_env('DISCORD_NOTIFICATIONS_ENABLED', False))
    
    @property
    def discord_trading_alerts_enabled(self) -> bool:
        """True if Discord trading alerts should be sent (separate from system alerts)."""
        return self.discord_notifications_enabled and self._get_bool_env('DISCORD_TRADING_ALERTS_ENABLED', True)
    
    # =============================================================================
    # LOGGING CONFIGURATION
    # =============================================================================
    
    @property
    def log_level(self) -> str:
        """Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)."""
        return os.getenv('LOG_LEVEL', 'INFO').upper()
    
    @property
    def log_dir(self) -> Path:
        """Directory for log files."""
        log_dir = Path(os.getenv('LOG_DIR', 'logs'))
        log_dir.mkdir(exist_ok=True)
        return log_dir
    
    @property
    def log_max_bytes(self) -> int:
        """Maximum size of log files before rotation."""
        return self._get_int_env('LOG_MAX_BYTES', 10 * 1024 * 1024)  # 10MB default
    
    @property
    def log_backup_count(self) -> int:
        """Number of backup log files to keep."""
        return self._get_int_env('LOG_BACKUP_COUNT', 5)
    
    # =============================================================================
    # HELPER METHODS
    # =============================================================================
    
    def _get_required_env(self, key: str) -> str:
        """Get a required environment variable or raise ConfigurationError."""
        value = os.getenv(key)
        if not value:
            raise ConfigurationError(f"Required environment variable '{key}' is not set")
        return value
    
    def _get_int_env(self, key: str, default: int) -> int:
        """Get an integer environment variable with default."""
        value = os.getenv(key)
        if not value:
            return default
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid integer value for {key}: '{value}', using default: {default}")
            return default
    
    def _get_bool_env(self, key: str, default: bool) -> bool:
        """Get a boolean environment variable with default."""
        value = os.getenv(key, '').lower()
        if value in ('true', '1', 'yes', 'on'):
            return True
        elif value in ('false', '0', 'no', 'off'):
            return False
        else:
            return default
    
    def _validate_required_settings(self) -> None:
        """Validate that all required configuration is present."""
        required_settings = [
            'alpaca_api_key',
            'alpaca_api_secret',
            'db_host',
            'db_user',
            'db_password',
            'db_name'
        ]
        
        missing_settings = []
        for setting in required_settings:
            try:
                getattr(self, setting)
            except ConfigurationError:
                missing_settings.append(setting)
        
        if missing_settings:
            raise ConfigurationError(
                f"Missing required configuration: {', '.join(missing_settings)}. "
                f"Please check your .env file or environment variables."
            )
    
    def _log_configuration_summary(self) -> None:
        """Log a summary of the current configuration (without sensitive data)."""
        logger.info("=== DCA Trading Bot Configuration ===")
        logger.info(f"Trading Mode: {'Paper Trading' if self.is_paper_trading else 'LIVE TRADING'}")
        logger.info(f"Database: {self.db_user}@{self.db_host}:{self.db_port}/{self.db_name}")
        logger.info(f"Order Cooldown: {self.order_cooldown_seconds}s")
        logger.info(f"Stale Order Threshold: {self.stale_order_threshold_minutes}m")
        logger.info(f"Testing Mode: {self.testing_mode}")
        logger.info(f"Dry Run Mode: {self.dry_run_mode}")
        logger.info(f"Email Alerts: {'Enabled' if self.email_alerts_enabled else 'Disabled'}")
        logger.info(f"Discord Alerts: {'Enabled' if self.discord_notifications_enabled else 'Disabled'}")
        logger.info(f"Log Level: {self.log_level}")
        logger.info(f"Log Directory: {self.log_dir}")
        logger.info("======================================")


# Global configuration instance
config = Config()


def get_config() -> Config:
    """Get the global configuration instance."""
    return config


# Convenience functions for backward compatibility
def get_alpaca_credentials() -> tuple[str, str, str]:
    """Get Alpaca API credentials (key, secret, base_url)."""
    return config.alpaca_api_key, config.alpaca_api_secret, config.alpaca_base_url


def get_db_credentials() -> dict[str, Union[str, int]]:
    """Get database connection parameters."""
    return {
        'host': config.db_host,
        'user': config.db_user,
        'password': config.db_password,
        'database': config.db_name,
        'port': config.db_port
    }


def get_email_config() -> Optional[dict[str, str]]:
    """Get email configuration if enabled, None otherwise."""
    if not config.email_alerts_enabled:
        return None
    
    return {
        'smtp_server': config.smtp_server,
        'smtp_port': str(config.smtp_port),
        'smtp_username': config.smtp_username,
        'smtp_password': config.smtp_password,
        'from_email': config.alert_email_from,
        'to_email': config.alert_email_to
    } 