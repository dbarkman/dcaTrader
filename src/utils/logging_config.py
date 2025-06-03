#!/usr/bin/env python3
"""
DCA Trading Bot - Logging Configuration

This module provides comprehensive, structured logging configuration for the entire
application. It includes special formatting for asset lifecycle tracking and
proper log rotation.

Features:
- Structured logging with consistent formatting
- Asset lifecycle tracking (easy to grep by trading pair)
- Rotating file handlers with size limits
- Console and file output
- Proper log levels and filtering
- Performance-conscious logging
"""

import logging
import logging.handlers
import sys
import gzip
import shutil
from pathlib import Path
from typing import Optional
from datetime import datetime

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config import get_config

config = get_config()


class GzipTimedRotatingFileHandler(logging.handlers.TimedRotatingFileHandler):
    """
    Custom TimedRotatingFileHandler that automatically gzips rotated log files.
    
    This handler extends the standard TimedRotatingFileHandler to compress
    old log files with gzip, saving disk space for archived logs.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Set up custom namer and rotator for gzipping
        self.namer = self._gzip_namer
        self.rotator = self._gzip_rotator
    
    def _gzip_namer(self, default_name: str) -> str:
        """
        Custom namer that adds .gz extension to rotated files.
        
        Args:
            default_name: The default name that would be used
            
        Returns:
            The name with .gz extension added
        """
        return default_name + ".gz"
    
    def _gzip_rotator(self, source: str, dest: str) -> None:
        """
        Custom rotator that gzips the rotated file.
        
        Args:
            source: Path to the source file to be rotated
            dest: Path to the destination (should end with .gz)
        """
        try:
            with open(source, 'rb') as f_in:
                with gzip.open(dest, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            # Remove the original uncompressed file
            Path(source).unlink()
        except Exception as e:
            # If gzipping fails, fall back to regular rotation
            shutil.move(source, dest.replace('.gz', ''))
            print(f"Warning: Failed to gzip {source}: {e}")


class AssetLifecycleFormatter(logging.Formatter):
    """
    Custom formatter that enhances log messages with asset context for lifecycle tracking.
    
    This formatter ensures that all asset-related operations include the trading pair
    in a consistent format, making it easy to grep logs for specific assets.
    """
    
    def __init__(self, include_asset_prefix: bool = True):
        """
        Initialize the formatter.
        
        Args:
            include_asset_prefix: If True, adds [ASSET:symbol] prefix to asset-related logs
        """
        # Enhanced format with module name and function for better debugging
        fmt = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        super().__init__(fmt, datefmt='%Y-%m-%d %H:%M:%S')
        self.include_asset_prefix = include_asset_prefix
    
    def format(self, record: logging.LogRecord) -> str:
        """Format the log record with asset context if available."""
        # Check if the record has asset context
        asset_symbol = getattr(record, 'asset_symbol', None)
        
        if asset_symbol and self.include_asset_prefix:
            # Add asset prefix to the message for easy grepping
            original_msg = record.getMessage()
            record.msg = f"[ASSET:{asset_symbol}] {original_msg}"
            record.args = ()  # Clear args since we've already formatted the message
        
        return super().format(record)


class AssetContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that automatically adds asset context to log records.
    
    This adapter makes it easy to create asset-specific loggers that automatically
    include the trading pair in all log messages.
    """
    
    def __init__(self, logger: logging.Logger, asset_symbol: str):
        """
        Initialize the adapter.
        
        Args:
            logger: The base logger to adapt
            asset_symbol: The trading pair symbol (e.g., 'BTC/USD')
        """
        super().__init__(logger, {'asset_symbol': asset_symbol})
        self.asset_symbol = asset_symbol
    
    def process(self, msg, kwargs):
        """Process the log record to add asset context."""
        # Add asset_symbol to the LogRecord
        if 'extra' not in kwargs:
            kwargs['extra'] = {}
        kwargs['extra']['asset_symbol'] = self.asset_symbol
        return msg, kwargs


