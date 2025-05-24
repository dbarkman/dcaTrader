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
* **Exchange API:** Alpaca (alpaca-py SDK) \- primarily WebSockets, with REST API for order placement and specific queries.  
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
```
   git clone \<repository\_url\>  
   cd \<repository\_name\>
```

2. **Create Python Virtual Environment:**  
```
   python \-m venv venv  
   source venv/bin/activate  \# On Windows: venv\\Scripts\\activate
```

3. **Install Dependencies:**  
```
   pip install \-r requirements.txt
```

   *(A requirements.txt file will be created as part of the development process).*  
4. **Database Setup:**  
   * Create a new database in MySQL/MariaDB (e.g., dca\_bot\_db).  
   * Create a database user with appropriate permissions for this database.  
   * Execute the following SQL DDL statements to create the necessary tables:

**Table: dca\_assets** (Stores configuration for tradable assets)
```sql
CREATE TABLE dca\_assets (  
    id INT AUTO\_INCREMENT PRIMARY KEY,  
    asset\_symbol VARCHAR(25) NOT NULL UNIQUE, \-- e.g., 'BTC/USD'  
    is\_enabled BOOLEAN NOT NULL DEFAULT TRUE,  
    base\_order\_amount DECIMAL(20, 10\) NOT NULL,  
    safety\_order\_amount DECIMAL(20, 10\) NOT NULL,  
    max\_safety\_orders INT NOT NULL,  
    safety\_order\_deviation DECIMAL(10, 4\) NOT NULL, \-- Percentage price drop to trigger safety order  
    take\_profit\_percent DECIMAL(10, 4\) NOT NULL, \-- Percentage price rise from avg purchase price to trigger sell  
    cooldown\_period INT NOT NULL, \-- Seconds after a take profit  
    buy\_order\_price\_deviation\_percent DECIMAL(10, 4\) NOT NULL, \-- Percent down from last sell to start new cycle (preempts cooldown)  
    last\_sell\_price DECIMAL(20, 10\) NULL, \-- Price of the last successful take-profit sell for this asset  
    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP,  
    updated\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP ON UPDATE CURRENT\_TIMESTAMP  
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```
**Table: dca\_cycles** (Stores data for each trading cycle of an asset)
```sql
CREATE TABLE dca\_cycles (  
    id INT AUTO\_INCREMENT PRIMARY KEY,  
    asset\_id INT NOT NULL,  
    status VARCHAR(20) NOT NULL, \-- e.g., 'watching', 'buying', 'selling', 'cooldown', 'complete', 'error'  
    quantity DECIMAL(30, 15\) NOT NULL DEFAULT 0, \-- Total quantity of the asset held in this cycle  
    average\_purchase\_price DECIMAL(20, 10\) NOT NULL DEFAULT 0, \-- Weighted average purchase price for this cycle  
    safety\_orders INT NOT NULL DEFAULT 0, \-- Number of safety orders filled in this cycle  
    latest\_order\_id VARCHAR(255) NULL, \-- Alpaca order ID of the most recent order for this cycle  
    last\_order\_fill\_price DECIMAL(20, 10\) NULL, \-- Fill price of the most recent BUY order in this cycle  
    completed\_at TIMESTAMP NULL, \-- Timestamp when the cycle reached a terminal status ('complete', 'error')  
    created\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP,  
    updated\_at TIMESTAMP DEFAULT CURRENT\_TIMESTAMP ON UPDATE CURRENT\_TIMESTAMP,  
    FOREIGN KEY (asset\_id) REFERENCES dca\_assets(id) ON DELETE CASCADE  
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

5. Configure Environment Variables:  
   Create a .env file in the project root directory with your Alpaca API keys and database credentials:  
   ```
   \# Alpaca API Credentials  
   APCA\_API\_KEY\_ID="YOUR\_ALPACA\_API\_KEY\_ID"  
   APCA\_API\_SECRET\_KEY="YOUR\_ALPACA\_API\_SECRET\_KEY"  
   APCA\_API\_BASE\_URL="https://paper-api.alpaca.markets" \# For paper trading  
   \# APCA\_API\_BASE\_URL="https://api.alpaca.markets" \# For live trading

   \# Database Credentials  
   DB\_HOST="localhost"  
   DB\_USER="your\_db\_user"  
   DB\_PASSWORD="your\_db\_password"  
   DB\_NAME="dca\_bot\_db"  
   DB\_PORT="3306" \# Or your MySQL/MariaDB port

   \# Watchdog Email Alert Configuration (Optional)  
   ALERT\_EMAIL\_SENDER="your\_sender\_email@example.com"  
   ALERT\_EMAIL\_RECEIVER="your\_receiver\_email@example.com"  
   ALERT\_EMAIL\_SMTP\_SERVER="smtp.example.com"  
   ALERT\_EMAIL\_SMTP\_PORT=587  
   ALERT\_EMAIL\_SMTP\_USER="your\_smtp\_user" \# Often same as sender  
   ALERT\_EMAIL\_SMTP\_PASSWORD="your\_smtp\_password"
