# **DCA Crypto Trading Bot - AI Model Prompts for Development Phases (v1.0)**

This document provides specific prompts for an AI coding assistant for each development phase of the DCA Crypto Trading Bot.

## **General Instructions for the AI Model (Include with each prompt):**

* **Primary Goal:** Implement the features for the current phase as described.
* **Development Principles:**
  * **Pragmatism & KISS:** Always prioritize the simplest, most straightforward solution that meets requirements. Avoid over-engineering.
  * **Modularity:** Organize code into logical functions and modules.
  * **Clarity:** Write clean, readable, and well-commented Python code.
* **Testing:**
  * **Functional Tests:** Write basic, pragmatic functional tests for any new, non-trivial logic. Focus on testing the core behavior, not exhaustive edge cases unless critical.
  * **Integration Test Script (`integration_test.py`):** Add a new test function to `integration_test.py` that specifically tests the features implemented in *this phase*. This test should:
    * Clearly state the scenario being tested (verbose print statements).
    * Perform necessary setup in the database and/or Alpaca paper account.
    * Execute the relevant part of the bot's logic (e.g., call a caretaker script, simulate a WebSocket event by calling its handler).
    * Make assertions about the outcome (e.g., database state changes, orders appearing/disappearing on Alpaca).
    * Report findings clearly.
    * Include teardown if necessary to clean up (e.g., delete test orders/positions, truncate test data from DB).
* **Error Handling:** Implement basic try-except blocks for expected I/O operations (network calls, DB access).
* **Logging:** Use Python's logging module. Add informative log messages (INFO for general operations, WARNING for potential issues, ERROR for failures).
* **Environment Variables:** Use python-dotenv and a `.env` file for configurations like API keys and database credentials. Refer to `README.md` for expected variables.
* **Database Interaction:** Assume utility functions for database connections and queries will be available (as developed in Phase 1).
* **Alpaca Interaction:** Assume utility functions/classes for Alpaca client initialization and basic API calls will be available (as developed in Phase 2).
* **Iterative Refinement:** After generating the code, you will be asked to "run the test suite (functional and the new integration test scenario), observe the results, and debug any issues until all tests for this phase are passing."

### **Prompt for Phase 1: Project Setup & Database Models**

Overview:
"We are starting a new Python project: a Dollar Cost Averaging (DCA) trading bot for Alpaca. This first phase focuses on setting up the basic project structure, establishing database connectivity with MySQL/MariaDB, and creating Python representations for our core database tables: `dca_assets` (for asset configurations) and `dca_cycles` (for tracking individual trading cycles). Refer to the `README.md` for the exact schemas of these tables."

**Tasks:**

1. Create the standard project directory structure: `src/` (for main source code), `src/utils/` (for utilities), `src/models/` (for data models), `scripts/` (for caretaker scripts - will be populated later), `tests/` (for functional tests), `logs/` (will be used for log files).
2. Create an initial `.gitignore` file (e.g., for `venv/`, `__pycache__/`, `.env`, `logs/*.log`).
3. Create an initial `requirements.txt` file including python-dotenv and mysql-connector-python.
4. In `src/utils/db_utils.py`:
   * Implement `get_db_connection()`: Connects to MySQL using credentials from `.env` and returns a connection object.
   * Implement `execute_query(query, params=None, fetch_one=False, fetch_all=False, commit=False)`: Executes a given SQL query. Handles params for parameterized queries. Can fetch one row, all rows, or just execute (e.g., INSERT, UPDATE) and commit.
5. In `src/models/asset_config.py`:
   * Define a Python class `DcaAsset` that mirrors the columns of the `dca_assets` table. Include type hints.
   * Implement a function `get_asset_config(db_conn, asset_symbol: str) -> DcaAsset | None`: Fetches an asset's configuration by its symbol.
   * Implement `get_all_enabled_assets(db_conn) -> list[DcaAsset]`: Fetches all enabled assets.
