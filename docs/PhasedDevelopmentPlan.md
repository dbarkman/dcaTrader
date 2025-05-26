# **DCA Crypto Trading Bot - Phased Development Plan (v1.0)**

This document outlines the development phases for Version 1.0 of the Alpaca DCA Crypto Trading Bot. Each phase is designed to be a manageable block of work, typically corresponding to a Fibonacci complexity of 3 or 5.

## **Core Principles for All Phases:**

* **Pragmatism & KISS:** Always choose the simpler, pragmatic approach.
* **Testing:** Include basic functional tests for new logic. Incrementally build the `integration_test.py` script with scenarios relevant to the completed phase.
* **Modularity:** Organize code into logical modules.
* **Configuration:** Utilize environment variables for sensitive data and configurable parameters.
* **Logging:** Implement comprehensive logging for diagnostics and monitoring.

## **Phase 1: Project Setup & Database Models (Complexity: 3)**

* **Goal:** Establish the basic project structure, database connectivity, and initial data models.
* **Tasks:**
  1. Set up the project directory structure (e.g., `src/`, `tests/`, `scripts/`, `logs/`).
  2. Initialize git repository and create `.gitignore`.
  3. Set up Python virtual environment and initial `requirements.txt` (e.g., python-dotenv, mysql-connector-python).
  4. Create a database utility module (`db_utils.py`) for establishing MySQL connections and executing basic queries (e.g., fetch, execute).
  5. Define Python data classes or simple classes for DcaAsset and DcaCycle to represent data from the `dca_assets` and `dca_cycles` tables.
  6. Implement functions to fetch asset configurations (`dca_assets`) from the database.
  7. Implement functions to fetch/create/update `dca_cycles` entries.
* **Functional Tests:**
  * Test database connection.
  * Test fetching a `dca_assets` record.
  * Test creating and fetching a `dca_cycles` record.
* **Integration Test (`integration_test.py`):**
  * Initial setup: connect to DB, ensure tables exist.
  * Test: Insert a dummy `dca_assets` record, fetch it, assert correctness, then delete it.

## **Phase 2: Alpaca SDK Integration & Basic API Calls (Complexity: 3)**

* **Goal:** Integrate the alpaca-py SDK and confirm basic REST API interactions for fetching account info, market data, and placing a test order.
* **Tasks:**
  1. Add alpaca-py to `requirements.txt`.
  2. Create an Alpaca client utility module (`alpaca_client.py`) to initialize and manage the TradingClient and CryptoDataStream / CryptoTradeStream (or equivalent WebSocket clients from alpaca-py).
  3. Implement functions to:
     * Fetch account information.
     * Fetch current price (latest quote/trade) for a crypto symbol using REST API.
     * Place a small test limit BUY order (using REST API).
     * Fetch open orders (using REST API).
     * Cancel an order (using REST API).
  4. Load Alpaca API keys from `.env` file.
* **Functional Tests:**
  * Test fetching account balance.
  * Test fetching current price for 'BTC/USD'.
* **Integration Test (`integration_test.py`):**
  * Test: Place a very small limit BUY order for a test symbol on paper account, verify it appears in open orders, then cancel it. Ensure it's no longer in open orders.

## **Phase 3: Core WebSocket Application Structure (`main_app.py`) (Complexity: 3)**

* **Goal:** Set up the main application script that will host the WebSocket connections.
* **Tasks:**
  1. Create `main_app.py` (or a similarly named main script).
  2. Implement basic structure for initializing Alpaca WebSocket clients (CryptoDataStream for market data, CryptoTradeStream for trade updates).
  3. Implement connection logic, including reconnection attempts on disconnect for WebSockets.
  4. Implement basic handlers for WebSocket events (e.g., on_open, on_message, on_close, on_error) that log received messages.
  5. Subscribe to market data for one test asset (e.g., 'BTC/USD') and trade updates for the account.
  6. Implement graceful shutdown (e.g., on KeyboardInterrupt).
* **Functional Tests:**
  * (Difficult to unit test WebSocket connections directly here; focus on the handler logic if separable).
* **Integration Test (`integration_test.py`):**
  * (Manual for now) Run `main_app.py` and observe logs to confirm connection to Alpaca WebSockets and receipt of price ticks for the test asset. Manually place an order via Alpaca dashboard and see if trade updates are logged.

## **Phase 4: MarketDataStream - Price Monitoring & Base Order Logic (Complexity: 5)**