```

   *Ensure this .env file is added to your .gitignore to prevent committing sensitive credentials.*  
6. Populate dca\_assets Table:  
   Manually insert rows into the dca\_assets table for the cryptocurrencies you want the bot to trade. For example:  
   ```
   INSERT INTO dca\_assets (  
       asset\_symbol, is\_enabled, base\_order\_amount, safety\_order\_amount,  
       max\_safety\_orders, safety\_order\_deviation, take\_profit\_percent,  
       cooldown\_period, buy\_order\_price\_deviation\_percent  
   ) VALUES (  
       'BTC/USD', TRUE, 20.00, 20.00, \-- Base and Safety order amounts in USD  
       5, 1.5, 1.0, \-- Max 5 safety orders, 1.5% drop for SO, 1.0% take profit  
       300, 2.0 \-- 300s (5 min) cooldown, 2% drop from last sell to restart early  
   );
   ```

### **5.3. Cron Job Setup**

The following cron jobs need to be set up on your Linux server. Ensure the paths to the Python interpreter (within your virtual environment) and the scripts are correct.  
```
\# Ensure environment variables are available to cron, or source them in the scripts.  
\# It's often best to create a wrapper script that activates the venv and then runs the Python script.

\# Example: /path\_to\_project/run\_script\_wrapper.sh \<script\_name.py\>  
\# \#\!/bin/bash  
\# cd /path\_to\_project/  
\# source venv/bin/activate  
\# python $1 \>\> /path\_to\_project/logs/$1.log 2\>&1

\# Watchdog for the main WebSocket application (e.g., runs every 5 minutes)  
\*/5 \* \* \* \* /path\_to\_project\_venv/venv/bin/python /path\_to\_project/watchdog.py \>\> /path\_to\_project/logs/watchdog.log 2\>&1

\# Caretaker: Order Manager (e.g., runs every 1 minute)  
\* \* \* \* \* /path\_to\_project\_venv/venv/bin/python /path\_to\_project/order\_manager.py \>\> /path\_to\_project/logs/order\_manager.log 2\>&1

\# Caretaker: Cooldown Manager (e.g., runs every 1 minute)  
\* \* \* \* \* /path\_to\_project\_venv/venv/bin/python /path\_to\_project/cooldown\_manager.py \>\> /path\_to\_project/logs/cooldown\_manager.log 2\>&1

\# Caretaker: Consistency Checker (e.g., runs every 5 minutes)  
\*/5 \* \* \* \* /path\_to\_project\_venv/venv/bin/python /path\_to\_project/consistency\_checker.py \>\> /path\_to\_project/logs/consistency\_checker.log 2\>&1
```

*Create a logs directory in your project root for the log files.*

## **6\. Usage**

1. Start the Main Application:  
   The watchdog.py script is responsible for starting and monitoring the main WebSocket application (e.g., main\_app.py). Ensure watchdog.py is configured correctly to launch your main application script.  
   Manually, you can run:  
   ```
   source venv/bin/activate  
   python main\_app.py \# Or whatever your main WebSocket application script is named
   ```
2. Ensure Cron Jobs are Active:  
   Verify that the cron jobs for the caretaker scripts and the watchdog are set up and running correctly.  
3. **Monitoring:**  
   * Check the log files in the logs/ directory for operational messages, errors, and trade activity.  
   * Monitor your Alpaca account (Paper Trading dashboard) for orders and positions.  
   * Check the database tables (dca\_assets, dca\_cycles) for state changes.

## **7\. Running Tests**

### **7.1. Functional Tests**

(Details on how to run functional tests will be provided as they are developed, typically using a test runner like pytest).

### **7.2. Integration Tests**

The integration test script (integration\_test.py) is designed to be run against your Alpaca Paper Trading account.  
```
source venv/bin/activate  
python integration\_test.py
```

This script will perform setup (potentially clearing DB tables and Alpaca positions/orders for a clean test environment), run test scenarios, make assertions, and then perform teardown. It will provide verbose output.  
*This README provides a foundational overview. Specific script names and detailed commands may evolve during development.*