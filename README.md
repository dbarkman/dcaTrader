# **Alpaca DCA Crypto Trading Bot (v1.0)**

## **1\. Project Overview**

This project is a Python-based Dollar Cost Averaging (DCA) trading bot designed to automate cryptocurrency trading on the Alpaca exchange. The bot operates using real-time market data and trade updates via Alpaca's WebSocket streams and employs several caretaker scripts run by cron to ensure data consistency and operational stability.  
The core strategy involves placing an initial base order for a configured cryptocurrency. If the price drops by a specified percentage from the last purchase price, subsequent "safety orders" are placed. When the price rises to a specified take-profit percentage above the average purchase price of the entire position for the current cycle, the position is sold. The bot then enters a cooldown period before potentially starting a new trading cycle for that asset.

## **2\. Core Functionality (v1.0)**

* **Automated DCA Trading:** Executes DCA strategy for configured crypto assets.  
* **Real-time Data Processing:** Utilizes Alpaca WebSockets for live market data (quotes/trades) and trade updates (order fills, cancellations).  
* **Dynamic Order Placement:**  
  * Places initial base limit BUY orders.  
  * Places subsequent safety limit BUY orders based on price drops from the last fill price.  
  * Places market SELL orders for take-profit.  
* **Cycle Management:** Tracks each trading cycle (from initial buy to take-profit sell) independently per asset.  
* **Cooldown Mechanism:** Implements a configurable cooldown period after a take-profit before initiating a new cycle.  
* **Price-Triggered Restart:** Allows a new cycle to start before cooldown expiry if the price drops significantly from the last sell price.  
* **Caretaker Scripts (Cron-based):**  
  * Manages stale (unfilled) BUY orders by canceling them.  
  * Manages orphaned Alpaca orders (orders on Alpaca not tracked by an active bot cycle).  
  * Manages the transition of assets from 'cooldown' to 'watching' status.  
  * Ensures consistency between the bot's database state and Alpaca's state (positions and orders).  
* **Process Watchdog:** Monitors the health of the main WebSocket application and attempts restarts/sends alerts on failure.  
* **Database Persistence:** Stores asset configurations, trading cycle history, and operational state in a MySQL/MariaDB database.

## **3\. Technology Stack**