* **Goal:** Implement logic within the MarketDataStream handler to monitor prices and trigger new base BUY orders.
* **Tasks:**
  1. In `main_app.py` (or a dedicated `market_data_handler.py`):
     * On receiving a price update:
       * Fetch the relevant `dca_assets` configuration.
       * Fetch the latest `dca_cycles` record for that asset.
       * If `dca_cycles.status` is 'watching' and `dca_cycles.quantity == 0`:
         * **Check Alpaca for existing position for this asset.** If position exists, log warning, send notification (stub for now), and DO NOT proceed.
         * If no existing position, determine if conditions for a base order are met (this is essentially always true if status is 'watching' and quantity is 0, assuming the asset is enabled).
         * Construct a base limit BUY order request (at Ask, time_in_force='day').
         * Place the order using `alpaca_client.py`.
         * **Important:** MarketDataStream does NOT update the database after placing the order. This is TradingStream's responsibility upon fill.
* **Functional Tests:**
  * Test the logic that determines if a base order should be placed (given mock asset config, cycle data, and no Alpaca position).
  * Test order parameter construction.
* **Integration Test (`integration_test.py`):**
  * Scenario: Asset configured, no active cycle (or last cycle 'complete'/'error', new cycle in 'watching' with qty 0), no Alpaca position.
  * Run `main_app.py` (or simulate its MarketDataStream price event handler).
  * Assert: A new limit BUY order is placed on Alpaca.

## **Phase 5: MarketDataStream - Safety Order Logic (Complexity: 5)**

* **Goal:** Implement logic for placing safety BUY orders.
* **Tasks:**
  1. In MarketDataStream handler:
     * If `dca_cycles.status` is 'watching' and `dca_cycles.quantity > 0`:
       * Check if `dca_cycles.safety_orders < dca_assets.max_safety_orders`.
       * Check if `current_market_price <= dca_cycles.last_order_fill_price * (1 - dca_assets.safety_order_deviation / 100)`.
       * If conditions met, construct and place a safety limit BUY order (at Ask, for `dca_assets.safety_order_amount`, time_in_force='day').
* **Functional Tests:**
  * Test safety order condition logic with various price points and last_order_fill_price.
  * Test safety order parameter construction.
* **Integration Test (`integration_test.py`):**
  * Scenario: Active cycle with a base order filled (quantity > 0, last_order_fill_price set). Simulate price drop.
  * Run `main_app.py` (or simulate handler).
  * Assert: A new safety limit BUY order is placed on Alpaca.

## **Phase 6: MarketDataStream - Take-Profit Order Logic (Complexity: 3)**

* **Goal:** Implement logic for placing take-profit SELL orders.
* **Tasks:**
  1. In MarketDataStream handler:
     * If `dca_cycles.status` is 'watching', `dca_cycles.quantity > 0`, and safety order conditions are NOT met:
       * Check if `current_market_price >= dca_cycles.average_purchase_price * (1 + dca_assets.take_profit_percent / 100)`.
       * If condition met, construct and place a take-profit market SELL order for the full `dca_cycles.quantity`.
* **Functional Tests:**
  * Test take-profit condition logic with various price points and average_purchase_price.
* **Integration Test (`integration_test.py`):**
  * Scenario: Active cycle with position, average_purchase_price set. Simulate price rise.
  * Run `main_app.py` (or simulate handler).
  * Assert: A new market SELL order is placed on Alpaca.

## **Phase 7: TradingStream - Handling BUY Order Fills (Complexity: 5)**

* **Goal:** Implement logic within the TradingStream handler to process BUY order fill events.
* **Tasks:**
  1. In `main_app.py` (or a dedicated `trade_update_handler.py`):
     * On receiving a fill or partial_fill event for a BUY order:
       * Fetch the corresponding `dca_cycles` row using event.order.id (if it matches latest_order_id) or by asset if latest_order_id was somehow lost (fallback, log warning).
       * Update `dca_cycles.quantity` (add filled quantity).
       * Recalculate and update `dca_cycles.average_purchase_price`.
       * Update `dca_cycles.last_order_fill_price` with the average fill price of this specific order.
       * If it was a safety order (can be inferred if initial quantity > 0), increment `dca_cycles.safety_orders`.
       * Set `dca_cycles.status` to 'watching'.
       * Update `dca_cycles.latest_order_id` to NULL (as the order is now filled/closed).
       * Handle partial_fill: If order is partially filled, update quantities and prices but keep latest_order_id and status as 'buying' until fully filled or canceled. (Revisit: For simplicity, v1.0 might treat partial fills like full fills for the filled portion and rely on stale order management for the rest, or simply wait for full fill event). Let's simplify: Only act on fill (fully filled) events for now. If a partial_fill comes, log it, but wait for the final fill or canceled event for that order ID.
