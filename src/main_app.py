#!/usr/bin/env python3
"""
DCA Trading Bot - Main WebSocket Application

This script manages real-time connections to Alpaca's WebSocket streams for:
- Market data (quotes, trades, bars) via CryptoDataStream
- Trade updates (order fills, cancellations) via TradingStream

The application runs continuously, processing real-time events and will eventually
trigger trading logic based on market conditions and account updates.
"""

import asyncio
import signal
import logging
import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Add src directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from alpaca.data.live import CryptoDataStream
from alpaca.trading.stream import TradingStream

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/main_app.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

# Global flag for graceful shutdown
shutdown_requested = False
# Global stream references for shutdown
crypto_stream_ref = None
trading_stream_ref = None


def validate_environment() -> bool:
    """
    Validate that required environment variables are set.
    
    Returns:
        True if all required variables are present, False otherwise
    """
    required_vars = ['APCA_API_KEY_ID', 'APCA_API_SECRET_KEY']
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        return False
    
    return True


async def on_crypto_quote(quote):
    """
    Handler for cryptocurrency quote updates.
    
    Args:
        quote: Quote object from Alpaca containing bid/ask data
    """
    logger.info(f"Quote: {quote.symbol} - Bid: ${quote.bid_price} @ {quote.bid_size}, "
               f"Ask: ${quote.ask_price} @ {quote.ask_size}")


async def on_crypto_trade(trade):
    """
    Handler for cryptocurrency trade updates.
    
    Args:
        trade: Trade object from Alpaca containing trade data
    """
    logger.info(f"Trade: {trade.symbol} - Price: ${trade.price}, Size: {trade.size}, "
               f"Time: {trade.timestamp}")


async def on_crypto_bar(bar):
    """
    Handler for cryptocurrency bar updates (OHLCV data).
    
    Args:
        bar: Bar object from Alpaca containing OHLCV data
    """
    logger.info(f"Bar: {bar.symbol} - Open: ${bar.open}, High: ${bar.high}, "
               f"Low: ${bar.low}, Close: ${bar.close}, Volume: {bar.volume}")


async def on_trade_update(trade_update):
    """
    Handler for account trade updates (order fills, cancellations, etc.).
    
    Args:
        trade_update: TradeUpdate object from Alpaca
    """
    logger.info(f"Trade Update: {trade_update.event} - Order ID: {trade_update.order.id}, "
               f"Symbol: {trade_update.order.symbol}, Side: {trade_update.order.side}, "
               f"Status: {trade_update.order.status}")
    
    if hasattr(trade_update, 'execution_id') and trade_update.execution_id:
        logger.info(f"  Execution: Price ${trade_update.price}, Qty: {trade_update.qty}")


