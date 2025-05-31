"""
Pure strategy logic functions for DCA trading.

This module contains the core decision-making logic decoupled from execution.
Functions take market data and state as input and return action intents.
"""

import os
import logging
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal

from models.backtest_structs import (
    MarketTickInput, StrategyAction, OrderIntent, CycleStateUpdateIntent, 
    TTPStateUpdateIntent, OrderSide, OrderType,
    create_buy_order_action, create_sell_order_action, 
    create_ttp_activation_action, create_ttp_update_action
)
from models.asset_config import DcaAsset
from models.cycle_data import DcaCycle

logger = logging.getLogger(__name__)


def decide_base_order_action(
    market_input: MarketTickInput,
    asset_config: DcaAsset,
    current_cycle: DcaCycle,
    current_alpaca_position: Optional[object] = None
) -> Optional[StrategyAction]:
    """
    Decide whether to place a base order.
    
    Args:
        market_input: Current market data
        asset_config: Asset configuration
        current_cycle: Current DCA cycle state
        current_alpaca_position: Optional Alpaca position for conflict check
        
    Returns:
        StrategyAction if base order should be placed, None otherwise
    """
    try:
        # Step 1: Check if asset is enabled
        if not asset_config.is_enabled:
            logger.debug(f"Asset {market_input.symbol} is disabled, skipping base order check")
            return None
        
        # Step 2: Check if cycle is in 'watching' status with no quantity (no existing position)
        if current_cycle.status != 'watching':
            return None
            
        if current_cycle.quantity > Decimal('0'):
            return None
        
        # Step 3: Check for existing Alpaca position (ignore tiny positions)
        min_order_qty = 0.000000002  # Alpaca's minimum order quantity for crypto
        
        if current_alpaca_position:
            position_qty = float(current_alpaca_position.qty)
            
            # Ignore tiny positions that are below minimum order size
            if position_qty >= min_order_qty:
                logger.warning(f"Base order for {market_input.symbol} skipped, existing position found on Alpaca. "
                              f"Position: {current_alpaca_position.qty} @ ${current_alpaca_position.avg_entry_price}")
                return None
        
        # Step 4: Validate market data
        if not market_input.current_ask_price or market_input.current_ask_price <= 0:
            logger.error(f"Invalid ask price for {market_input.symbol}: {market_input.current_ask_price}")
            return None
        
        if not market_input.current_bid_price or market_input.current_bid_price <= 0:
            logger.error(f"Invalid bid price for {market_input.symbol}: {market_input.current_bid_price}")
            return None
        
        # Step 5: Calculate order size (convert USD to crypto quantity)
        base_order_usd = float(asset_config.base_order_amount)
        if not base_order_usd or base_order_usd <= 0:
            logger.error(f"Invalid base order amount for {market_input.symbol}: {base_order_usd}")
            return None
            
        order_quantity = Decimal(str(base_order_usd)) / market_input.current_ask_price
        
        # Validate calculated values
        if not order_quantity or order_quantity <= 0:
            logger.error(f"Invalid calculated order quantity for {market_input.symbol}: {order_quantity}")
            return None
        
        # Step 6: Determine limit price
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            limit_price = market_input.current_ask_price * Decimal('1.05')
        else:
            # Normal production mode: use ask price
            limit_price = market_input.current_ask_price
        
        # Step 7: Create and return the action intent
        logger.info(f"📊 Base order conditions met for {market_input.symbol}")
        logger.info(f"   Order Amount: ${base_order_usd} ÷ {limit_price} = {order_quantity} {market_input.symbol.split('/')[0]}")
        
        return create_buy_order_action(
            symbol=market_input.symbol,
            quantity=order_quantity,
            limit_price=limit_price,
            new_status="buying",
            timestamp=market_input.timestamp
        )
        
    except Exception as e:
        logger.error(f"Error in decide_base_order_action for {market_input.symbol}: {e}")
        return None


