-- Historical 1-minute bars table for backtesting
-- Based on Alpaca CryptoHistoricalDataClient response structure

CREATE TABLE historical_1min_bars (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Foreign key to dca_assets table
    asset_id INT NOT NULL,
    
    -- Bar timestamp (opening time in UTC)
    timestamp DATETIME NOT NULL,
    
    -- OHLC prices (using DECIMAL for precision)
    open DECIMAL(20, 10) NOT NULL,
    high DECIMAL(20, 10) NOT NULL,
    low DECIMAL(20, 10) NOT NULL,
    close DECIMAL(20, 10) NOT NULL,
    
    -- Volume and trading data
    volume DECIMAL(30, 15) NOT NULL DEFAULT 0,
    trade_count DECIMAL(20, 10) DEFAULT NULL,
    vwap DECIMAL(20, 10) DEFAULT NULL,  -- Volume Weighted Average Price
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Indexes for efficient querying
    UNIQUE KEY unique_asset_timestamp (asset_id, timestamp),
    INDEX idx_timestamp (timestamp),
    INDEX idx_asset_id (asset_id),
    INDEX idx_asset_timestamp_range (asset_id, timestamp),
    
    -- Foreign key constraint
    FOREIGN KEY (asset_id) REFERENCES dca_assets(id) ON DELETE CASCADE
);

-- Comments for documentation
ALTER TABLE historical_1min_bars 
    COMMENT = 'Historical 1-minute OHLCV bars for cryptocurrency backtesting';

-- Add column comments
ALTER TABLE historical_1min_bars 
    MODIFY COLUMN asset_id INT NOT NULL COMMENT 'Reference to dca_assets.id',
    MODIFY COLUMN timestamp DATETIME NOT NULL COMMENT 'Bar opening time in UTC',
    MODIFY COLUMN open DECIMAL(20, 10) NOT NULL COMMENT 'Opening price',
    MODIFY COLUMN high DECIMAL(20, 10) NOT NULL COMMENT 'Highest price in the bar',
    MODIFY COLUMN low DECIMAL(20, 10) NOT NULL COMMENT 'Lowest price in the bar',
    MODIFY COLUMN close DECIMAL(20, 10) NOT NULL COMMENT 'Closing price',
    MODIFY COLUMN volume DECIMAL(30, 15) NOT NULL DEFAULT 0 COMMENT 'Trading volume',
    MODIFY COLUMN trade_count DECIMAL(20, 10) DEFAULT NULL COMMENT 'Number of trades (if available)',
    MODIFY COLUMN vwap DECIMAL(20, 10) DEFAULT NULL COMMENT 'Volume Weighted Average Price (if available)'; 