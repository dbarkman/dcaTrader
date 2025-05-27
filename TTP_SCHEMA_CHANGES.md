# Trailing Take Profit (TTP) Schema Changes - Phase 1

## Overview

This document summarizes the database schema and Python model changes made to support the Trailing Take Profit (TTP) feature. This is Phase 1 of the TTP implementation, focusing only on data structures.

## Database Schema Changes

### 1. dca_assets Table

**New Fields Added:**
```sql
ALTER TABLE dca_assets
ADD COLUMN ttp_enabled BOOLEAN NOT NULL DEFAULT FALSE AFTER take_profit_percent,
ADD COLUMN ttp_deviation_percent DECIMAL(10, 4) NULL DEFAULT NULL AFTER ttp_enabled;
```

**Field Descriptions:**
- `ttp_enabled`: Boolean flag to enable/disable TTP for this asset (default: FALSE)
- `ttp_deviation_percent`: Percentage deviation for TTP trailing (default: NULL)

**Note:** The existing `take_profit_percent` field will be used as the TTP activation percentage when `ttp_enabled` is TRUE.

### 2. dca_cycles Table

**New Fields Added:**
```sql
ALTER TABLE dca_cycles
ADD COLUMN highest_trailing_price DECIMAL(20, 10) NULL DEFAULT NULL AFTER last_order_fill_price;
```

**Status Enum Updated:**
```sql
ALTER TABLE dca_cycles 
MODIFY COLUMN status ENUM('watching', 'buying', 'selling', 'cooldown', 'complete', 'error', 'trailing') NOT NULL;
```

**Field Descriptions:**
- `highest_trailing_price`: Tracks the highest price reached during TTP trailing (default: NULL)
- `status`: Added 'trailing' as a valid status for cycles in TTP mode

## Python Model Changes

### 1. DcaAsset Model (`src/models/asset_config.py`)

**New Fields:**
```python
@dataclass
class DcaAsset:
    # ... existing fields ...
    ttp_enabled: bool
    ttp_deviation_percent: Optional[Decimal]
    # ... existing fields ...
```

**Updated Functions:**
- `from_dict()`: Handles new TTP fields with proper type conversion
- `get_asset_config()`: Updated SQL query to include TTP fields
- `get_asset_config_by_id()`: Updated SQL query to include TTP fields  
- `get_all_enabled_assets()`: Updated SQL query to include TTP fields

### 2. DcaCycle Model (`src/models/cycle_data.py`)

**New Fields:**
```python
@dataclass
class DcaCycle:
    # ... existing fields ...
    highest_trailing_price: Optional[Decimal]
    # ... existing fields ...
```

**Updated Functions:**
- `from_dict()`: Handles new highest_trailing_price field
- `get_latest_cycle()`: Updated SQL query to include highest_trailing_price
- `create_cycle()`: Added highest_trailing_price parameter (default: None)
- `get_cycle_by_id()`: Updated SQL query to include highest_trailing_price

## Test Updates

### 1. Test Fixtures (`conftest.py`)

**Updated sample_asset_data:**
```python
{
    # ... existing fields ...
    'ttp_enabled': False,
    'ttp_deviation_percent': None,
    # ... existing fields ...
}
```

**Updated sample_cycle_data:**
```python
{
    # ... existing fields ...
    'highest_trailing_price': None,
    # ... existing fields ...
}
```

### 2. Unit Tests

**New Asset Tests:**
- `test_dca_asset_from_dict_with_ttp_enabled()`: Tests TTP enabled scenario
- `test_dca_asset_from_dict_null_ttp_deviation()`: Tests NULL TTP deviation

**New Cycle Tests:**
- `test_dca_cycle_from_dict_with_trailing_status()`: Tests trailing status
- `test_dca_cycle_from_dict_completed_with_sell_price()`: Tests completed cycles
- `test_create_cycle_with_trailing_status()`: Tests cycle creation with TTP

## Key Implementation Notes

### Default Values
- `ttp_enabled`: FALSE (TTP disabled by default)
- `ttp_deviation_percent`: NULL (no deviation when TTP disabled)
- `highest_trailing_price`: NULL (no trailing price initially)

### Data Integrity
- When `ttp_enabled` is FALSE, `ttp_deviation_percent` should be NULL
- When creating 'cooldown' cycles, `highest_trailing_price` should be None
- The 'trailing' status is only valid when TTP is enabled for the asset

### Backward Compatibility
- All existing functionality remains unchanged
- New fields have sensible defaults
- Existing cycles and assets continue to work without modification

## Verification

All changes have been verified through:
- ✅ Unit tests (31 tests passing)
- ✅ Integration tests with actual database
- ✅ Model serialization/deserialization
- ✅ SQL query compatibility

## Next Steps

This completes Phase 1 of TTP implementation. The data structures are now ready for Phase 2, which will implement the actual TTP trading logic in the main application.

**Phase 2 will include:**
- TTP activation logic when take-profit threshold is reached
- Price tracking and trailing logic
- TTP sell trigger when price drops by deviation percentage
- Status transitions between 'watching' → 'trailing' → 'selling' → 'cooldown' 