* **Functional Tests:**
  * Test average_purchase_price calculation logic.
  * Test `dca_cycles` row update logic based on a mock fill event.
* **Integration Test (`integration_test.py`):**
  * Scenario: Place a BUY order (base or safety) that is expected to fill on paper.
  * Run `main_app.py`.
  * Assert: Once filled, `dca_cycles` table is updated correctly (status, quantity, avg_price, last_fill_price, safety_orders count).

## **Phase 8: TradingStream - Handling SELL Order Fills (Complexity: 3)**

* **Goal:** Implement logic for processing take-profit SELL order fill events.
* **Tasks:**
  1. In TradingStream handler:
     * On receiving a fill event for a SELL order:
       * Fetch the corresponding `dca_cycles` row.
       * Set current `dca_cycles.status` to 'complete'.
       * Set `dca_cycles.completed_at` timestamp.
       * Update `dca_assets.last_sell_price` with the fill price of this sell order.
       * Create a *new* `dca_cycles` row for the same asset with status = 'cooldown', quantity = 0, average_purchase_price = 0, safety_orders = 0, latest_order_id = NULL, last_order_fill_price = NULL, completed_at = NULL.
* **Functional Tests:**
  * Test `dca_cycles` update to 'complete' and new 'cooldown' cycle creation.
* **Integration Test (`integration_test.py`):**
  * Scenario: Place a SELL order that is expected to fill.
  * Run `main_app.py`.
  * Assert: `dca_cycles` is marked 'complete', `dca_assets.last_sell_price` updated, and a new 'cooldown' cycle is created.

## **Phase 9: TradingStream - Handling Order Cancellations/Rejections (Complexity: 3)**

* **Goal:** Implement logic for processing order cancellation or rejection events.
* **Tasks:**
  1. In TradingStream handler:
     * On receiving canceled, rejected, expired events for an order linked to a `dca_cycles` row (via latest_order_id):
       * If the cycle status was 'buying' or 'selling':
         * Set `dca_cycles.status` to 'watching'.
         * Set `dca_cycles.latest_order_id` to NULL.
       * Log the event.
     * If an order is canceled and no matching `dca_cycles` row is found (e.g., orphan canceled by `order_manager.py`), log a warning and take no DB action.
* **Functional Tests:**
  * Test `dca_cycles` status update on a mock cancellation event.
* **Integration Test (`integration_test.py`):**
  * Scenario: Place an order, then cancel it via Alpaca API / dashboard before it fills.
  * Run `main_app.py`.
  * Assert: `dca_cycles.status` is set to 'watching', latest_order_id is NULL.

## **Phase 10: Caretaker Script - `order_manager.py` (Complexity: 5)**

* **Goal:** Create the script to manage stale and orphaned Alpaca orders.
* **Tasks:**
  1. Create `scripts/order_manager.py`.
  2. Implement logic to:
     * Fetch all open orders from Alpaca created by the bot (can filter by client_order_id prefix if used, or fetch all and identify).
     * For Stale BUY Order Management:
       * Identify bot's open BUY limit orders older than 5 minutes (query orders created in last ~10 minutes).
       * If found, cancel them via Alpaca API. (The TradingStream will then pick up the cancellation event and update DB).
     * For Orphaned Alpaca Order Management:
       * Identify bot's open Alpaca orders (BUY or SELL) older than 5 minutes that do *not* correspond to an active (status='buying' or 'selling') `dca_cycles` row via latest_order_id.
       * If found, cancel them via Alpaca API.
  3. Ensure script uses DB utils and Alpaca client utils.
  4. Add logging.
* **Functional Tests:**
  * Test logic for identifying stale orders from a list of mock orders.
  * Test logic for identifying orphaned orders.
* **Integration Test (`integration_test.py`):**
  * Scenario Stale: Create a BUY limit order far from market price. Wait >5 mins. Run `order_manager.py`. Assert order is canceled on Alpaca.
  * Scenario Orphan: Manually create an order on Alpaca. Run `order_manager.py`. Assert order is canceled.

## **Phase 11: Caretaker Script - `cooldown_manager.py` (Complexity: 3)**