6. In `src/models/cycle_data.py`:
   * Define a Python class `DcaCycle` that mirrors the columns of the `dca_cycles` table. Include type hints.
   * Implement `get_latest_cycle(db_conn, asset_id: int) -> DcaCycle | None`: Fetches the most recent cycle for a given asset_id (order by id DESC or created_at DESC, limit 1).
   * Implement `create_cycle(db_conn, asset_id: int, status: str, quantity: Decimal = Decimal(0), ...) -> DcaCycle`: Inserts a new cycle record and returns the created DcaCycle object (including its new id and created_at from DB).
   * Implement `update_cycle(db_conn, cycle_id: int, updates: dict) -> bool`: Updates specified fields of a cycle. updates is a dictionary of column_name: new_value.

**Gotchas to Watch For:**

* Ensure database connection details are loaded correctly from `.env`.
* Handle potential None results gracefully when fetching data.
* Use parameterized queries to prevent SQL injection.
* Remember Decimal type for financial values.

**Functional Tests (in `tests/`):**

* `test_db_connection()`: Checks if `get_db_connection()` successfully connects.
* `test_get_asset_config()`: Mocks DB call or uses test DB to verify fetching an asset.
* `test_create_and_get_cycle()`: Tests creating a cycle and then fetching it to verify data.

**Integration Test (`integration_test.py` - new function):**

* `test_phase1_asset_and_cycle_crud()`:
  * Scenario: Basic Create, Read, Update, Delete (CRUD-like) operations for `dca_assets` and `dca_cycles` using the functions you built.
  * Setup: Connect to the (paper) test database.
  * Action:
    1. Insert a test `dca_assets` record directly via SQL or a helper if you build one (e.g., for testing `get_asset_config`).
    2. Call `get_asset_config()` for the test asset and assert the returned data is correct.
    3. Call `create_cycle()` for this test asset. Assert the returned object has an ID and correct initial values.
    4. Call `get_latest_cycle()` and assert it matches the created cycle.
    5. Call `update_cycle()` to change the status, then fetch again and assert the update.
  * Teardown: Delete the test `dca_cycles` and `dca_assets` records.
  * Report: Print success/failure and any relevant data.

### **Prompt for Phase 2: Alpaca SDK Integration & Basic API Calls**

Overview:
"This phase involves integrating the alpaca-py SDK into our project. We need to establish a client for interacting with Alpaca's REST API, load API keys securely, and implement basic functions to fetch account information, market data (price), place a test order, fetch open orders, and cancel an order. This will primarily be in a new utility module."

**Tasks:**

1. Add alpaca-py to `requirements.txt`.
2. Create `src/utils/alpaca_client_rest.py` (to distinguish from future WebSocket client wrappers if any).
3. In `alpaca_client_rest.py`:
   * Implement `get_trading_client() -> TradingClient`: Initializes and returns an Alpaca TradingClient using API key/secret/URL from `.env`.
   * Implement `get_account_info(client: TradingClient) -> Account | None`.
   * Implement `get_latest_crypto_price(client: TradingClient, symbol: str) -> float | None`: Fetches the latest trade price for a crypto symbol (e.g., using `client.get_latest_crypto_trade()`). Handle cases where price data might not be immediately available.
   * Implement `place_limit_buy_order(client: TradingClient, symbol: str, qty: float, limit_price: float, time_in_force: str = 'day') -> Order | None`.
   * Implement `get_open_orders(client: TradingClient) -> list[Order]`.
   * Implement `cancel_order(client: TradingClient, order_id: str) -> bool`. Returns True if cancellation is successful (or acknowledged).

**Gotchas to Watch For:**

