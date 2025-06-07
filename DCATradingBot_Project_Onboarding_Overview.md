## **DCA Trading Bot: Project Onboarding & Status**

Document Version: 3.0  
Last Updated: Friday, June 7, 2024

### **Introduction**
**Who am I:** Hi, my name is David, I'm a veteran software developer and technologist. I've been writing software in some form or another since 2000 and have worked in support, Unix administration, system analytics, full stack web development, and mobile development, iOS and Android. I'm now working with AI models to build even more software, even faster! I'm excited to work with you and see what we can do together! Here is our project:

### **1\. Project Overview & Guiding Philosophy**

**Project Goal:** To develop, maintain, and enhance a robust, fully automated Dollar Cost Averaging (DCA) trading bot for cryptocurrencies on the Alpaca exchange. The bot operates 24/7, reacting to real-time market data to execute a predefined, configurable trading strategy.  
**Development Philosophy (Crucial for Success):**

* **Pragmatism & KISS (Keep It Simple, Stupid):** This is the most important principle. We always prioritize simple, straightforward, and maintainable solutions over complex or over-engineered ones.  
* **Iterative & Phased Development:** We build features in small, manageable, and well-defined phases. Each phase is a logical block of work with clear goals.  
* **Test-Driven Confidence:** The project relies heavily on a comprehensive integration test suite (integration\_test.py). This script is our primary tool for verifying that the code behaves exactly as specified in our requirements. It is not an afterthought; it is a core part of the development process.  
* **Separation of Concerns:** The architecture clearly separates real-time event handling (the main WebSocket application) from periodic maintenance and data integrity tasks (the caretaker scripts).

### **2\. System Architecture & Components**

* **Language & SDK:** Python 3.x, using the alpaca-py SDK.  
* **Main Application (src/main\_app.py):** The core of the live trading bot. It's an event-driven application that hosts two persistent Alpaca WebSocket connections:  
  * **CryptoDataStream:** Receives real-time market data (quotes). The on\_crypto\_quote handler and its helper functions (check\_and\_place\_base\_order, check\_and\_place\_safety\_order, check\_and\_place\_take\_profit\_order) contain the core strategy logic to decide *when* to trade.  
  * **TradingStream:** Receives real-time updates about the bot's own orders (e.g., new, fill, partial\_fill, canceled). The on\_trade\_update handler and its helpers (update\_cycle\_on\_buy\_fill, etc.) process these events to update the bot's state in the database.  
* **Database (MySQL/MariaDB):** The persistent state machine for the bot.  
  * **dca\_assets:** Stores the static configuration for every tradable asset (e.g., base/safety amounts, deviation percentages, take-profit settings, and flags/parameters for advanced features like Trailing Take Profit).  
  * **dca\_cycles:** Tracks the dynamic state of each individual trading cycle for every asset. This is a critical table, tracking every step from the initial buy to the final sell. Key fields include status (watching, buying, selling, trailing, cooldown, complete, error), quantity, average\_purchase\_price, last\_order\_fill\_price, safety\_orders count, latest\_order\_id, latest\_order\_created\_at, completed\_at, sell\_price, and highest\_trailing\_price.  
  * **dca\_orders:** A table and a corresponding caretaker script (scripts/fetch\_orders.py) that creates a local cache of Alpaca order data, fetched periodically.  
* **Caretaker Scripts (scripts/ directory, run by cron):** These are autonomous scripts that ensure the bot's long-term health and data integrity.  
  * order\_manager.py: Manages stale BUY orders, stuck (any limit order older than five minutes) and orphaned orders.  
  * cooldown\_manager.py: Manages the cooldown period for assets after a take-profit.  
  * consistency\_checker.py: A vital script that periodically reconciles the bot's database state with the live Alpaca account state (e.g., syncing position quantities/prices, fixing orphaned cycles).  
  * asset\_caretaker.py: Ensures all enabled assets have an initial cycle record to start trading.  
  * watchdog.py & app\_control.py: Manage the lifecycle of main\_app.py (start, stop, restart, monitor for crashes, maintenance mode).  
* **CLI Reports (analyze\_pl.py):** Standalone scripts that query the database and Alpaca API to provide performance reports. Sources data directly from the database, API and TradingView to display market information.

### **3\. Core Strategy & Key Logic Features**