def setup_signal_handlers():
    """Set up signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        global shutdown_requested, crypto_stream_ref, trading_stream_ref
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_requested = True
        
        # Try to stop the streams immediately using their internal mechanisms
        if crypto_stream_ref:
            try:
                logger.info("Stopping CryptoDataStream...")
                # Use the stream's internal stop method if available
                if hasattr(crypto_stream_ref, '_should_run'):
                    crypto_stream_ref._should_run = False
                if hasattr(crypto_stream_ref, '_ws') and crypto_stream_ref._ws:
                    try:
                        crypto_stream_ref._ws.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error stopping CryptoDataStream: {e}")
        
        if trading_stream_ref:
            try:
                logger.info("Stopping TradingStream...")
                # Use the stream's internal stop method if available
                if hasattr(trading_stream_ref, '_should_run'):
                    trading_stream_ref._should_run = False
                if hasattr(trading_stream_ref, '_ws') and trading_stream_ref._ws:
                    try:
                        trading_stream_ref._ws.close()
                    except:
                        pass
            except Exception as e:
                logger.error(f"Error stopping TradingStream: {e}")
        
        logger.info("Shutdown signal processed - streams should stop immediately")
        
        # Reduce force exit timeout since we're being more aggressive
        import threading
        def force_exit():
            import time
            time.sleep(2)  # Give only 2 seconds for cleanup
            if shutdown_requested:
                logger.warning("Forcing immediate exit...")
                os._exit(0)
        
        threading.Thread(target=force_exit, daemon=True).start()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def setup_crypto_stream() -> CryptoDataStream:
    """
    Setup and configure the CryptoDataStream for market data.
    
    Returns:
        Configured CryptoDataStream instance
    """
    api_key = os.getenv('APCA_API_KEY_ID')
    api_secret = os.getenv('APCA_API_SECRET_KEY')
    
    # Determine if using paper trading based on base URL
    base_url = os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    paper = 'paper-api' in base_url
    
    logger.info(f"Setting up CryptoDataStream (paper={paper})")
    
    # Initialize crypto stream
    stream = CryptoDataStream(
        api_key=api_key,
        secret_key=api_secret
    )
    
    # List of most popular crypto pairs to monitor (limited to avoid symbol limit)
    crypto_symbols = [
        'BTC/USD',   # Bitcoin
        'ETH/USD',   # Ethereum
        'SOL/USD',   # Solana
        'DOGE/USD',  # Dogecoin
        'AVAX/USD',  # Avalanche
        'LINK/USD',  # Chainlink
        'UNI/USD',   # Uniswap
        'XRP/USD'    # Ripple
    ]
    
    # Subscribe to quotes and trades for selected crypto symbols
    for symbol in crypto_symbols:
        stream.subscribe_quotes(on_crypto_quote, symbol)
        stream.subscribe_trades(on_crypto_trade, symbol)
    
    logger.info(f"Subscribed to quotes and trades for {len(crypto_symbols)} popular crypto pairs:")
    logger.info(f"Symbols: {', '.join(crypto_symbols)}")
    
    # Optionally subscribe to bars for minute-by-minute data
    # stream.subscribe_bars(on_crypto_bar, 'BTC/USD')
    
    return stream


def setup_trading_stream() -> TradingStream:
    """
    Setup and configure the TradingStream for account updates.
    
    Returns:
        Configured TradingStream instance
    """
    api_key = os.getenv('APCA_API_KEY_ID')
    api_secret = os.getenv('APCA_API_SECRET_KEY')
    
    # Determine if using paper trading based on base URL
    base_url = os.getenv('APCA_API_BASE_URL', 'https://paper-api.alpaca.markets')
    paper = 'paper-api' in base_url
    
    logger.info(f"Setting up TradingStream (paper={paper})")
    
    # Initialize trading stream
    stream = TradingStream(
        api_key=api_key,
        secret_key=api_secret
    )
    
    # Subscribe to trade updates
    stream.subscribe_trade_updates(on_trade_update)
    
    logger.info("Subscribed to trade updates")
    
    return stream


def main():
    """Main application entry point."""
    global shutdown_requested, crypto_stream_ref, trading_stream_ref
    
    logger.info("="*60)
    logger.info("DCA Trading Bot - Main WebSocket Application Starting")
    logger.info("="*60)
    
    # Validate environment
    if not validate_environment():
        logger.error("Environment validation failed. Exiting.")
        sys.exit(1)
    
    # Set up signal handlers for graceful shutdown
    setup_signal_handlers()
    
    # Create logs directory if it doesn't exist
    os.makedirs('logs', exist_ok=True)
    
    try:
        # Setup streams
        crypto_stream_ref = setup_crypto_stream()
        trading_stream_ref = setup_trading_stream()
        
        logger.info("Starting both WebSocket streams concurrently...")
        
        # Run both streams concurrently using asyncio
        asyncio.run(run_both_streams(crypto_stream_ref, trading_stream_ref))
        
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down...")
    except Exception as e:
        logger.error(f"Unexpected error in main: {e}")
        logger.exception("Full traceback:")
        raise
    finally:
        # Ensure streams are closed
        if crypto_stream_ref:
            try:
                crypto_stream_ref.close()
                logger.info("CryptoDataStream closed")
            except:
                pass
        
        if trading_stream_ref:
            try:
                trading_stream_ref.close()
                logger.info("TradingStream closed")
            except:
                pass
        
        logger.info("DCA Trading Bot - Main WebSocket Application Stopped")


async def run_both_streams(crypto_stream, trading_stream):
    """
    Run both crypto data stream and trading stream concurrently.
    
    Args:
        crypto_stream: CryptoDataStream instance
        trading_stream: TradingStream instance
    """
    global shutdown_requested
    
    logger.info("Creating concurrent tasks for both streams...")
    
    # Create tasks for both streams with shutdown monitoring
    crypto_task = asyncio.create_task(run_crypto_stream_async(crypto_stream))
    trading_task = asyncio.create_task(run_trading_stream_async(trading_stream))
    
    # Create a shutdown monitor task
    shutdown_task = asyncio.create_task(monitor_shutdown_simple(crypto_task, trading_task))
    
    try:
        # Run all tasks concurrently
        await asyncio.gather(crypto_task, trading_task, shutdown_task, return_exceptions=True)
    except asyncio.CancelledError:
        logger.info("Stream tasks cancelled")
    except Exception as e:
        logger.error(f"Error in concurrent stream execution: {e}")
    finally:
        # Ensure all tasks are cancelled
        for task in [crypto_task, trading_task, shutdown_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        logger.info("All WebSocket tasks have been stopped")


async def monitor_shutdown_simple(crypto_task, trading_task):
    """
    Monitor for shutdown requests and cancel stream tasks.
    
    Args:
        crypto_task: Crypto stream asyncio task
        trading_task: Trading stream asyncio task
    """
    global shutdown_requested
    
    while not shutdown_requested:
        await asyncio.sleep(0.1)  # Check every 100ms
    
    # Shutdown was requested, cancel stream tasks immediately
    logger.info("Shutdown monitor detected shutdown request - cancelling stream tasks...")
    
    # Cancel the stream tasks - this will interrupt the executor threads
    if not crypto_task.done():
        crypto_task.cancel()
        logger.info("Cancelled CryptoDataStream task")
    
    if not trading_task.done():
        trading_task.cancel()
        logger.info("Cancelled TradingStream task")
    
    logger.info("Shutdown monitor completed - all stream tasks cancelled")


async def run_crypto_stream_async(crypto_stream):
    """
    Run crypto stream asynchronously with shutdown monitoring.
    
    Args:
        crypto_stream: CryptoDataStream instance
    """
    try:
        logger.info("Starting CryptoDataStream...")
        # Run the stream in executor - cancellation will interrupt it
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, crypto_stream.run)
    except asyncio.CancelledError:
        logger.info("CryptoDataStream task cancelled during shutdown")
    except Exception as e:
        if not shutdown_requested:
            logger.error(f"CryptoDataStream error: {e}")
    finally:
        logger.info("CryptoDataStream stopped")


async def run_trading_stream_async(trading_stream):
    """
    Run trading stream asynchronously with shutdown monitoring.
    
    Args:
        trading_stream: TradingStream instance
    """
    try:
        logger.info("Starting TradingStream...")
        # Run the stream in executor - cancellation will interrupt it
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, trading_stream.run)
    except asyncio.CancelledError:
        logger.info("TradingStream task cancelled during shutdown")
    except Exception as e:
        if not shutdown_requested:
            logger.error(f"TradingStream error: {e}")
    finally:
        logger.info("TradingStream stopped")


if __name__ == "__main__":
    main() 