* Alpaca API endpoints and SDK function names/parameters.
* Error handling for API requests (e.g., invalid symbol, insufficient funds - though not explicitly handled by placing an order yet, be mindful of potential errors).
* Rate limits (not an issue for these basic calls, but good to be aware of Alpaca's policies).
* Ensure correct symbol format (e.g., 'BTC/USD').

**Functional Tests (in `tests/`):**

* `test_get_trading_client_initialization()`: Mocks `.env` and checks client creation.
* Mock Alpaca client responses to test:
  * `test_get_account_info_parsing()`.
  * `test_get_latest_crypto_price_parsing()`.

**Integration Test (`integration_test.py` - new function):**

* `test_phase2_alpaca_rest_api_order_cycle()`:
  * Scenario: Test the full cycle of placing, viewing, and canceling an order via REST API on the Alpaca paper account.
  * Setup: Initialize TradingClient. Use a non-critical, low-value test symbol if possible, or BTC/USD with a very small quantity and a price far from the market to prevent accidental fills for this specific test.
  * Action:
    1. Call `get_account_info()` and print some details (e.g., buying power).
    2. Call `get_latest_crypto_price()` for 'BTC/USD' and print it.
    3. Call `place_limit_buy_order()` for a very small quantity of 'BTC/USD' (e.g., 0.0001) at a price significantly below the current market (e.g., $1000). Store the returned order object. Assert an order object is returned.
    4. Call `get_open_orders()`. Iterate through them and find the order placed in step 3 by its ID. Assert it's found and its status is 'new' or 'accepted'.
    5. Call `cancel_order()` using the order ID. Assert it returns True or successfully processes.
    6. Call `get_open_orders()` again. Assert the canceled order is no longer present or its status is 'canceled'.
  * Report: Print success/failure and relevant order details.

### **Prompt for Phase 3: Core WebSocket Application Structure (`main_app.py`)**

Overview:
"Now, we'll set up the main application script, `main_app.py`, which will host and manage the Alpaca WebSocket connections for real-time market data (CryptoDataStream) and trade updates (CryptoTradeStream). This phase focuses on establishing these connections, handling basic WebSocket lifecycle events (open, message, close, error) by logging them, and subscribing to initial data streams."

**Tasks:**

1. Create `src/main_app.py`.
2. In `main_app.py`:
   * Import necessary Alpaca SDK components (CryptoDataStream, CryptoTradeStream, TradingClient for any initial setup if needed).
   * Load API credentials from `.env`.
   * Define asynchronous handler functions for WebSocket events:
     * `async def on_crypto_quote(q)`: print(f"Quote: {q}") (or similar for trades/bars depending on chosen stream).
     * `async def on_crypto_trade_update(tu)`: print(f"Trade Update: {tu}")
   * Implement a main `async def run_websockets()`: function:
     * Initialize CryptoDataStream and CryptoTradeStream clients.
     * Subscribe CryptoDataStream to quotes (or trades/bars) for a test asset (e.g., 'BTC/USD').
     * Subscribe CryptoTradeStream to trade updates for your account.
     * Start both WebSocket connections (e.g., `data_stream.run()`, `trade_stream.run()` in separate tasks using `asyncio.gather`).
     * Include basic error handling for connection issues and a simple reconnection loop (e.g., retry after a delay).
   * Implement a main execution block: `if __name__ == "__main__": asyncio.run(run_websockets())`.
   * Add signal handling (e.g., for SIGINT, SIGTERM) to gracefully close WebSocket connections and exit.

**Gotchas to Watch For:**

* asyncio programming concepts.
* Ensuring WebSocket clients are run concurrently (e.g., `asyncio.gather`).
* Correctly defining and assigning async handler functions to the stream clients.
* Alpaca's specific WebSocket subscription syntax.
* Robust reconnection logic can be complex; start with a simple retry.

**Functional Tests:**

* (Challenging to unit test live WebSocket interactions directly).
* If you break out handler logic into separate testable functions (e.g., a function that processes a mock quote object), test those.

**Integration Test (`integration_test.py` - new section, likely manual observation for this phase):**

* `test_phase3_websocket_connection_and_data_receipt()`:
  * Scenario: Verify that `main_app.py` connects to Alpaca WebSockets and receives data.
  * Action:
    1. Run `src/main_app.py` manually.
    2. Observe the console output for:
       * Log messages indicating successful connection to both data and trade streams.
       * Regular quote/trade messages for 'BTC/USD'.
    3. Go to the Alpaca paper trading dashboard and manually place a small order for any crypto.
    4. Observe the console output of `main_app.py` for a corresponding trade update message.
    5. Stop `main_app.py` using Ctrl+C and check for graceful shutdown messages.
  * Report: Manually confirm observations. (Automating this fully is advanced and likely out of scope for simple integration tests initially).

This concludes the AI model prompts for all 15 phases of v1.0 development.