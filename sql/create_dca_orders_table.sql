-- Table: dca_orders (Stores order data fetched from Alpaca API)
CREATE TABLE dca_orders (
    -- Primary key and identifiers
    id VARCHAR(36) NOT NULL PRIMARY KEY,  -- UUID from Alpaca
    client_order_id VARCHAR(36) NOT NULL,  -- UUID client order ID
    
    -- Asset information
    asset_id VARCHAR(36) NULL,  -- UUID asset ID
    symbol VARCHAR(25) NULL,  -- e.g., 'BTC/USD', 'LINK/USD'
    asset_class VARCHAR(20) NULL,  -- e.g., 'CRYPTO'
    
    -- Order details
    order_class VARCHAR(20) NOT NULL,  -- e.g., 'SIMPLE', 'BRACKET', 'OCO', 'OTO'
    order_type VARCHAR(20) NULL,  -- e.g., 'MARKET', 'LIMIT', 'STOP', 'STOP_LIMIT'
    type VARCHAR(20) NULL,  -- Duplicate of order_type (API provides both)
    side VARCHAR(10) NULL,  -- 'BUY' or 'SELL'
    position_intent VARCHAR(20) NULL,  -- e.g., 'BUY_TO_OPEN', 'SELL_TO_CLOSE'
    
    -- Quantities and prices
    qty DECIMAL(30, 15) NULL,  -- Order quantity
    notional DECIMAL(20, 10) NULL,  -- Notional value (for fractional shares)
    filled_qty DECIMAL(30, 15) NULL,  -- Filled quantity
    filled_avg_price DECIMAL(20, 10) NULL,  -- Average fill price
    limit_price DECIMAL(20, 10) NULL,  -- Limit price
    stop_price DECIMAL(20, 10) NULL,  -- Stop price
    trail_price DECIMAL(20, 10) NULL,  -- Trail price
    trail_percent DECIMAL(10, 4) NULL,  -- Trail percentage
    ratio_qty DECIMAL(30, 15) NULL,  -- Ratio quantity (for ratio orders)
    hwm DECIMAL(20, 10) NULL,  -- High water mark (for trailing orders)
    
    -- Order status and timing
    status VARCHAR(20) NOT NULL,  -- e.g., 'NEW', 'FILLED', 'CANCELED', 'EXPIRED'
    time_in_force VARCHAR(10) NOT NULL,  -- e.g., 'DAY', 'GTC', 'IOC', 'FOK'
    extended_hours BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- Timestamps
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    submitted_at TIMESTAMP NOT NULL,
    filled_at TIMESTAMP NULL,
    canceled_at TIMESTAMP NULL,
    expired_at TIMESTAMP NULL,
    expires_at TIMESTAMP NULL,
    failed_at TIMESTAMP NULL,
    replaced_at TIMESTAMP NULL,
    
    -- Order relationships
    replaced_by VARCHAR(36) NULL,  -- UUID of replacing order
    replaces VARCHAR(36) NULL,  -- UUID of replaced order
    
    -- Complex order legs (JSON for multi-leg orders)
    legs JSON NULL,  -- For bracket/OCO orders with multiple legs
    
    -- Metadata
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_by_fetch_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes for common queries
    INDEX idx_symbol (symbol),
    INDEX idx_status (status),
    INDEX idx_side (side),
    INDEX idx_created_at (created_at),
    INDEX idx_filled_at (filled_at),
    INDEX idx_client_order_id (client_order_id),
    INDEX idx_fetched_at (fetched_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Comments for dca_orders table:
-- This table stores complete order data fetched from Alpaca API
-- - id: Alpaca's UUID for the order (primary key)
-- - client_order_id: Our client-generated UUID for the order
-- - All price fields use DECIMAL(20,10) for precision
-- - All quantity fields use DECIMAL(30,15) for high precision crypto amounts
-- - legs: JSON field for complex multi-leg orders (bracket, OCO, etc.)
-- - fetched_at: When we fetched this data from API
-- - updated_by_fetch_at: Last time this record was updated by fetch
-- - No foreign key constraints to avoid deletion cascades
-- - Comprehensive indexing for performance on common queries 