* **Goal:** Create the script to manage asset cooldown periods.
* **Tasks:**
  1. Create `scripts/cooldown_manager.py`.
  2. Implement logic to:
     * Fetch all `dca_cycles` rows with status = 'cooldown'.
     * For each, get its asset_id and fetch the `dca_assets` config and the *previous* cycle for that asset (the one with status='complete' or 'error' that triggered this cooldown).
     * Check if `dca_assets.cooldown_period` has expired relative to the completed_at timestamp of the *previous* cycle.
     * If expired, update the current 'cooldown' `dca_cycles.status` to 'watching'.
  3. Add logging.
* **Functional Tests:**
  * Test cooldown expiry logic with mock cycle data and timestamps.
* **Integration Test (`integration_test.py`):**
  * Scenario: Manually set a cycle to 'complete' with a recent completed_at, and create a 'cooldown' cycle for it. Set cooldown_period to a short time (e.g., 60s). Wait >60s. Run `cooldown_manager.py`. Assert 'cooldown' cycle status changes to 'watching'.

## **Phase 12: Caretaker Script - `consistency_checker.py` (Complexity: 5)**

* **Goal:** Create the script to ensure consistency between DB state and Alpaca.
* **Tasks:**
  1. Create `scripts/consistency_checker.py`.
  2. Implement logic:
     * Scenario 1: `dca_cycles.status` is 'buying'.
       * Query Alpaca for an open BUY order matching `dca_cycles.latest_order_id`.
       * If no such active order (or it's >5min old), set `dca_cycles.status` to 'watching'.
     * Scenario 2: `dca_cycles.status` is 'watching' AND `dca_cycles.quantity > 0`.
       * Query Alpaca for current position for that asset.
       * If Alpaca reports no position (or zero quantity):
         * Set current `dca_cycles.status` to 'error' and populate completed_at.
         * Create a new `dca_cycles` row for that asset: quantity=0, average_purchase_price=0, safety_orders=0, status='watching', latest_order_id=NULL, completed_at=NULL.
  3. Add logging.
* **Functional Tests:**
  * Test logic for Scenario 1 with mock data.
  * Test logic for Scenario 2 with mock data.
* **Integration Test (`integration_test.py`):**
  * Scenario 1: Set DB cycle to 'buying' with a fake latest_order_id. Run `consistency_checker.py`. Assert status changes to 'watching'.
  * Scenario 2: Set DB cycle to 'watching' with quantity > 0. Ensure no Alpaca position. Run `consistency_checker.py`. Assert old cycle is 'error' and new 'watching' cycle is created.

## **Phase 13: `watchdog.py` Script (Complexity: 3)**

* **Goal:** Create a watchdog script to monitor and restart the main WebSocket application.
* **Tasks:**
  1. Create `scripts/watchdog.py`.
  2. Implement logic to:
     * Check if the `main_app.py` process is running (e.g., by PID file or process name).
     * If not running, attempt to restart it.
     * Log actions.
     * Optional: Send email alert on failure to start or on successful restart after failure (requires email sending utility).
* **Functional Tests:** (Difficult to unit test process management directly; focus on helper functions if any).
* **Integration Test (`integration_test.py`):**
  * (Manual for now) Start `main_app.py`. Kill it. Run `watchdog.py`. Observe if it restarts `main_app.py`.

## **Phase 14: Configuration, Logging, and Error Handling (Complexity: 3)**

* **Goal:** Ensure robust configuration management, comprehensive logging, and graceful error handling throughout the application.
* **Tasks:**
  1. Standardize use of python-dotenv for all configurations.
  2. Implement structured logging (e.g., INFO, WARNING, ERROR levels) across all modules and scripts. Log to console and files.
  3. Review all components for try-except blocks for expected errors (API errors, DB errors, network issues).
  4. Implement a basic email alert utility if desired for critical errors or watchdog events.
* **Functional Tests:**
  * Test error handling in key functions (e.g., mock an API error and check if it's caught).
* **Integration Test (`integration_test.py`):**
  * Review logs produced during other integration tests for clarity and completeness.

## **Phase 15: Final Integration Testing & Refinement (Complexity: 5)**

* **Goal:** Conduct comprehensive integration testing of the entire v1.0 system, refine logic, and prepare for deployment.
* **Tasks:**
  1. Expand `integration_test.py` to cover more complex scenarios and edge cases.
  2. Run the bot for an extended period on a paper trading account.
  3. Monitor logs, database state, and Alpaca account activity closely.
  4. Identify and fix any bugs or logical inconsistencies.
  5. Review and update documentation (`README.md`).
  6. Prepare `requirements.txt` with pinned versions.
* **Functional Tests:** N/A (focus is on integration).
* **Integration Test (`integration_test.py`):** This phase *is* the integration testing.