* **Programming Language:** Python 3.x  
* **Exchange API:** Alpaca (alpaca-py SDK) - primarily WebSockets, with REST API for order placement and specific queries.  
* **Database:** MySQL / MariaDB  
* **Scheduling:** cron (for caretaker scripts and watchdog)  
* **Key Python Libraries (anticipated):**  
  * alpaca-py (for Alpaca API interaction)  
  * mysql-connector-python (or similar, for DB interaction)  
  * websockets (if alpaca-py doesn't abstract it sufficiently or for direct WebSocket management)  
  * python-dotenv (for managing environment variables like API keys)  
  * logging (standard Python logging module)

## **4\. Development Practices**

* **Pragmatism & KISS (Keep It Simple, Stupid):** Prioritize simple, straightforward solutions over complex ones.  
* **Phased Development:** Features are broken down into small, manageable phases.  
* **Functional Testing:** Simple, pragmatic functional tests for core logic components.  
* **Integration Testing:** A dedicated script (integration\_test.py) will test end-to-end scenarios against an Alpaca paper trading account, including database state changes and interactions with caretaker scripts. This script will include setup and teardown routines.  
* **Modularity:** Code will be organized into logical modules (e.g., WebSocket handlers, caretaker scripts, database interaction, Alpaca interaction).  
* **Clear Separation of Concerns:**  
  * WebSocket processes handle real-time event listening and reactive order placement/DB updates.  
  * Caretaker cron scripts handle periodic checks, data synchronization, and system stability tasks.

## **4.5. Backtesting Infrastructure**

### **4.5.1. Overview**

The backtesting system allows testing DCA strategies against historical market data to evaluate performance before risking real capital. The infrastructure consists of:

* **Historical Data Storage:** 1-minute OHLCV bars stored in the `historical_1min_bars` table
* **Data Fetching:** Automated scripts to populate and maintain historical data from Alpaca
* **Strategy Testing:** (Future) Backtesting engine to simulate DCA strategy execution

### **4.5.2. Historical Data Table**

**Table: historical_1min_bars** (Stores 1-minute historical bars for backtesting)
```sql
CREATE TABLE historical_1min_bars (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asset_id INT NOT NULL,
    timestamp DATETIME NOT NULL,
    open DECIMAL(20, 10) NOT NULL,
    high DECIMAL(20, 10) NOT NULL,
    low DECIMAL(20, 10) NOT NULL,
    close DECIMAL(20, 10) NOT NULL,
    volume DECIMAL(30, 15) NOT NULL DEFAULT 0,
    trade_count DECIMAL(20, 10) DEFAULT NULL,
    vwap DECIMAL(20, 10) DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY unique_asset_timestamp (asset_id, timestamp),
    INDEX idx_timestamp (timestamp),
    INDEX idx_asset_id (asset_id),
    INDEX idx_asset_timestamp_range (asset_id, timestamp),
    
    FOREIGN KEY (asset_id) REFERENCES dca_assets(id) ON DELETE CASCADE
) COMMENT = 'Historical 1-minute OHLCV bars for cryptocurrency backtesting';
```

### **4.5.3. Historical Data Management**

**Create the historical data table:**
```bash
python scripts/create_historical_bars_table.py
```

**Fetch historical data:**
```bash
# Bulk fetch for specific symbols and date range
python scripts/fetch_historical_bars.py --symbols "BTC/USD,ETH/USD" --start-date "2024-01-01" --end-date "2024-01-31" --mode bulk

# Incremental update for all configured assets
python scripts/fetch_historical_bars.py --all-configured --mode incremental

# Fetch recent data for one symbol
python scripts/fetch_historical_bars.py --symbols "BTC/USD" --start-date "2024-12-01" --mode bulk
```

**Features:**
* **Bulk Mode:** Initial population of large historical datasets
* **Incremental Mode:** Ongoing updates to keep data current
* **API Rate Limiting:** Respects Alpaca API limits with automatic delays
* **Pagination Handling:** Efficiently processes large datasets across multiple API pages
* **Upsert Logic:** Prevents duplicate data while allowing updates
* **Robust Error Handling:** Continues processing other symbols if one fails

### **4.5.4. Data Schema Details**

The historical bars table captures all available properties from the Alpaca API:
* **OHLC Prices:** Open, High, Low, Close with high precision (DECIMAL 20,10)
* **Volume Data:** Trading volume with extended precision (DECIMAL 30,15)
* **Additional Metrics:** Trade count and VWAP when available
* **Indexing:** Optimized for time-range queries common in backtesting
* **Foreign Key:** Links to asset configuration in `dca_assets` table

## **5\. Setup Process**

### **5.1. Prerequisites**

* Python 3.8+ installed.  
* MySQL or MariaDB server installed and accessible.  
* An Alpaca account (Paper Trading account highly recommended for development and testing).  
* git for cloning the repository.

### **5.2. Initial Setup**

1. **Clone the Repository:**
```bash
git clone <repository_url>
cd <repository_name>
```

2. **Create Python Virtual Environment:**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install Dependencies:**
```bash
pip install -r requirements.txt
```

   *(A requirements.txt file will be created as part of the development process).*
4. **Database Setup:**
   * Create a new database in MySQL/MariaDB (e.g., dca_bot_db).
   * Create a database user with appropriate permissions for this database.
   * Execute the following SQL DDL statements to create the necessary tables:

**Table: dca_assets** (Stores configuration for tradable assets)
```sql
CREATE TABLE dca_assets (
  id int(11) NOT NULL,
  asset_symbol varchar(25) NOT NULL,
  is_enabled tinyint(1) NOT NULL DEFAULT 1,
  base_order_amount decimal(20,10) NOT NULL DEFAULT 10.0000000000,
  safety_order_amount decimal(20,10) NOT NULL DEFAULT 20.0000000000,
  max_safety_orders int(11) NOT NULL DEFAULT 15,
  safety_order_deviation decimal(10,4) NOT NULL DEFAULT 0.9000,
  take_profit_percent decimal(10,4) NOT NULL DEFAULT 2.0000,
  ttp_enabled tinyint(1) NOT NULL DEFAULT 1,
  ttp_deviation_percent decimal(10,4) DEFAULT 1.0000,
  last_sell_price decimal(20,10) DEFAULT NULL,
  buy_order_price_deviation_percent decimal(10,4) NOT NULL DEFAULT 1.0000,
  cooldown_period int(11) NOT NULL DEFAULT 120,
  created_at timestamp NOT NULL DEFAULT current_timestamp(),
  updated_at timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE dca_assets
  ADD PRIMARY KEY (id),
  ADD UNIQUE KEY asset_symbol (asset_symbol);

ALTER TABLE dca_assets
  MODIFY id int(11) NOT NULL AUTO_INCREMENT;
```

**Table: dca_cycles** (Stores data for each trading cycle of an asset)
```sql
CREATE TABLE dca_cycles (
  id int(11) NOT NULL,
  asset_id int(11) NOT NULL,
  status varchar(20) NOT NULL,
  quantity decimal(30,15) NOT NULL DEFAULT 0.000000000000000,
  average_purchase_price decimal(20,10) NOT NULL DEFAULT 0.0000000000,
  safety_orders int(11) NOT NULL DEFAULT 0,
  latest_order_id varchar(255) DEFAULT NULL,
  latest_order_created_at timestamp NULL DEFAULT NULL,
  last_order_fill_price decimal(20,10) DEFAULT NULL,
  highest_trailing_price decimal(20,10) DEFAULT NULL,
  completed_at timestamp NULL DEFAULT NULL,
  sell_price decimal(20,10) DEFAULT NULL,
  created_at timestamp NOT NULL DEFAULT current_timestamp(),
  updated_at timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

ALTER TABLE dca_cycles
  ADD PRIMARY KEY (id),
  ADD KEY asset_id (asset_id);

ALTER TABLE dca_cycles
  MODIFY id int(11) NOT NULL AUTO_INCREMENT;
```

**Table: dca_orders** (Stores order data fetched from Alpaca API)
```sql
CREATE TABLE dca_orders (
  id varchar(36) NOT NULL,
  client_order_id varchar(36) NOT NULL,
  asset_id varchar(36) DEFAULT NULL,
  symbol varchar(25) DEFAULT NULL,
  asset_class varchar(20) DEFAULT NULL,
  order_class varchar(20) NOT NULL,
  order_type varchar(20) DEFAULT NULL,
  type varchar(20) DEFAULT NULL,
  side varchar(10) DEFAULT NULL,
  position_intent varchar(20) DEFAULT NULL,
  qty decimal(30,15) DEFAULT NULL,
  notional decimal(20,10) DEFAULT NULL,
  filled_qty decimal(30,15) DEFAULT NULL,
  filled_avg_price decimal(20,10) DEFAULT NULL,
  limit_price decimal(20,10) DEFAULT NULL,
  stop_price decimal(20,10) DEFAULT NULL,
  trail_price decimal(20,10) DEFAULT NULL,
  trail_percent decimal(10,4) DEFAULT NULL,
  ratio_qty decimal(30,15) DEFAULT NULL,
  hwm decimal(20,10) DEFAULT NULL,
  status varchar(20) NOT NULL,
  time_in_force varchar(10) NOT NULL,
  extended_hours tinyint(1) NOT NULL DEFAULT 0,
  created_at timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp(),
  updated_at timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
  submitted_at timestamp NOT NULL DEFAULT '0000-00-00 00:00:00',
  filled_at timestamp NULL DEFAULT NULL,
  canceled_at timestamp NULL DEFAULT NULL,
  expired_at timestamp NULL DEFAULT NULL,
  expires_at timestamp NULL DEFAULT NULL,
  failed_at timestamp NULL DEFAULT NULL,
  replaced_at timestamp NULL DEFAULT NULL,
  replaced_by varchar(36) DEFAULT NULL,
  replaces varchar(36) DEFAULT NULL,
  legs longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin DEFAULT NULL CHECK (json_valid(legs)),
  fetched_at timestamp NOT NULL DEFAULT current_timestamp(),
  updated_by_fetch_at timestamp NOT NULL DEFAULT current_timestamp() ON UPDATE current_timestamp()
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;


ALTER TABLE dca_orders
  ADD PRIMARY KEY (id),
  ADD KEY idx_symbol (symbol),
  ADD KEY idx_status (status),
  ADD KEY idx_side (side),
  ADD KEY idx_created_at (created_at),
  ADD KEY idx_filled_at (filled_at),
  ADD KEY idx_client_order_id (client_order_id),
  ADD KEY idx_fetched_at (fetched_at);
```

5. Configure Environment Variables:
   Create a .env file in the project root directory with your Alpaca API keys and database credentials:
   
```env
# Alpaca API Credentials
APCA_API_KEY_ID="YOUR_ALPACA_API_KEY_ID"
APCA_API_SECRET_KEY="YOUR_ALPACA_API_SECRET_KEY"
APCA_API_BASE_URL="https://paper-api.alpaca.markets"
# APCA_API_BASE_URL="https://api.alpaca.markets"

# Database Credentials
DB_HOST="localhost"
DB_USER="your_db_user"
DB_PASSWORD="your_db_password"
DB_NAME="dca_bot_db"
DB_PORT="3306"

# Order Management Configuration
ORDER_COOLDOWN_SECONDS=5  # Prevent duplicate orders during processing (default: 5)

# Watchdog Email Alert Configuration (Optional)
ALERT_EMAIL_SENDER="your_sender_email@example.com"
ALERT_EMAIL_RECEIVER="your_receiver_email@example.com"
ALERT_EMAIL_SMTP_SERVER="smtp.example.com"
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_SMTP_USER="your_smtp_user"
ALERT_EMAIL_SMTP_PASSWORD="your_smtp_password"
```

   Configuration notes:
   - For paper trading, use `https://paper-api.alpaca.markets`
   - For live trading, use `https://api.alpaca.markets` 
   - Or your MySQL/MariaDB port for `DB_PORT`
   - Often same as sender for `ALERT_EMAIL_SMTP_USER`
   - Ensure this .env file is added to your .gitignore to prevent committing sensitive credentials.

6. Populate dca_assets Table:
   Run the script, scripts/add_asset.py followed by a comma separated list of assets:

   ```
   python scripts/add_asset.py BTC/USD,ETH/USD,XRP/USD,SOL/USD,DOGE/USD,LINK/USD,AVAX/USD,SHIB/USD,BCH/USD,LTC/USD,DOT/USD,PEPE/USD,AAVE/USD,UNI/USD,TRUMP/USD --enabled; python scripts/add_asset.py MKR/USD,GRT/USD,CRV/USD,XTZ/USD,BAT/USD,SUSHI/USD,YFI/USD
   ```

### **5.3. Cron Job Setup**

The following cron jobs need to be set up on your Linux server. Ensure the paths to the Python interpreter (within your virtual environment) and the scripts are correct.

```cron
# Watchdog (every 3 minutes)
*/3 * * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/watchdog.py >> logs/cron.log 2>&1

# Order Manager (every minute)
* * * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/order_manager.py >> logs/cron.log 2>&1

# Cooldown Manager (every minute)  
* * * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/cooldown_manager.py >> logs/cron.log 2>&1

# Consistency Checker (every 5 minutes)
*/5 * * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/consistency_checker.py >> logs/cron.log 2>&1

# Asset Caretaker (every 15 minutes)
*/5 * * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/asset_caretaker.py >> logs/cron.log 2>&1

# Log Rotation
0 8 * * *	cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/log_rotator.py >> logs/cron.log 2>&1

# Fetch Orders (every 15 minutes)
*/15 * * * *     cd /home/david/dcaTrader && /home/david/dcaTrader/venv/bin/python scripts/fetch_orders.py >> logs/cron.log 2>&1
```

Setup notes:
- Ensure environment variables are available to cron, or source them in the scripts.
- It's often best to create a wrapper script that activates the venv and then runs the Python script.

Example wrapper script: `/path_to_project/run_script_wrapper.sh <script_name.py>`
```bash
#!/bin/bash
cd /path_to_project/
source venv/bin/activate
python scripts/$1 >> /path_to_project/logs/cron.log 2>&1
```

*Create a logs directory in your project root for the log files.*

**Consolidated Logging Structure:**
The application uses a consolidated logging approach with three primary log files:
- `logs/main.log` - All logs from the main WebSocket application (main_app.py)
- `logs/caretakers.log` - All logs from caretaker scripts (order_manager.py, cooldown_manager.py, consistency_checker.py, watchdog.py, etc.)
- `logs/cron.log` - Raw stdout/stderr from cron job executions (shell errors, startup issues, etc.)

Python's logging system automatically handles multiple processes writing to the same log file safely.

**Log Rotation:**
The application implements comprehensive log rotation to manage disk space:
- `main.log` uses time-based rotation (daily at midnight) with automatic gzip compression
- `caretakers.log` and `cron.log` are rotated by an external script (`scripts/log_rotator.py`)
- All rotated logs are compressed with gzip and kept for 7 days by default
- Archived logs follow the naming pattern: `logfile.YYYY-MM-DD.gz`

## **6\. Usage**

1. Start the Main Application:
   The watchdog.py script is responsible for starting and monitoring the main WebSocket application (e.g., main_app.py). Ensure watchdog.py is configured correctly to launch your main application script.
   Manually, you can run:
   
```bash
source venv/bin/activate
python main_app.py
```

2. Ensure Cron Jobs are Active:
   Verify that the cron jobs for the caretaker scripts and the watchdog are set up and running correctly.
3. **Monitoring:**
   * Check the log files in the logs/ directory for operational messages, errors, and trade activity.
   * Monitor your Alpaca account (Paper Trading dashboard) for orders and positions.
   * Check the database tables (dca_assets, dca_cycles) for state changes.

## **7\. Running Tests**

### **7.1. Setup**

Make sure your virtual environment is properly activated:

```bash
source venv/bin/activate
# Verify python points to venv:
which python  # Should show: ~/dcaTrader/venv/bin/python
```

If needed, install test dependencies:
```bash
pip install -r requirements.txt
```

### **7.2. Running Tests**

#### **Using the test runner script (recommended):**

```bash
python run_tests.py all          # Run all tests
python run_tests.py unit         # Run only unit tests  
python run_tests.py coverage     # Run with coverage report
python run_tests.py html         # Generate HTML coverage report
python run_tests.py integration  # Run integration tests
python run_tests.py fast         # Run tests without coverage
python run_tests.py verbose      # Run with verbose output
```

#### **Using pytest directly:**

```bash
python -m pytest tests/ -v                    # Run all tests
python -m pytest tests/ -m unit              # Run only unit tests
python -m pytest tests/ --cov=src            # Run with coverage
python -m pytest tests/ --cov=src --cov-report=html  # HTML coverage report
```

### **7.3. Test Organization**

- **Unit tests**: Use `@pytest.mark.unit` - test individual functions with mocking
- **Integration tests**: Use `@pytest.mark.integration` - test end-to-end scenarios
- **Slow tests**: Use `@pytest.mark.slow` - tests that take longer to run
- **DB tests**: Use `@pytest.mark.db` - tests requiring database connection

### **7.4. Coverage Reports**

- Terminal coverage: Shows percentage and missing lines
- HTML coverage: Generated in `htmlcov/index.html` - open in browser for detailed view

### **7.5. Integration Testing**

The integration test script (`integration_test.py`) is designed to be run against your Alpaca Paper Trading account:

```bash
source venv/bin/activate
python integration_test.py
```

This script will perform setup (potentially clearing DB tables and Alpaca positions/orders for a clean test environment), run test scenarios, make assertions, and then perform teardown. It will provide verbose output.

### **7.6. Current Status**

- ✅ 344 tests passing
- ✅ 85% code coverage  
- ✅ All Phase 1-3 functionality tested
- ✅ Log rotation system fully implemented and tested

*This README provides a foundational overview. Specific script names and detailed commands may evolve during development.*