def decide_safety_order_action(
    market_input: MarketTickInput,
    asset_config: DcaAsset,
    current_cycle: DcaCycle
) -> Optional[StrategyAction]:
    """
    Decide whether to place a safety order.
    
    Args:
        market_input: Current market data
        asset_config: Asset configuration  
        current_cycle: Current DCA cycle state
        
    Returns:
        StrategyAction if safety order should be placed, None otherwise
    """
    try:
        # Step 1: Check if asset is enabled
        if not asset_config.is_enabled:
            logger.debug(f"Asset {market_input.symbol} is disabled, skipping safety order check")
            return None
        
        # Step 2: Check if cycle is in 'watching' status with quantity > 0 (existing position)
        if current_cycle.status != 'watching':
            return None
        
        if current_cycle.quantity <= Decimal('0'):
            return None
        
        # Step 3: Check if we can place more safety orders
        if current_cycle.safety_orders >= asset_config.max_safety_orders:
            logger.debug(f"Asset {market_input.symbol} already at max safety orders ({current_cycle.safety_orders}/{asset_config.max_safety_orders}) - skipping")
            return None
        
        # Step 4: Check if we have a last_order_fill_price to calculate trigger from
        if current_cycle.last_order_fill_price is None:
            return None
        
        # Step 5: Calculate trigger price for safety order
        safety_deviation_decimal = asset_config.safety_order_deviation / Decimal('100')  # Convert % to decimal
        trigger_price = current_cycle.last_order_fill_price * (Decimal('1') - safety_deviation_decimal)
        
        # Step 6: Check if current ask price has dropped enough to trigger safety order
        if market_input.current_ask_price > trigger_price:
            return None
        
        # Step 7: Validate market data
        if not market_input.current_ask_price or market_input.current_ask_price <= 0:
            logger.error(f"Invalid ask price for safety order {market_input.symbol}: {market_input.current_ask_price}")
            return None
        
        if not market_input.current_bid_price or market_input.current_bid_price <= 0:
            logger.error(f"Invalid bid price for safety order {market_input.symbol}: {market_input.current_bid_price}")
            return None
        
        # Step 8: Calculate safety order size (convert USD to crypto quantity)
        safety_order_usd = float(asset_config.safety_order_amount)
        if not safety_order_usd or safety_order_usd <= 0:
            logger.error(f"Invalid safety order amount for {market_input.symbol}: {safety_order_usd}")
            return None
            
        order_quantity = Decimal(str(safety_order_usd)) / market_input.current_ask_price
        
        # Validate calculated values
        if not order_quantity or order_quantity <= 0:
            logger.error(f"Invalid calculated safety order quantity for {market_input.symbol}: {order_quantity}")
            return None
        
        # Step 9: Determine limit price
        testing_mode = os.getenv('TESTING_MODE', 'false').lower() == 'true'
        if testing_mode:
            # Use 5% above ask for aggressive fills during testing
            limit_price = market_input.current_ask_price * Decimal('1.05')
        else:
            # Normal production mode: use ask price
            limit_price = market_input.current_ask_price
        
        # Step 10: Log analysis and create action intent
        price_drop = current_cycle.last_order_fill_price - market_input.current_ask_price
        price_drop_pct = (price_drop / current_cycle.last_order_fill_price) * Decimal('100')
        
        logger.info(f"🛡️ Safety order conditions met for {market_input.symbol}!")
        logger.info(f"   Last Fill: {current_cycle.last_order_fill_price} | Current Ask: {market_input.current_ask_price}")
        logger.info(f"   Price Drop: {price_drop} ({price_drop_pct:.2f}%)")
        logger.info(f"   Trigger at: {trigger_price} ({asset_config.safety_order_deviation}% drop)")
        logger.info(f"   Safety Orders: {current_cycle.safety_orders + 1}/{asset_config.max_safety_orders}")
        logger.info(f"   Order Amount: ${safety_order_usd} ÷ {limit_price} = {order_quantity} {market_input.symbol.split('/')[0]}")
        
        return create_buy_order_action(
            symbol=market_input.symbol,
            quantity=order_quantity,
            limit_price=limit_price,
            new_status="buying",
            timestamp=market_input.timestamp
        )
        
    except Exception as e:
        logger.error(f"Error in decide_safety_order_action for {market_input.symbol}: {e}")
        return None


