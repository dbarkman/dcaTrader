# Asset Lifecycle Tracking Demo

## Overview
Your DCA trading bot now has enhanced lifecycle tracking! You can easily track any asset's complete trading history by grepping the logs for the trading pair.

## New Lifecycle Markers Added

### 🚀 CYCLE_START
Logged when a new DCA cycle begins (base order fills)
```
🚀 CYCLE_START: BTC/USD - New DCA cycle initiated with base order
```

### 🔄 CYCLE_CONTINUE  
Logged when safety orders are added to an existing cycle
```
🔄 CYCLE_CONTINUE: BTC/USD - Safety order #1 added to active cycle
```

### ✅ CYCLE_COMPLETE
Logged when a cycle completes with profit information
```
✅ CYCLE_COMPLETE: BTC/USD - Profit: $45.23 (4.2%)
```

### ❌ CYCLE_ERROR
Logged when critical errors occur during cycle processing
```
❌ CYCLE_ERROR: BTC/USD - Failed to update cycle after buy fill
```

## How to Use

### Track Complete Asset Lifecycle
```bash
# See everything for BTC/USD
grep "BTC/USD" logs/app.log

# Focus on key lifecycle events
grep "BTC/USD" logs/app.log | grep -E "CYCLE_|ORDER.*SUCCESSFULLY|Trade Update"
```

### Track Just Cycle Events
```bash
# See cycle starts, continuations, and completions
grep "BTC/USD.*CYCLE_" logs/app.log
```

### Track Errors Only
```bash
# See any errors for BTC/USD
grep "BTC/USD.*CYCLE_ERROR" logs/app.log
```

### Track Profit/Loss
```bash
# See completed cycles with profit info
grep "CYCLE_COMPLETE" logs/app.log
```

## Sample Complete Lifecycle

Here's what a complete BTC/USD cycle would look like in your logs:

```
2024-01-15 10:30:15 - Quote: BTC/USD - Bid: $42,150.25 @ 1.2, Ask: $42,151.00 @ 0.8
2024-01-15 10:30:16 - Base order conditions met for BTC/USD - checking Alpaca positions...
2024-01-15 10:30:17 - 📊 Market Data for BTC/USD: Bid: $42,150.25 | Ask: $42,151.00
2024-01-15 10:30:18 - 🔄 Placing LIMIT BUY order for BTC/USD: Quantity: 0.00237 @ $42,151.00
2024-01-15 10:30:19 - 📨 Trade Update: FILL - BTC/USD
2024-01-15 10:30:19 - 🎯 ORDER FILLED SUCCESSFULLY for BTC/USD!
2024-01-15 10:30:20 - 🔄 Updating cycle database for BTC/USD BUY fill...
2024-01-15 10:30:20 - 🚀 CYCLE_START: BTC/USD - New DCA cycle initiated with base order
2024-01-15 10:45:22 - 🛡️ Safety order conditions met for BTC/USD!
2024-01-15 10:45:23 - 📊 Safety Order Analysis for BTC/USD: Price Drop: $1,250.50 (2.97%)
2024-01-15 10:45:24 - 🔄 Placing SAFETY LIMIT BUY order for BTC/USD:
2024-01-15 10:45:25 - 📨 Trade Update: FILL - BTC/USD
2024-01-15 10:45:25 - 🔄 CYCLE_CONTINUE: BTC/USD - Safety order #1 added to active cycle
2024-01-15 11:15:33 - 💰 Take-profit conditions met for BTC/USD!
2024-01-15 11:15:34 - 📊 Take-Profit Analysis for BTC/USD: Gain: $1,890.75 (4.48%)
2024-01-15 11:15:35 - 🔄 Processing take-profit SELL fill for BTC/USD...
2024-01-15 11:15:36 - ✅ CYCLE_COMPLETE: BTC/USD - Profit: $45.23 (4.2%)
2024-01-15 11:15:37 - ✅ Created new cooldown cycle for BTC/USD
```

## Benefits

1. **🔍 Easy Debugging**: Quickly find issues with specific assets
2. **📊 Performance Analysis**: Track profit/loss for each cycle
3. **⏱️ Timeline Reconstruction**: See exactly when decisions were made
4. **🚨 Error Tracking**: Identify problematic assets or conditions
5. **📈 Strategy Validation**: Verify DCA logic is working correctly

## Integration with Your Workflow

When vetting the application against the paper account:

1. **Daily Review**: `grep "CYCLE_COMPLETE\|CYCLE_ERROR" logs/app.log`
2. **Asset Deep Dive**: `grep "BTC/USD" logs/app.log | less`
3. **Performance Check**: `grep "CYCLE_COMPLETE" logs/app.log | tail -10`
4. **Error Investigation**: `grep "CYCLE_ERROR" logs/app.log`

This gives you complete visibility into every trading decision and outcome! 🎯 