def setup_logging(
    app_name: str = "dca_bot",
    console_level: Optional[str] = None,
    file_level: Optional[str] = None,
    enable_asset_tracking: bool = True
) -> logging.Logger:
    """
    Set up comprehensive logging configuration for the application.
    
    Args:
        app_name: Name of the application (used for log file naming)
        console_level: Console logging level (defaults to config.log_level)
        file_level: File logging level (defaults to config.log_level)
        enable_asset_tracking: Enable asset lifecycle tracking formatting
    
    Returns:
        Configured root logger
    """
    # Get log levels from config or use provided values
    console_level = console_level or config.log_level
    file_level = file_level or config.log_level
    
    # Convert string levels to logging constants
    console_level_int = getattr(logging, console_level.upper(), logging.INFO)
    file_level_int = getattr(logging, file_level.upper(), logging.INFO)
    
    # Ensure logs directory exists
    config.log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    if enable_asset_tracking:
        console_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
        file_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
    else:
        # Standard formatters without asset tracking
        console_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        console_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
        file_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # During testing, use individual loggers instead of root logger to allow pytest capture
    import sys
    if 'pytest' in sys.modules:
        # Use individual logger for pytest compatibility
        logger = logging.getLogger(app_name)
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = True  # Allow pytest to capture logs
    else:
        # Use root logger for production
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
    
    # Console handler - only add if console logging is not explicitly disabled
    disable_console = os.getenv('DISABLE_MAIN_APP_CONSOLE_LOGGING', '').lower() == 'true'
    
    if not disable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(console_level_int)
        console_handler.setFormatter(console_formatter)
        logger.addHandler(console_handler)
    
    # File handler with rotation
    log_file = config.log_dir / f"{app_name}.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(file_level_int)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Asset logs are included in the main log file (no separate asset file)
    
    # Suppress noisy third-party library logs
    # Websockets library logs PING/PONG at DEBUG level - suppress them
    logging.getLogger('websockets.client').setLevel(logging.INFO)
    logging.getLogger('websockets.protocol').setLevel(logging.INFO)
    logging.getLogger('websockets.server').setLevel(logging.INFO)
    logging.getLogger('websockets').setLevel(logging.INFO)
    
    # Alpaca SDK can be noisy at DEBUG level
    logging.getLogger('alpaca').setLevel(logging.INFO)
    
    # Suppress noisy internal utility logs
    # Database connection/query logs are too verbose at DEBUG level
    logging.getLogger('utils.db_utils').setLevel(logging.INFO)
    logging.getLogger('models.cycle_data').setLevel(logging.INFO)
    logging.getLogger('models.asset_config').setLevel(logging.INFO)
    
    # Log the logging setup
    setup_logger = logging.getLogger(__name__)
    setup_logger.info(f"Logging configured for {app_name}")
    setup_logger.info(f"Console level: {console_level}, File level: {file_level}")
    setup_logger.info(f"Log directory: {config.log_dir}")
    setup_logger.info(f"Asset tracking: {'Enabled' if enable_asset_tracking else 'Disabled'}")
    
    return logger


def get_asset_logger(asset_symbol: str, base_logger: Optional[logging.Logger] = None) -> AssetContextAdapter:
    """
    Get a logger adapter that automatically includes asset context in all log messages.
    
    This is the recommended way to log asset-related operations for lifecycle tracking.
    
    Args:
        asset_symbol: The trading pair symbol (e.g., 'BTC/USD')
        base_logger: Base logger to adapt (defaults to module logger)
    
    Returns:
        Logger adapter with asset context
    
    Example:
        >>> asset_logger = get_asset_logger('BTC/USD')
        >>> asset_logger.info("Base order placed")
        # Logs: [ASSET:BTC/USD] Base order placed
    """
    if base_logger is None:
        # Use the caller's module logger
        import inspect
        frame = inspect.currentframe().f_back
        module_name = frame.f_globals.get('__name__', 'unknown')
        base_logger = logging.getLogger(module_name)
    
    return AssetContextAdapter(base_logger, asset_symbol)