def decide_take_profit_action(
    market_input: MarketTickInput,
    asset_config: DcaAsset,
    current_cycle: DcaCycle,
    current_alpaca_position: Optional[object] = None
) -> Optional[StrategyAction]:
    """
    Decide whether to place a take-profit order or update TTP state.
    
    Args:
        market_input: Current market data
        asset_config: Asset configuration
        current_cycle: Current DCA cycle state
        current_alpaca_position: Optional Alpaca position for accurate quantity
        
    Returns:
        StrategyAction if take-profit action should be taken, None otherwise
    """
    try:
        # Step 1: Check if asset is enabled
        if not asset_config.is_enabled:
            logger.debug(f"Asset {market_input.symbol} is disabled, skipping take-profit check")
            return None
        
        # Step 2: Check if cycle is in valid status for take-profit/TTP processing
        # Valid statuses: 'watching' (standard TP or TTP activation) or 'trailing' (TTP active)
        if current_cycle.status not in ['watching', 'trailing']:
            return None
            
        if current_cycle.quantity <= Decimal('0'):
            return None
        
        # Step 3: Check if we have valid average_purchase_price for take-profit calculation
        if current_cycle.average_purchase_price is None or current_cycle.average_purchase_price <= Decimal('0'):
            logger.debug(f"Asset {market_input.symbol} has invalid average_purchase_price {current_cycle.average_purchase_price} - cannot calculate take-profit")
            return None
        
        # Step 4: Check safety order conditions are NOT met (we don't want to sell if we should be buying more)
        # Only check if we have last_order_fill_price and haven't reached max safety orders
        if (current_cycle.last_order_fill_price is not None and 
            current_cycle.safety_orders < asset_config.max_safety_orders):
            
            safety_deviation_decimal = asset_config.safety_order_deviation / Decimal('100')
            safety_trigger_price = current_cycle.last_order_fill_price * (Decimal('1') - safety_deviation_decimal)
            
            if market_input.current_ask_price <= safety_trigger_price:
                logger.debug(f"Safety order would trigger for {market_input.symbol} (ask {market_input.current_ask_price} <= trigger {safety_trigger_price}) - skipping take-profit")
                return None
        
        # Step 5: TTP-aware take-profit logic
        take_profit_percent_decimal = asset_config.take_profit_percent / Decimal('100')  # Convert % to decimal
        take_profit_trigger_price = current_cycle.average_purchase_price * (Decimal('1') + take_profit_percent_decimal)
        
        # Step 6: TTP Logic Implementation
        if not asset_config.ttp_enabled:
            # Standard take-profit logic (TTP disabled)
            if market_input.current_bid_price < take_profit_trigger_price:
                return None
            
            logger.info(f"💰 Standard take-profit conditions met for {market_input.symbol}!")
            
        else:
            # TTP logic (TTP enabled)
            if current_cycle.status == 'watching':
                # TTP not yet activated - check if we should activate it
                if market_input.current_bid_price >= take_profit_trigger_price:
                    # Activate TTP - return action to update cycle to 'trailing' status and set initial peak
                    logger.info(f"🎯 TTP activated for {market_input.symbol}, cycle {current_cycle.id}. Initial peak: {market_input.current_bid_price}")
                    
                    return create_ttp_activation_action(
                        new_status='trailing',
                        highest_trailing_price=market_input.current_bid_price
                    )
                else:
                    return None
                    
            elif current_cycle.status == 'trailing':
                # TTP is active - check for new peak or sell trigger
                current_peak = current_cycle.highest_trailing_price or Decimal('0')
                
                if market_input.current_bid_price > current_peak:
                    # New peak reached - return action to update highest_trailing_price
                    logger.info(f"🎯 TTP new peak for {market_input.symbol}, cycle {current_cycle.id}: {market_input.current_bid_price}")
                    
                    return create_ttp_update_action(
                        highest_trailing_price=market_input.current_bid_price
                    )
                    
                else:
                    # Check if price has dropped enough to trigger TTP sell
                    if asset_config.ttp_deviation_percent is None:
                        logger.error(f"TTP enabled for {market_input.symbol} but ttp_deviation_percent is None - cannot calculate sell trigger")
                        return None
                    
                    ttp_deviation_decimal = asset_config.ttp_deviation_percent / Decimal('100')
                    ttp_sell_trigger_price = current_peak * (Decimal('1') - ttp_deviation_decimal)
                    
                    if market_input.current_bid_price < ttp_sell_trigger_price:
                        # TTP sell triggered!
                        logger.info(f"🎯 TTP sell triggered for {market_input.symbol}, cycle {current_cycle.id}. Peak: {current_peak}, Deviation: {asset_config.ttp_deviation_percent}%, Current Price: {market_input.current_bid_price}")
                        logger.info(f"💰 TTP conditions met for {market_input.symbol}!")
                    else:
                        return None
        
        # Step 7: Validate market data for sell order
        if not market_input.current_bid_price or market_input.current_bid_price <= 0:
            logger.error(f"Invalid bid price for take-profit {market_input.symbol}: {market_input.current_bid_price}")
            return None
        
        # Step 8: Determine sell quantity
        # Use Alpaca position if available for accuracy, otherwise use cycle quantity
        if current_alpaca_position:
            sell_quantity = Decimal(str(current_alpaca_position.qty))
        else:
            sell_quantity = current_cycle.quantity
        
        # Validate quantity
        if not sell_quantity or sell_quantity <= 0:
            logger.error(f"Invalid sell quantity for take-profit {market_input.symbol}: {sell_quantity}")
            return None
        
        # Check minimum order requirements
        min_order_qty = Decimal('0.000000002')  # Alpaca's minimum order quantity for crypto
        if sell_quantity < min_order_qty:
            logger.warning(f"⚠️ Take-profit skipped for {market_input.symbol}: quantity {sell_quantity} < minimum {min_order_qty}")
            return None
        
        # Step 9: Log analysis
        price_gain = market_input.current_bid_price - current_cycle.average_purchase_price
        price_gain_pct = (price_gain / current_cycle.average_purchase_price) * Decimal('100')
        estimated_proceeds = market_input.current_bid_price * current_cycle.quantity
        estimated_cost = current_cycle.average_purchase_price * current_cycle.quantity
        estimated_profit = estimated_proceeds - estimated_cost
        
        # Determine order type for logging
        order_type_desc = "TTP" if asset_config.ttp_enabled else "TAKE-PROFIT"
        
        logger.info(f"📊 {order_type_desc} Analysis for {market_input.symbol}:")
        logger.info(f"   Avg Purchase: {current_cycle.average_purchase_price} | Current Bid: {market_input.current_bid_price}")
        logger.info(f"   Price Gain: {price_gain} ({price_gain_pct:.2f}%)")
        logger.info(f"   Take-Profit Trigger: {take_profit_trigger_price} ({asset_config.take_profit_percent}% gain)")
        
        if asset_config.ttp_enabled and current_cycle.status == 'trailing':
            current_peak = current_cycle.highest_trailing_price or Decimal('0')
            ttp_deviation_decimal = asset_config.ttp_deviation_percent / Decimal('100')
            ttp_sell_trigger_price = current_peak * (Decimal('1') - ttp_deviation_decimal)
            logger.info(f"   TTP Peak: {current_peak} | TTP Deviation: {asset_config.ttp_deviation_percent}%")
            logger.info(f"   TTP Sell Trigger: {ttp_sell_trigger_price}")
        
        logger.info(f"   Position: {current_cycle.quantity} {market_input.symbol.split('/')[0]}")
        logger.info(f"   Est. Proceeds: ${estimated_proceeds:.2f} | Est. Cost: ${estimated_cost:.2f}")
        logger.info(f"   Est. Profit: ${estimated_profit:.2f}")
        
        # Step 10: Create sell order action
        return create_sell_order_action(
            symbol=market_input.symbol,
            quantity=sell_quantity,
            new_status="selling",
            limit_price=None,  # Market order
            timestamp=market_input.timestamp
        )
        
    except Exception as e:
        logger.error(f"Error in decide_take_profit_action for {market_input.symbol}: {e}")
        return None 