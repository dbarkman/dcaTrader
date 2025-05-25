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
    id INT AUTO_INCREMENT PRIMARY KEY,
    asset_symbol VARCHAR(25) NOT NULL UNIQUE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    base_order_amount DECIMAL(20, 10) NOT NULL,
    safety_order_amount DECIMAL(20, 10) NOT NULL,
    max_safety_orders INT NOT NULL,
    safety_order_deviation DECIMAL(10, 4) NOT NULL,
    take_profit_percent DECIMAL(10, 4) NOT NULL,
    cooldown_period INT NOT NULL,
    buy_order_price_deviation_percent DECIMAL(10, 4) NOT NULL,
    last_sell_price DECIMAL(20, 10) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Comments for dca_assets table:
- `asset_symbol`: e.g., 'BTC/USD'
- `safety_order_deviation`: Percentage price drop to trigger safety order
- `take_profit_percent`: Percentage price rise from avg purchase price to trigger sell
- `cooldown_period`: Seconds after a take profit
- `buy_order_price_deviation_percent`: Percent down from last sell to start new cycle (preempts cooldown)
- `last_sell_price`: Price of the last successful take-profit sell for this asset

**Table: dca_cycles** (Stores data for each trading cycle of an asset)
```sql
CREATE TABLE dca_cycles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    asset_id INT NOT NULL,
    status VARCHAR(20) NOT NULL,
    quantity DECIMAL(30, 15) NOT NULL DEFAULT 0,
    average_purchase_price DECIMAL(20, 10) NOT NULL DEFAULT 0,
    safety_orders INT NOT NULL DEFAULT 0,
    latest_order_id VARCHAR(255) NULL,
    last_order_fill_price DECIMAL(20, 10) NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (asset_id) REFERENCES dca_assets(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

Comments for dca_cycles table:
- `status`: e.g., 'watching', 'buying', 'selling', 'cooldown', 'complete', 'error'
- `quantity`: Total quantity of the asset held in this cycle
- `average_purchase_price`: Weighted average purchase price for this cycle
- `safety_orders`: Number of safety orders filled in this cycle
- `latest_order_id`: Alpaca order ID of the most recent order for this cycle
- `last_order_fill_price`: Fill price of the most recent BUY order in this cycle
- `completed_at`: Timestamp when the cycle reached a terminal status ('complete', 'error')

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
   Manually insert rows into the dca_assets table for the cryptocurrencies you want the bot to trade. For example:
   
```sql
INSERT INTO dca_assets (
    asset_symbol, is_enabled, base_order_amount, safety_order_amount,
    max_safety_orders, safety_order_deviation, take_profit_percent,
    cooldown_period, buy_order_price_deviation_percent
) VALUES (
    'BTC/USD', TRUE, 20.00, 20.00,
    5, 1.5, 1.0,
    300, 2.0
);
```

   Parameter explanations:
   - Base and Safety order amounts in USD: 20.00, 20.00
   - Max 5 safety orders, 1.5% drop for SO, 1.0% take profit
   - 300s (5 min) cooldown, 2% drop from last sell to restart early

### **5.3. Cron Job Setup**

The following cron jobs need to be set up on your Linux server. Ensure the paths to the Python interpreter (within your virtual environment) and the scripts are correct.

```cron
# Watchdog for the main WebSocket application (e.g., runs every 5 minutes)
*/5 * * * * /path_to_project_venv/venv/bin/python /path_to_project/watchdog.py >> /path_to_project/logs/watchdog.log 2>&1

# Caretaker: Order Manager (e.g., runs every 1 minute)
* * * * * /path_to_project_venv/venv/bin/python /path_to_project/order_manager.py >> /path_to_project/logs/order_manager.log 2>&1

# Caretaker: Cooldown Manager (e.g., runs every 1 minute)
* * * * * /path_to_project_venv/venv/bin/python /path_to_project/cooldown_manager.py >> /path_to_project/logs/cooldown_manager.log 2>&1

# Caretaker: Consistency Checker (e.g., runs every 5 minutes)
*/5 * * * * /path_to_project_venv/venv/bin/python /path_to_project/consistency_checker.py >> /path_to_project/logs/consistency_checker.log 2>&1
```

Setup notes:
- Ensure environment variables are available to cron, or source them in the scripts.
- It's often best to create a wrapper script that activates the venv and then runs the Python script.

Example wrapper script: `/path_to_project/run_script_wrapper.sh <script_name.py>`
```bash
#!/bin/bash
cd /path_to_project/
source venv/bin/activate
python $1 >> /path_to_project/logs/$1.log 2>&1
```

*Create a logs directory in your project root for the log files.*

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

- ✅ 34 tests passing
- ✅ 84% code coverage  
- ✅ All Phase 1 functionality tested

*This README provides a foundational overview. Specific script names and detailed commands may evolve during development.*