def log_asset_lifecycle_event(
    asset_symbol: str,
    event_type: str,
    details: dict,
    logger: Optional[logging.Logger] = None,
    level: int = logging.INFO
) -> None:
    """
    Log a structured asset lifecycle event.
    
    This function provides a standardized way to log important asset lifecycle events
    with consistent formatting for easy analysis.
    
    Args:
        asset_symbol: The trading pair symbol (e.g., 'BTC/USD')
        event_type: Type of event (e.g., 'BASE_ORDER', 'SAFETY_ORDER', 'TAKE_PROFIT')
        details: Dictionary of event details
        logger: Logger to use (defaults to caller's module logger)
        level: Log level to use
    
    Example:
        >>> log_asset_lifecycle_event(
        ...     'BTC/USD',
        ...     'BASE_ORDER',
        ...     {'order_id': '123', 'quantity': 0.001, 'price': 50000}
        ... )
    """
    if logger is None:
        # Use the caller's module logger
        import inspect
        frame = inspect.currentframe().f_back
        module_name = frame.f_globals.get('__name__', 'unknown')
        logger = logging.getLogger(module_name)
    
    # Create asset logger adapter
    asset_logger = AssetContextAdapter(logger, asset_symbol)
    
    # Format the details for logging
    details_str = " | ".join(f"{k}={v}" for k, v in details.items())
    message = f"LIFECYCLE_EVENT:{event_type} | {details_str}"
    
    asset_logger.log(level, message)


# Convenience functions for the new consolidated logging approach
def setup_main_app_logging(
    console_level: Optional[str] = None,
    file_level: Optional[str] = None,
    enable_asset_tracking: bool = True
) -> logging.Logger:
    """
    Set up logging for the main WebSocket application with time-based rotation.
    
    This function sets up logging specifically for the main application with
    daily log rotation and gzip compression for archived files.
    
    Args:
        console_level: Console logging level (defaults to config.log_level)
        file_level: File logging level (defaults to config.log_level)
        enable_asset_tracking: Enable asset lifecycle tracking formatting
    
    Returns:
        Configured logger for main_app
    """
    # Get log levels from config or use provided values
    console_level = console_level or config.log_level
    file_level = file_level or config.log_level
    
    # Convert string levels to logging constants
    console_level_int = getattr(logging, console_level.upper(), logging.INFO)
    file_level_int = getattr(logging, file_level.upper(), logging.INFO)
    
    # Ensure logs directory exists
    config.log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    if enable_asset_tracking:
        console_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
        file_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
    else:
        # Standard formatters without asset tracking
        console_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        console_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
        file_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # During testing, use individual loggers instead of root logger to allow pytest capture
    import sys
    if 'pytest' in sys.modules:
        # Use individual logger for pytest compatibility
        logger = logging.getLogger("main_app")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = True  # Allow pytest to capture logs
    else:
        # Use root logger for production
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
    
    # main_app logs only to files, never to console
    
    # Time-based rotating file handler for main.log with gzip compression
    log_file = config.log_dir / "main.log"
    file_handler = GzipTimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=7,  # Keep 7 days of archives
        encoding='utf-8'
    )
    file_handler.setLevel(file_level_int)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Asset logs are included in main.log (no separate asset file for main app)
    
    # Suppress noisy third-party library logs
    # Websockets library logs PING/PONG at DEBUG level - suppress them
    logging.getLogger('websockets.client').setLevel(logging.INFO)
    logging.getLogger('websockets.protocol').setLevel(logging.INFO)
    logging.getLogger('websockets.server').setLevel(logging.INFO)
    logging.getLogger('websockets').setLevel(logging.INFO)
    
    # Alpaca SDK can be noisy at DEBUG level
    logging.getLogger('alpaca').setLevel(logging.INFO)
    
    # Suppress noisy internal utility logs
    # Database connection/query logs are too verbose at DEBUG level
    logging.getLogger('utils.db_utils').setLevel(logging.INFO)
    logging.getLogger('models.cycle_data').setLevel(logging.INFO)
    logging.getLogger('models.asset_config').setLevel(logging.INFO)
    
    # Log the logging setup
    setup_logger = logging.getLogger(__name__)
    setup_logger.info("Logging configured for main_app with time-based rotation")
    setup_logger.info(f"Console level: {console_level}, File level: {file_level}")
    setup_logger.info(f"Log directory: {config.log_dir}")
    setup_logger.info(f"Log file: main.log (rotated daily, 7 days retention, gzipped)")
    setup_logger.info(f"Asset tracking: {'Enabled' if enable_asset_tracking else 'Disabled'}")
    setup_logger.info("Noisy debug logs suppressed (websockets, alpaca, db_utils, models)")
    
    return logger