* **Standard DCA:** Base Order \-\> Safety Orders on percentage drop from last buy \-\> Take Profit on percentage rise from average price.  
* **Trailing Take Profit (TTP):** If ttp\_enabled is true for an asset, once the initial take\_profit\_percent is met, the bot enters a 'trailing' status. It tracks the highest\_trailing\_price and only sells when the price drops from that peak by ttp\_deviation\_percent.  
* **Stuck Market SELL Order Handling:** A key robustness feature. When main\_app.py places a market SELL order, it immediately updates the dca\_cycles row with status='selling', latest\_order\_id, and latest\_order\_created\_at. The order\_manager.py script will then check if any cycle has been 'selling' for too long (e.g., \>75 seconds) and attempt to cancel the stuck order, allowing the bot to retry.  
* **Position Sync on Fills/Cancels:** TradingStream logic has been enhanced. Upon receiving a terminal order event (fill or canceled), it now calls get\_position() from the Alpaca API to update dca\_cycles.quantity and dca\_cycles.average\_purchase\_price with the definitive values from the broker. This makes handling of partial fills much more robust.  
* **Logging System:** A custom logging system is in place (src/utils/logging\_config.py).

### **4\. Backtesting Framework (Recently Completed Development)**

A major recent effort was to build a backtesting framework integrated into the project, designed to reuse the core strategy logic. The 5-phase development of this framework is complete.

* **Phase 1 \- Data Infrastructure:** A new historical\_1min\_bars table was designed, and a script (scripts/fetch\_historical\_bars.py) was created to perform bulk and incremental fetches of 1-minute OHLCV data from Alpaca into this local DB table.  
* **Phase 2 \- Logic Refactoring:** The core decision-making functions in main\_app.py were decoupled. They now accept market state and bot state as parameters and return "Action Intents" (OrderIntent, CycleStateUpdateIntent, etc.) instead of directly executing API calls or DB updates. The live on\_crypto\_quote handler was adapted to execute these returned intents.  
* **Phase 3 \- Backtesting Engine Core:** A new script, scripts/run\_backtest.py, was created. It contains a HistoricalDataFeeder that reads from the historical\_1min\_bars table and a main loop that iterates through historical bars, calling the refactored strategy logic from Phase 2\.  
* **Phase 4 \- Broker Simulator:** run\_backtest.py was enhanced with a "Broker Simulator." It processes OrderIntent objects, simulates order fills based on historical bar prices, and updates a SimulatedPortfolio (tracking cash and holdings). It generates "Simulated Fill Events" that are fed into the same TradingStream handler logic to update an in-memory DcaCycle object.  
* **Phase 5 \- Caretaker Simulation & Reporting:** The backtester now includes simplified logic to simulate the effects of caretaker scripts (cooldowns, stale orders) and provides a basic P/L and trade statistics report at the end of a run.

### **5\. Integration Testing (integration\_test.py)**

This script is the **single most important tool for ensuring code quality and adherence to requirements.**

* **Overhaul Complete:** The script has been recently overhauled to move from old, phase-based tests to comprehensive, scenario-based tests.  
* **Environment:** It runs **exclusively** against a dedicated paper trading account and test database, configured via a **.env.test** file.  
* **Absolute Teardown:** Every single test scenario function *must* end with a call to a comprehensive\_test\_teardown() function, which liquidates all paper account positions, cancels all open orders, and truncates the test database tables. This ensures each test runs with a completely clean slate.  
* **Methodology:**  
  * **Live Smoke Tests (Phase 1 of Overhaul \- Complete):** Verifies basic, live WebSocket connectivity by running main\_app.py as a subprocess.  
  * **Simulated WebSocket Scenarios (Phase 2 of Overhaul \- Complete):** Tests the detailed logic of main\_app.py's handlers by directly importing and calling them with mock event data, while still making real order placements and position checks against the paper account. This covers all complex DCA and TTP lifecycles.  
  * **Caretaker Script Scenarios (Phase 3 of Overhaul \- Complete):** Tests each caretaker script by setting up specific pre-conditions in the database and on the paper account, running the script's main() function, and asserting the outcome.

### **6\. Current State & Immediate Next Steps**

* **Code Status:** The core live trading bot is functional and making paper trades. The 5-phase development of the backtesting engine is complete. The integration test overhaul is complete.  
* **Next Steps Post-Testing:** The next step is to **use the bot and the backtester** to identify and fix any remaining bugs, and to begin testing various strategy configurations, while the DCA bot runs in live mode, paper trading the live market.

### **7\. Future Considerations (Post-Current Work)**

* **Experimentation Framework:** Build a "campaign manager" script that can run the backtester multiple times with different parameter sets to systematically test and compare strategies.  
* **New Strategies:** Implement advanced DCA strategies like Safety Order Volume Scale (SOVS) and TA-based entry and exit conditions (e.g., using RSI, MAs, trends for entries and stop losses for exits).  
* **Market Regime-Based Trading:** with a combination of our historical data and our backtester, we will identify different periods of history and record the noted behavior. We’ll then experiment with different strategies to understand what works best for different market behaviors. We’ll then take that knowledge and programmatically identify current market behavior and tune our DCA trading strategy to fit the current market for the greatest success.  
* **Web Interface:** A long-term goal is to build a web UI for monitoring and control.