def setup_caretaker_logging(
    script_name: str,
    console_level: Optional[str] = None,
    file_level: Optional[str] = None,
    enable_asset_tracking: bool = True
) -> logging.Logger:
    """
    Set up logging for caretaker scripts.
    
    All caretaker scripts log to the same caretakers.log file for consolidation.
    Asset logs are also included in caretakers.log (no separate asset file).
    
    Args:
        script_name: Name of the caretaker script (e.g., 'order_manager', 'cooldown_manager')
        console_level: Console logging level (defaults to config.log_level)
        file_level: File logging level (defaults to config.log_level)
        enable_asset_tracking: Enable asset lifecycle tracking formatting
    
    Returns:
        Configured logger for the caretaker script
    """
    # Get log levels from config or use provided values
    console_level = console_level or config.log_level
    file_level = file_level or config.log_level
    
    # Convert string levels to logging constants
    console_level_int = getattr(logging, console_level.upper(), logging.INFO)
    file_level_int = getattr(logging, file_level.upper(), logging.INFO)
    
    # Ensure logs directory exists
    config.log_dir.mkdir(parents=True, exist_ok=True)
    
    # Create formatters
    if enable_asset_tracking:
        console_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
        file_formatter = AssetLifecycleFormatter(include_asset_prefix=True)
    else:
        # Standard formatters without asset tracking
        console_format = '%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s'
        console_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
        file_formatter = logging.Formatter(console_format, datefmt='%Y-%m-%d %H:%M:%S')
    
    # During testing, use individual loggers instead of root logger to allow pytest capture
    import sys
    if 'pytest' in sys.modules:
        # Use individual logger for pytest compatibility
        logger = logging.getLogger(f"caretakers_{script_name}")
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
        logger.propagate = True  # Allow pytest to capture logs
    else:
        # Use root logger for production
        logger = logging.getLogger()
        logger.setLevel(logging.DEBUG)
        logger.handlers.clear()
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(console_level_int)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)
    
    # Single file handler for caretakers.log (includes all logs, including asset logs)
    log_file = config.log_dir / "caretakers.log"
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.log_max_bytes,
        backupCount=config.log_backup_count,
        encoding='utf-8'
    )
    file_handler.setLevel(file_level_int)
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)
    
    # Log the logging setup
    setup_logger = logging.getLogger(__name__)
    setup_logger.info(f"Caretaker logging configured for {script_name}")
    setup_logger.info(f"Console level: {console_level}, File level: {file_level}")
    setup_logger.info(f"Log directory: {config.log_dir}")
    setup_logger.info(f"Log file: caretakers.log (consolidated)")
    setup_logger.info(f"Asset tracking: {'Enabled' if enable_asset_tracking else 'Disabled'}")
    
    return logger


def setup_script_logging(script_name: str) -> logging.Logger:
    """
    Set up logging for standalone scripts with appropriate file naming.
    
    Args:
        script_name: Name of the script (without .py extension)
    
    Returns:
        Configured logger for the script
    """
    return setup_logging(
        app_name=script_name,
        enable_asset_tracking=True
    )


# Convenience function for quick setup
def quick_setup(app_name: str = "dca_bot") -> logging.Logger:
    """Quick logging setup with sensible defaults."""
    return setup_logging(app_name, enable_asset_tracking=True)


# Pre-configured loggers for common use cases
def get_main_app_logger() -> logging.Logger:
    """Get the main application logger."""
    return setup_logging("main_app", enable_asset_tracking=True)


def get_script_logger(script_name: str) -> logging.Logger:
    """Get a logger for a script."""
    return setup_logging(script_name, enable_asset_tracking=True) 