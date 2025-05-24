# **DCA Crypto Trading Bot \- AI Model Prompts for Development Phases (v1.0)**

This document provides specific prompts for an AI coding assistant for each development phase of the DCA Crypto Trading Bot.

## **General Instructions for the AI Model (Include with each prompt):**

* **Primary Goal:** Implement the features for the current phase as described.  
* **Development Principles:**  
  * **Pragmatism & KISS:** Always prioritize the simplest, most straightforward solution that meets requirements. Avoid over-engineering.  
  * **Modularity:** Organize code into logical functions and modules.  
  * **Clarity:** Write clean, readable, and well-commented Python code.  
* **Testing:**  
  * **Functional Tests:** Write basic, pragmatic functional tests for any new, non-trivial logic. Focus on testing the core behavior, not exhaustive edge cases unless critical.  
  * **Integration Test Script (integration\_test.py):** Add a new test function to integration\_test.py that specifically tests the features implemented in *this phase*. This test should:  
    * Clearly state the scenario being tested (verbose print statements).  
    * Perform necessary setup in the database and/or Alpaca paper account.  
    * Execute the relevant part of the bot's logic (e.g., call a caretaker script, simulate a WebSocket event by calling its handler).  
    * Make assertions about the outcome (e.g., database state changes, orders appearing/disappearing on Alpaca).  
    * Report findings clearly.  
    * Include teardown if necessary to clean up (e.g., delete test orders/positions, truncate test data from DB).  
* **Error Handling:** Implement basic try-except blocks for expected I/O operations (network calls, DB access).  
* **Logging:** Use Python's logging module. Add informative log messages (INFO for general operations, WARNING for potential issues, ERROR for failures).  
* **Environment Variables:** Use python-dotenv and a .env file for configurations like API keys and database credentials. Refer to README.md for expected variables.  
* **Database Interaction:** Assume utility functions for database connections and queries will be available (as developed in Phase 1).  
* **Alpaca Interaction:** Assume utility functions/classes for Alpaca client initialization and basic API calls will be available (as developed in Phase 2).  
* **Iterative Refinement:** After generating the code, you will be asked to "run the test suite (functional and the new integration test scenario), observe the results, and debug any issues until all tests for this phase are passing."

### **Prompt for Phase 1: Project Setup & Database Models**

Overview:  
"We are starting a new Python project: a Dollar Cost Averaging (DCA) trading bot for Alpaca. This first phase focuses on setting up the basic project structure, establishing database connectivity with MySQL/MariaDB, and creating Python representations for our core database tables: dca\_assets (for asset configurations) and dca\_cycles (for tracking individual trading cycles). Refer to the README.md for the exact schemas of these tables."  
**Tasks:**

1. Create the standard project directory structure: src/ (for main source code), src/utils/ (for utilities), src/models/ (for data models), scripts/ (for caretaker scripts \- will be populated later), tests/ (for functional tests), logs/ (will be used for log files).  
2. Create an initial .gitignore file (e.g., for venv/, \_\_pycache\_\_/, .env, logs/\*.log).  
3. Create an initial requirements.txt file including python-dotenv and mysql-connector-python.  
4. In src/utils/db\_utils.py:  
   * Implement get\_db\_connection(): Connects to MySQL using credentials from .env and returns a connection object.  
   * Implement execute\_query(query, params=None, fetch\_one=False, fetch\_all=False, commit=False): Executes a given SQL query. Handles params for parameterized queries. Can fetch one row, all rows, or just execute (e.g., INSERT, UPDATE) and commit.  
5. In src/models/asset\_config.py:  
   * Define a Python class DcaAsset that mirrors the columns of the dca\_assets table. Include type hints.  
   * Implement a function get\_asset\_config(db\_conn, asset\_symbol: str) \-\> DcaAsset | None: Fetches an asset's configuration by its symbol.  
   * Implement get\_all\_enabled\_assets(db\_conn) \-\> list\[DcaAsset\]: Fetches all enabled assets.  
6. In src/models/cycle\_data.py:  
   * Define a Python class DcaCycle that mirrors the columns of the dca\_cycles table. Include type hints.  
   * Implement get\_latest\_cycle(db\_conn, asset\_id: int) \-\> DcaCycle | None: Fetches the most recent cycle for a given asset\_id (order by id DESC or created\_at DESC, limit 1).  
   * Implement create\_cycle(db\_conn, asset\_id: int, status: str, quantity: Decimal \= Decimal(0), ...) \-\> DcaCycle: Inserts a new cycle record and returns the created DcaCycle object (including its new id and created\_at from DB).  
   * Implement update\_cycle(db\_conn, cycle\_id: int, updates: dict) \-\> bool: Updates specified fields of a cycle. updates is a dictionary of column\_name: new\_value.

**Gotchas to Watch For:**

* Ensure database connection details are loaded correctly from .env.  
* Handle potential None results gracefully when fetching data.  
* Use parameterized queries to prevent SQL injection.  
* Remember Decimal type for financial values.

**Functional Tests (in tests/):**

* test\_db\_connection(): Checks if get\_db\_connection() successfully connects.  
* test\_get\_asset\_config(): Mocks DB call or uses test DB to verify fetching an asset.  
* test\_create\_and\_get\_cycle(): Tests creating a cycle and then fetching it to verify data.

**Integration Test (integration\_test.py \- new function):**

* test\_phase1\_asset\_and\_cycle\_crud():  
  * Scenario: Basic Create, Read, Update, Delete (CRUD-like) operations for dca\_assets and dca\_cycles using the functions you built.  
  * Setup: Connect to the (paper) test database.  
  * Action:  
    1. Insert a test dca\_assets record directly via SQL or a helper if you build one (e.g., for testing get\_asset\_config).  
    2. Call get\_asset\_config() for the test asset and assert the returned data is correct.  
    3. Call create\_cycle() for this test asset. Assert the returned object has an ID and correct initial values.  
    4. Call get\_latest\_cycle() and assert it matches the created cycle.  
    5. Call update\_cycle() to change the status, then fetch again and assert the update.  
  * Teardown: Delete the test dca\_cycles and dca\_assets records.  
  * Report: Print success/failure and any relevant data.

### **Prompt for Phase 2: Alpaca SDK Integration & Basic API Calls**

Overview:  
"This phase involves integrating the alpaca-py SDK into our project. We need to establish a client for interacting with Alpaca's REST API, load API keys securely, and implement basic functions to fetch account information, market data (price), place a test order, fetch open orders, and cancel an order. This will primarily be in a new utility module."  
**Tasks:**

1. Add alpaca-py to requirements.txt.  
2. Create src/utils/alpaca\_client\_rest.py (to distinguish from future WebSocket client wrappers if any).  
3. In alpaca\_client\_rest.py:  
   * Implement get\_trading\_client() \-\> TradingClient: Initializes and returns an Alpaca TradingClient using API key/secret/URL from .env.  
   * Implement get\_account\_info(client: TradingClient) \-\> Account | None.  
   * Implement get\_latest\_crypto\_price(client: TradingClient, symbol: str) \-\> float | None: Fetches the latest trade price for a crypto symbol (e.g., using client.get\_latest\_crypto\_trade()). Handle cases where price data might not be immediately available.  
   * Implement place\_limit\_buy\_order(client: TradingClient, symbol: str, qty: float, limit\_price: float, time\_in\_force: str \= 'day') \-\> Order | None.  
   * Implement get\_open\_orders(client: TradingClient) \-\> list\[Order\].  
   * Implement cancel\_order(client: TradingClient, order\_id: str) \-\> bool. Returns True if cancellation is successful (or acknowledged).

**Gotchas to Watch For:**

* Alpaca API endpoints and SDK function names/parameters.  
* Error handling for API requests (e.g., invalid symbol, insufficient funds \- though not explicitly handled by placing an order yet, be mindful of potential errors).  
* Rate limits (not an issue for these basic calls, but good to be aware of Alpaca's policies).  
* Ensure correct symbol format (e.g., 'BTC/USD').

**Functional Tests (in tests/):**

* test\_get\_trading\_client\_initialization(): Mocks .env and checks client creation.  
* Mock Alpaca client responses to test:  
  * test\_get\_account\_info\_parsing().  
  * test\_get\_latest\_crypto\_price\_parsing().

**Integration Test (integration\_test.py \- new function):**

* test\_phase2\_alpaca\_rest\_api\_order\_cycle():  
  * Scenario: Test the full cycle of placing, viewing, and canceling an order via REST API on the Alpaca paper account.  
  * Setup: Initialize TradingClient. Use a non-critical, low-value test symbol if possible, or BTC/USD with a very small quantity and a price far from the market to prevent accidental fills for this specific test.  
  * Action:  
    1. Call get\_account\_info() and print some details (e.g., buying power).  
    2. Call get\_latest\_crypto\_price() for 'BTC/USD' and print it.  
    3. Call place\_limit\_buy\_order() for a very small quantity of 'BTC/USD' (e.g., 0.0001) at a price significantly below the current market (e.g., $1000). Store the returned order object. Assert an order object is returned.  
    4. Call get\_open\_orders(). Iterate through them and find the order placed in step 3 by its ID. Assert it's found and its status is 'new' or 'accepted'.  
    5. Call cancel\_order() using the order ID. Assert it returns True or successfully processes.  
    6. Call get\_open\_orders() again. Assert the canceled order is no longer present or its status is 'canceled'.  
  * Report: Print success/failure and relevant order details.

*(Prompts for subsequent phases will follow a similar structure, detailing tasks, gotchas, functional tests, and integration test scenarios specific to the features of that phase. I will continue this pattern for all 15 phases.)*

### **Prompt for Phase 3: Core WebSocket Application Structure (main\_app.py)**

Overview:  
"Now, we'll set up the main application script, main\_app.py, which will host and manage the Alpaca WebSocket connections for real-time market data (CryptoDataStream) and trade updates (CryptoTradeStream). This phase focuses on establishing these connections, handling basic WebSocket lifecycle events (open, message, close, error) by logging them, and subscribing to initial data streams."  
**Tasks:**

1. Create src/main\_app.py.  
2. In main\_app.py:  
   * Import necessary Alpaca SDK components (CryptoDataStream, CryptoTradeStream, TradingClient for any initial setup if needed).  
   * Load API credentials from .env.  
   * Define asynchronous handler functions for WebSocket events:  
     * async def on\_crypto\_quote(q): print(f"Quote: {q}") (or similar for trades/bars depending on chosen stream).  
     * async def on\_crypto\_trade\_update(tu): print(f"Trade Update: {tu}")  
   * Implement a main async def run\_websockets(): function:  
     * Initialize CryptoDataStream and CryptoTradeStream clients.  
     * Subscribe CryptoDataStream to quotes (or trades/bars) for a test asset (e.g., 'BTC/USD').  
     * Subscribe CryptoTradeStream to trade updates for your account.  
     * Start both WebSocket connections (e.g., data\_stream.run(), trade\_stream.run() in separate tasks using asyncio.gather).  
     * Include basic error handling for connection issues and a simple reconnection loop (e.g., retry after a delay).  
   * Implement a main execution block: if \_\_name\_\_ \== "\_\_main\_\_": asyncio.run(run\_websockets()).  
   * Add signal handling (e.g., for SIGINT, SIGTERM) to gracefully close WebSocket connections and exit.

**Gotchas to Watch For:**

* asyncio programming concepts.  
* Ensuring WebSocket clients are run concurrently (e.g., asyncio.gather).  
* Correctly defining and assigning async handler functions to the stream clients.  
* Alpaca's specific WebSocket subscription syntax.  
* Robust reconnection logic can be complex; start with a simple retry.

**Functional Tests:**

* (Challenging to unit test live WebSocket interactions directly).  
* If you break out handler logic into separate testable functions (e.g., a function that processes a mock quote object), test those.

**Integration Test (integration\_test.py \- new section, likely manual observation for this phase):**

* test\_phase3\_websocket\_connection\_and\_data\_receipt():  
  * Scenario: Verify that main\_app.py connects to Alpaca WebSockets and receives data.  
  * Action:  
    1. Run src/main\_app.py manually.  
    2. Observe the console output for:  
       * Log messages indicating successful connection to both data and trade streams.  
       * Regular quote/trade messages for 'BTC/USD'.  
    3. Go to the Alpaca paper trading dashboard and manually place a small order for any crypto.  
    4. Observe the console output of main\_app.py for a corresponding trade update message.  
    5. Stop main\_app.py using Ctrl+C and check for graceful shutdown messages.  
  * Report: Manually confirm observations. (Automating this fully is advanced and likely out of scope for simple integration tests initially).

### **Prompt for Phase 4: MarketDataStream \- Price Monitoring & Base Order Logic**

Overview:  
"This phase implements the core logic in the MarketDataStream handler (within main\_app.py or a dedicated module it calls) to monitor incoming crypto prices. When conditions are met for a new base order (asset is 'watching', quantity is 0, and crucially, no existing Alpaca position for that asset), it will place a limit BUY order. The database is NOT updated by this stream; that's TradingStream's job upon fill."  
**Tasks:**

1. Modify the MarketDataStream message handler (e.g., on\_crypto\_quote or on\_crypto\_trade in main\_app.py or a new src/market\_data\_handler.py).  
2. Inside the handler, upon receiving a price update for an asset:  
   * Get a DB connection (from db\_utils).  
   * Fetch the DcaAsset configuration for the symbol (from asset\_config.py). If not configured or not enabled, ignore.  
   * Fetch the latest DcaCycle for this asset\_id (from cycle\_data.py). If no cycle, or if the asset is not in a state to buy (e.g., not 'watching'), ignore.  
   * **If latest\_cycle.status \== 'watching' and latest\_cycle.quantity \== Decimal(0):**  
     * Initialize an Alpaca TradingClient (from alpaca\_client\_rest.py).  
     * **Crucial Check:** Call Alpaca API to get current positions. Check if a position already exists for this asset\_symbol.  
     * If an Alpaca position **exists**:  
       * Log a detailed WARNING message (e.g., "Base order for {symbol} skipped, existing position found on Alpaca.").  
       * (Future: Send notification).  
       * Do NOT place an order.  
     * If no Alpaca position **exists**:  
       * Determine the limit price (e.g., current Ask price from the quote, or latest trade price if using trade stream). Be careful if using trade price as it might not be fillable. Using Ask from quote is safer for limit BUYs.  
       * Use alpaca\_client\_rest.place\_limit\_buy\_order() to place the base order for dca\_asset.base\_order\_amount (USD value needs to be converted to crypto quantity based on price), time\_in\_force='day'.  
       * Log the action (e.g., "Base BUY order placed for {symbol} at {price} for quantity {qty}.").  
       * **Important:** This stream does *not* update dca\_cycles.latest\_order\_id or status.

**Gotchas to Watch For:**

* Converting USD base\_order\_amount to crypto quantity: quantity \= base\_order\_amount\_usd / limit\_price. Handle potential division by zero if price is missing.  
* Ensuring the "check for existing Alpaca position" is robust.  
* Asynchronous handling: DB calls and REST API calls from within the async WebSocket handler should be done carefully (e.g., run synchronous blocking calls in an executor if they are not already async-compatible, or use an async DB library if chosen). For mysql-connector-python and alpaca-py REST calls, they are typically blocking. asyncio.to\_thread can be used.  
* Getting a reliable Ask price from the WebSocket stream (quotes stream is better than trades for this).

**Functional Tests (in tests/):**

* test\_base\_order\_conditions\_met(): Given mock asset, cycle (watching, qty 0), no Alpaca position (mocked), and price data, assert base order logic proceeds.  
* test\_base\_order\_skipped\_if\_position\_exists(): Mock an existing Alpaca position; assert order is skipped.  
* test\_base\_order\_usd\_to\_qty\_conversion().

**Integration Test (integration\_test.py \- new function):**

* test\_phase4\_marketdata\_places\_base\_order():  
  * Scenario: An asset is configured in dca\_assets, its latest cycle in dca\_cycles is status='watching' and quantity=0. No existing position for this asset on Alpaca paper account.  
  * Setup:  
    1. Ensure the test asset (e.g., 'BTC/USD') is in dca\_assets and enabled.  
    2. Manually insert/update dca\_cycles for this asset: status='watching', quantity=0, asset\_id links to your test asset.  
    3. Ensure no 'BTC/USD' position exists in your Alpaca paper account.  
  * Action:  
    1. Run src/main\_app.py.  
    2. Wait for a price tick for 'BTC/USD' to be processed by the MarketDataStream handler. (You might need to observe logs or have a way to know the event was processed).  
  * Assert:  
    1. A new limit BUY order for the base amount of 'BTC/USD' appears in your Alpaca paper account's open orders.  
    2. The dca\_cycles table for this asset should *not* have its status or latest\_order\_id changed by MarketDataStream.  
  * Teardown: Manually cancel the test order from Alpaca. Clean up DB entries if necessary.  
  * Report: Print success/failure and observed order details.

## ***(Continuing this pattern for all 15 phases. Each prompt will be self-contained with the general instructions and phase-specific details.)***

### **Prompt for Phase 5: MarketDataStream \- Safety Order Logic**

Overview:  
"This phase extends the MarketDataStream handler to implement logic for placing safety BUY orders. This occurs if an asset is 'watching', has an existing quantity (meaning a base order or previous safety order filled), is below the max safety order count, and the price drops by the configured safety\_order\_deviation from the last\_order\_fill\_price."  
**Tasks:**

1. In the MarketDataStream message handler (e.g., on\_crypto\_quote in main\_app.py or src/market\_data\_handler.py):  
   * After fetching dca\_asset and latest\_cycle, if latest\_cycle.status \== 'watching' and latest\_cycle.quantity \> Decimal(0):  
     * Check if latest\_cycle.safety\_orders \< dca\_asset.max\_safety\_orders:  
       * Calculate the trigger price: trigger\_price \= latest\_cycle.last\_order\_fill\_price \* (1 \- dca\_asset.safety\_order\_deviation / 100).  
       * Get current market price (e.g., Bid price from quote for selling, Ask for buying; for safety BUY, use Ask or latest trade). Let's assume current\_ask\_price.  
       * **If current\_ask\_price \<= trigger\_price:**  
         * Initialize TradingClient.  
         * Convert dca\_asset.safety\_order\_amount (USD) to crypto quantity using current\_ask\_price.  
         * Use alpaca\_client\_rest.place\_limit\_buy\_order() to place the safety order.  
         * Log the action (e.g., "Safety BUY order placed for {symbol}...").  
         * MarketDataStream does NOT update the database.

**Gotchas to Watch For:**

* Ensure last\_order\_fill\_price is correctly populated in dca\_cycles (this will be TradingStream's job, but the logic here depends on it).  
* Correct calculation of trigger\_price and USD to crypto quantity conversion.  
* Using an appropriate market price (Ask) for placing the limit BUY order.

**Functional Tests (in tests/):**

* test\_safety\_order\_conditions\_met(): Mock asset, cycle (watching, qty \> 0, last\_order\_fill\_price set, safety\_orders \< max), and price data. Assert safety order logic proceeds.  
* test\_safety\_order\_conditions\_not\_met\_max\_orders(): Test when safety\_orders \== max\_safety\_orders.  
* test\_safety\_order\_conditions\_not\_met\_price\_not\_low\_enough().  
* test\_safety\_order\_trigger\_price\_calculation().

**Integration Test (integration\_test.py \- new function):**

* test\_phase5\_marketdata\_places\_safety\_order():  
  * Scenario: An asset has an active cycle with a base order filled. The price then drops enough to trigger a safety order.  
  * Setup:  
    1. Asset in dca\_assets.  
    2. dca\_cycles row: status='watching', quantity \> 0 (e.g., from a simulated base order), average\_purchase\_price set, last\_order\_fill\_price set (e.g., to $50000 for BTC/USD), safety\_orders \= 0, max\_safety\_orders \> 0\.  
    3. safety\_order\_deviation in dca\_assets (e.g., 1.0 for 1%).  
  * Action:  
    1. Run src/main\_app.py.  
    2. Simulate a price tick where the Ask price drops below last\_order\_fill\_price \* (1 \- safety\_order\_deviation / 100). (This might be hard to time perfectly with live data; consider if the test can temporarily modify the last\_order\_fill\_price in DB to force a trigger with current market, or if the test logic can directly invoke the handler with a crafted price event).  
  * Assert:  
    1. A new safety limit BUY order appears in Alpaca paper account.  
    2. dca\_cycles table is NOT updated by MarketDataStream.  
  * Teardown: Cancel test order. Clean DB.  
  * Report: Print success/failure.

### **Prompt for Phase 6: MarketDataStream \- Take-Profit Order Logic**

Overview:  
"This phase adds the take-profit logic to the MarketDataStream handler. If an asset is 'watching', has a position, safety order conditions are NOT met, and the current price rises above the take-profit threshold (based on average\_purchase\_price), a market SELL order for the entire position is placed."  
**Tasks:**

1. In the MarketDataStream message handler, if latest\_cycle.status \== 'watching', latest\_cycle.quantity \> Decimal(0), AND safety order conditions (from Phase 5\) were NOT met:  
   * Calculate the take-profit price: take\_profit\_trigger\_price \= latest\_cycle.average\_purchase\_price \* (1 \+ dca\_asset.take\_profit\_percent / 100).  
   * Get current market price (e.g., Bid price from quote for selling). Let's assume current\_bid\_price.  
   * **If current\_bid\_price \>= take\_profit\_trigger\_price:**  
     * Initialize TradingClient.  
     * Use a new function in alpaca\_client\_rest.py: place\_market\_sell\_order(client: TradingClient, symbol: str, qty: float, time\_in\_force: str \= 'day') \-\> Order | None.  
     * Place the market SELL order for latest\_cycle.quantity.  
     * Log the action.  
     * MarketDataStream does NOT update the database.

**Gotchas to Watch For:**

* Using average\_purchase\_price for take-profit calculation.  
* Using an appropriate market price (Bid) for evaluating sell conditions.  
* Ensuring the SELL order is for the correct total quantity held in the cycle.  
* Market orders can have slippage; this is accepted for v1.0.

**Functional Tests (in tests/):**

* test\_take\_profit\_conditions\_met(): Mock asset, cycle (watching, qty \> 0, average\_purchase\_price set), and price data. Assert take-profit logic proceeds.  
* test\_take\_profit\_conditions\_not\_met\_price\_not\_high\_enough().  
* test\_take\_profit\_trigger\_price\_calculation().

**Integration Test (integration\_test.py \- new function):**

* test\_phase6\_marketdata\_places\_take\_profit\_order():  
  * Scenario: Asset has an active cycle with a position. Price rises to trigger take-profit.  
  * Setup:  
    1. Asset in dca\_assets.  
    2. dca\_cycles row: status='watching', quantity \> 0, average\_purchase\_price set (e.g., to $50000 for BTC/USD).  
    3. take\_profit\_percent in dca\_assets (e.g., 1.0 for 1%).  
  * Action:  
    1. Run src/main\_app.py.  
    2. Simulate a price tick where Bid price rises above average\_purchase\_price \* (1 \+ take\_profit\_percent / 100). (Similar timing challenges as safety order; consider options).  
  * Assert:  
    1. A new market SELL order for the cycle's quantity appears in Alpaca.  
    2. dca\_cycles table is NOT updated by MarketDataStream.  
  * Teardown: If order doesn't fill immediately, cancel it. Clean DB. (Market orders on paper usually fill quickly).  
  * Report: Print success/failure.

### **Prompt for Phase 7: TradingStream \- Handling BUY Order Fills**

Overview:  
"Now we focus on the TradingStream handler. When it receives a trade update event indicating a BUY order (base or safety) has been fully filled, it must update the corresponding dca\_cycles row in the database with the new quantity, recalculated average\_purchase\_price, the last\_order\_fill\_price from this specific fill, increment safety order count if applicable, and set status to 'watching'. latest\_order\_id is cleared."  
**Tasks:**

1. Modify the CryptoTradeStream message handler (e.g., on\_crypto\_trade\_update in main\_app.py or src/trade\_update\_handler.py).  
2. Inside the handler, if event.event \== 'fill' and event.order.side \== 'buy':  
   * Get a DB connection.  
   * Fetch the dca\_cycles row where latest\_order\_id \== event.order.id. If not found, log error and skip.  
   * Fetch the dca\_assets config for this cycle's asset\_id.  
   * filled\_qty \= Decimal(event.order.filled\_qty)  
   * avg\_fill\_price \= Decimal(event.order.filled\_avg\_price)  
   * current\_total\_qty \= latest\_cycle.quantity \+ filled\_qty  
   * new\_average\_purchase\_price \= ((latest\_cycle.average\_purchase\_price \* latest\_cycle.quantity) \+ (avg\_fill\_price \* filled\_qty)) / current\_total\_qty (if current\_total\_qty \> 0, else avg\_fill\_price). Handle initial buy where latest\_cycle.quantity is 0\.  
   * updates \= {  
     * 'quantity': current\_total\_qty,  
     * 'average\_purchase\_price': new\_average\_purchase\_price,  
     * 'last\_order\_fill\_price': avg\_fill\_price,  
     * 'status': 'watching',  
     * 'latest\_order\_id': None  
     * }  
   * If latest\_cycle.quantity \> Decimal(0) before this fill (i.e., it was a safety order, not a base order):  
     * updates\['safety\_orders'\] \= latest\_cycle.safety\_orders \+ 1  
   * Call update\_cycle(db\_conn, latest\_cycle.id, updates).  
   * Log the update.  
   * **Simplification for v1.0:** We are only processing event.event \== 'fill'. partial\_fill events will be logged but not change DB state until the final fill or canceled event for that order ID.

**Gotchas to Watch For:**

* Correctly identifying the cycle based on event.order.id.  
* Accurate calculation of the new weighted average\_purchase\_price.  
* Differentiating between a base order fill and a safety order fill to update safety\_orders count.  
* Using Decimal for all financial calculations.  
* Ensuring latest\_order\_id is set to None after a fill.

**Functional Tests (in tests/):**

* test\_buy\_fill\_updates\_cycle\_base\_order(): Mock cycle (qty 0), mock fill event. Assert correct updates to qty, avg\_price, last\_fill\_price, status, safety\_orders (should be 0 or not incremented).  
* test\_buy\_fill\_updates\_cycle\_safety\_order(): Mock cycle (qty \> 0), mock fill event. Assert correct updates, especially safety\_orders incremented.  
* test\_average\_purchase\_price\_recalculation\_logic().

**Integration Test (integration\_test.py \- new function):**

* test\_phase7\_tradingstream\_processes\_buy\_fill():  
  * Scenario: A BUY order (can be base or safety) placed by MarketDataStream (or manually for test isolation) gets filled on Alpaca.  
  * Setup:  
    1. Ensure an asset is configured. Place a BUY limit order for it on Alpaca paper that is likely to fill (e.g., at current Ask or slightly above).  
    2. Manually create/update a dca\_cycles row: status='buying', latest\_order\_id set to the ID of the order you just placed. Store initial quantity, average\_purchase\_price, safety\_orders.  
  * Action:  
    1. Run src/main\_app.py.  
    2. Wait for the order to fill on Alpaca and for TradingStream to process the fill event.  
  * Assert:  
    1. Query dca\_cycles for the test cycle.  
    2. Verify status is 'watching'.  
    3. Verify quantity has increased by the filled amount.  
    4. Verify average\_purchase\_price is correctly recalculated.  
    5. Verify last\_order\_fill\_price is the fill price of this order.  
    6. Verify safety\_orders count is updated if it was a safety order.  
    7. Verify latest\_order\_id is None.  
  * Report: Print success/failure and DB state changes.

### **Prompt for Phase 8: TradingStream \- Handling SELL Order Fills**

Overview:  
"This phase focuses on TradingStream processing successful take-profit SELL order fills. When a fill event for a SELL order comes through, the current cycle is marked 'complete', its completed\_at timestamp is set, dca\_assets.last\_sell\_price is updated, and a new dca\_cycles row is immediately created for the same asset with status='cooldown'."  
**Tasks:**

1. In the CryptoTradeStream message handler, if event.event \== 'fill' and event.order.side \== 'sell':  
   * Get a DB connection.  
   * Fetch the dca\_cycles row where latest\_order\_id \== event.order.id. If not found, log error.  
   * Fetch the dca\_assets config for this cycle's asset\_id.  
   * avg\_fill\_price \= Decimal(event.order.filled\_avg\_price)  
   * **Update current cycle:**  
     * updates\_current \= {  
       * 'status': 'complete',  
       * 'completed\_at': datetime.utcnow(), \# Or DB function for current timestamp  
       * 'latest\_order\_id': None  
       * }  
     * Call update\_cycle(db\_conn, latest\_cycle.id, updates\_current).  
   * **Update dca\_assets:**  
     * In src/models/asset\_config.py, add update\_asset\_config(db\_conn, asset\_id: int, updates: dict).  
     * Call update\_asset\_config(db\_conn, dca\_asset.id, {'last\_sell\_price': avg\_fill\_price}).  
   * **Create new 'cooldown' cycle:**  
     * Call create\_cycle(db\_conn, asset\_id=dca\_asset.id, status='cooldown', quantity=Decimal(0), average\_purchase\_price=Decimal(0), safety\_orders=0, latest\_order\_id=None, last\_order\_fill\_price=None, completed\_at=None).  
   * Log the completion and new cycle creation.

**Gotchas to Watch For:**

* Ensuring the correct cycle is marked 'complete'.  
* Atomicity: Ideally, these three updates (current cycle, asset config, new cycle) should be atomic. For v1.0, separate calls are acceptable, but be aware of potential partial updates if one fails. A transaction block in db\_utils.execute\_query or TradingStream handler would be better if feasible.  
* Setting completed\_at timestamp correctly.  
* Resetting all relevant fields for the new 'cooldown' cycle.

**Functional Tests (in tests/):**

* test\_sell\_fill\_completes\_cycle\_and\_creates\_cooldown\_cycle(): Mock cycle, mock SELL fill event. Assert current cycle is updated to 'complete', and mock create\_cycle is called with correct 'cooldown' parameters. Mock update\_asset\_config is called.

**Integration Test (integration\_test.py \- new function):**

* test\_phase8\_tradingstream\_processes\_sell\_fill():  
  * Scenario: A take-profit SELL order gets filled.  
  * Setup:  
    1. Asset configured. Place a SELL market order for an asset you "hold" on paper (you might need to do a quick paper BUY first if no position).  
    2. Manually create/update dca\_cycles: status='selling', latest\_order\_id to your SELL order's ID, quantity \> 0\.  
    3. Store initial dca\_assets.last\_sell\_price.  
  * Action:  
    1. Run src/main\_app.py.  
    2. Wait for the SELL order to fill and TradingStream to process.  
  * Assert:  
    1. Original dca\_cycles row: status is 'complete', completed\_at is set, latest\_order\_id is None.  
    2. dca\_assets.last\_sell\_price is updated to the fill price.  
    3. A *new* dca\_cycles row exists for the same asset with status='cooldown', quantity=0, etc.  
  * Report: Print success/failure and DB state changes.

*(Continuing this pattern for all 15 phases)*  
This detailed structure should provide the AI with very clear instructions for each step. I will proceed to generate the prompts for the remaining phases following this template.  
Due to the extensive nature of generating detailed prompts for all 15 phases, I will provide the prompts for phases 9 through 15 now.

### **Prompt for Phase 9: TradingStream \- Handling Order Cancellations/Rejections**

Overview:  
"This phase enhances the TradingStream handler to process events indicating an order was canceled, rejected, or expired. If the order was linked to an active cycle ('buying' or 'selling'), the cycle's status should revert to 'watching' and its latest\_order\_id cleared. If the canceled order is an orphan (not found in DB), just log it."  
**Tasks:**

1. In the CryptoTradeStream message handler, if event.event is one of ('canceled', 'rejected', 'expired'):  
   * Get a DB connection.  
   * Try to fetch the dca\_cycles row where latest\_order\_id \== event.order.id.  
   * **If a cycle is found and cycle.status was 'buying' or 'selling':**  
     * updates \= {  
       * 'status': 'watching',  
       * 'latest\_order\_id': None  
       * }  
     * Call update\_cycle(db\_conn, cycle.id, updates).  
     * Log the action (e.g., "Order {order\_id} for cycle {cycle\_id} was {event.event}. Cycle status set to watching.").  
   * **If no cycle is found with that latest\_order\_id:**  
     * Log a WARNING (e.g., "Received {event.event} for order {order\_id} not actively tracked or already processed. Ignoring DB update for this event.").  
   * (No action needed if cycle status was already 'watching', 'complete', etc.)

**Gotchas to Watch For:**

* Ensuring only cycles in an active order state ('buying', 'selling') are reverted to 'watching'.  
* Correctly clearing latest\_order\_id.  
* Handling the case where a cancellation event arrives for an order that TradingStream no longer considers active (e.g., already processed or an orphan canceled by order\_manager.py).

**Functional Tests (in tests/):**

* test\_order\_cancellation\_reverts\_buying\_cycle\_to\_watching(): Mock cycle ('buying'), mock 'canceled' event. Assert cycle status updated.  
* test\_order\_cancellation\_for\_unknown\_order\_logs\_warning(): Mock 'canceled' event for an ID not in a mock DB. Assert warning logged and no DB update attempted on cycle.

**Integration Test (integration\_test.py \- new function):**

* test\_phase9\_tradingstream\_handles\_order\_cancellation():  
  * Scenario: An open BUY or SELL order linked to an active cycle is canceled.  
  * Setup:  
    1. Asset configured. Place a limit BUY order on Alpaca paper that is unlikely to fill immediately (e.g., price far from market).  
    2. Manually create/update dca\_cycles: status='buying', latest\_order\_id to this order's ID.  
  * Action:  
    1. Run src/main\_app.py.  
    2. Manually cancel the order via Alpaca dashboard or API.  
    3. Wait for TradingStream to process the cancellation event.  
  * Assert:  
    1. Query dca\_cycles. Verify status is 'watching' and latest\_order\_id is None.  
  * Report: Print success/failure and DB state.

### **Prompt for Phase 10: Caretaker Script \- order\_manager.py**

Overview:  
"Create the order\_manager.py caretaker script. This script, run by cron, will manage: 1\) Stale BUY Orders: Cancel bot's open BUY limit orders older than 5 minutes. 2\) Orphaned Alpaca Orders: Cancel any of the bot's open Alpaca orders (BUY or SELL) older than 5 minutes that don't correspond to an active dca\_cycles row. It uses REST API calls."  
**Tasks:**

1. Create scripts/order\_manager.py.  
2. Import necessary utils: db\_utils, alpaca\_client\_rest, models.  
3. Implement main logic:  
   * Initialize TradingClient and DB connection.  
   * Fetch all open orders from Alpaca using alpaca\_client\_rest.get\_open\_orders().  
   * Get current UTC time.  
   * **Stale BUY Order Management:**  
     * Iterate through open Alpaca orders.  
     * If order.side \== 'buy' and order.type \== 'limit':  
       * Calculate order age: current\_time \- order.created\_at (ensure timezone awareness; Alpaca times are usually UTC).  
       * If age \> 5 minutes (configurable, e.g., STALE\_ORDER\_THRESHOLD \= timedelta(minutes=5)):  
         * Log attempt to cancel stale BUY order.  
         * Call alpaca\_client\_rest.cancel\_order(client, order.id).  
         * (DB update to 'watching' will be handled by TradingStream when it gets the 'canceled' event).  
   * **Orphaned Alpaca Order Management:**  
     * Iterate again through open Alpaca orders (or combine loops).  
     * For each open order older than 5 minutes (both BUY and SELL):  
       * Query dca\_cycles to see if there's an *active* cycle (status IN ('buying', 'selling')) where latest\_order\_id \== order.id.  
       * If NO such active cycle is found AND the order is older than 5 minutes:  
         * Log attempt to cancel orphaned order.  
         * Call alpaca\_client\_rest.cancel\_order(client, order.id).  
   * Add logging for actions taken and orders checked.  
   * Ensure script exits cleanly.

**Gotchas to Watch For:**

* Timezone handling: Alpaca order timestamps are UTC. Python's datetime.now() might be naive unless made timezone-aware. Use datetime.now(timezone.utc).  
* Efficiently querying dca\_cycles for active orders.  
* Order of operations: It might be simpler to fetch all open orders once, then iterate for different conditions.  
* The script only *initiates* cancellations. TradingStream handles the DB updates upon receiving confirmation.

**Functional Tests (in tests/):**

* test\_identify\_stale\_buy\_orders(): Given a list of mock Alpaca order objects (with varying created\_at, side, type), assert correct ones are identified as stale.  
* test\_identify\_orphaned\_orders(): Given mock Alpaca orders and mock dca\_cycles data, assert correct orders are identified as orphans.

**Integration Test (integration\_test.py \- new function):**

* test\_phase10\_order\_manager\_cleans\_orders():  
  * Scenario Stale: A BUY limit order is open for \>5 mins.  
    * Setup: Place a BUY limit order on Alpaca paper far from market. Wait \~6 minutes.  
    * Action: Run scripts/order\_manager.py.  
    * Assert: The order is canceled on Alpaca (check via API or dashboard).  
  * Scenario Orphan: An order exists on Alpaca for \>5 mins but is not tracked by an active DB cycle.  
    * Setup: Manually place an order on Alpaca. Ensure no dca\_cycles row has this as latest\_order\_id with status 'buying'/'selling'. Wait \~6 minutes.  
    * Action: Run scripts/order\_manager.py.  
    * Assert: The order is canceled on Alpaca.  
  * Report: Print success/failure.

### **Prompt for Phase 11: Caretaker Script \- cooldown\_manager.py**

Overview:  
"Create the cooldown\_manager.py caretaker script. Run by cron, this script finds dca\_cycles rows in 'cooldown' status. If the configured cooldown\_period (from dca\_assets) has expired relative to the completed\_at timestamp of the previous cycle that triggered this cooldown, it updates the current 'cooldown' cycle's status to 'watching'."  
**Tasks:**

1. Create scripts/cooldown\_manager.py.  
2. Import db\_utils, models (DcaAsset, DcaCycle).  
3. Implement main logic:  
   * Get DB connection.  
   * Fetch all dca\_cycles where status \== 'cooldown'.  
   * For each 'cooldown' cycle:  
     * Fetch its DcaAsset configuration using cycle.asset\_id.  
     * Fetch the *previous* cycle for this asset\_id that is 'complete' or 'error' and has the most recent completed\_at timestamp before this 'cooldown' cycle's created\_at. (This requires careful querying, e.g., SELECT \* FROM dca\_cycles WHERE asset\_id \= %s AND status IN ('complete', 'error') AND completed\_at IS NOT NULL AND created\_at \< %s ORDER BY completed\_at DESC LIMIT 1, where the second param is the 'cooldown' cycle's created\_at).  
     * If a valid previous 'complete'/'error' cycle with a completed\_at is found:  
       * cooldown\_expiry\_time \= previous\_cycle.completed\_at \+ timedelta(seconds=dca\_asset.cooldown\_period).  
       * If datetime.now(timezone.utc) \>= cooldown\_expiry\_time:  
         * Call update\_cycle(db\_conn, current\_cooldown\_cycle.id, {'status': 'watching'}).  
         * Log the action.  
   * Add logging.

**Gotchas to Watch For:**

* Correctly identifying the *relevant previous completed cycle* to base the cooldown calculation on. The previous cycle's completed\_at is key.  
* Timezone awareness for completed\_at and datetime.now().  
* cooldown\_period is in seconds.

**Functional Tests (in tests/):**

* test\_cooldown\_expired(): Mock 'cooldown' cycle, previous 'complete' cycle with completed\_at, asset config with cooldown\_period. Current time is past expiry. Assert update to 'watching' is triggered.  
* test\_cooldown\_not\_expired(): Same setup, but current time is before expiry. Assert no update.  
* test\_cooldown\_no\_valid\_previous\_cycle(): Mock 'cooldown' cycle, but no suitable previous 'complete' cycle. Assert no update.

**Integration Test (integration\_test.py \- new function):**

* test\_phase11\_cooldown\_manager\_updates\_status():  
  * Scenario: A cycle is in 'cooldown', and its cooldown period expires.  
  * Setup:  
    1. Asset in dca\_assets with cooldown\_period (e.g., 60 seconds for test).  
    2. Manually create a 'complete' dca\_cycles row for this asset with completed\_at set to (current time \- 70 seconds).  
    3. Manually create a 'cooldown' dca\_cycles row for the same asset (created after the 'complete' one).  
  * Action: Run scripts/cooldown\_manager.py.  
  * Assert: The 'cooldown' dca\_cycles row status is updated to 'watching'.  
  * Report: Print success/failure and DB state.

### **Prompt for Phase 12: Caretaker Script \- consistency\_checker.py**

Overview:  
"Create consistency\_checker.py. This cron script handles two scenarios: 1\) If a DB cycle is 'buying' but no corresponding active BUY order exists on Alpaca, set cycle to 'watching'. 2\) If a DB cycle is 'watching' with quantity \> 0, but Alpaca shows no position, mark current cycle as 'error' and create a new 'watching' cycle with zero quantity for that asset."  
**Tasks:**

1. Create scripts/consistency\_checker.py.  
2. Import utils and models.  
3. Implement main logic:  
   * Get DB connection and TradingClient.  
   * **Scenario 1: Stuck 'buying' cycle:**  
     * Fetch dca\_cycles where status \== 'buying'.  
     * For each such cycle:  
       * If cycle.latest\_order\_id is null, log error and set to 'watching'.  
       * Else, try to fetch the order cycle.latest\_order\_id from Alpaca (client.get\_order()).  
       * If order not found, or status is filled/canceled/expired/rejected, or (order is open but older than \~5 min, indicating order\_manager should have caught it or will soon):  
         * Call update\_cycle(db\_conn, cycle.id, {'status': 'watching', 'latest\_order\_id': None}).  
         * Log the correction.  
   * **Scenario 2: 'Watching' cycle with no Alpaca position:**  
     * Fetch dca\_cycles where status \== 'watching' AND quantity \> Decimal(0).  
     * For each such cycle:  
       * Fetch its DcaAsset config.  
       * Get current position for dca\_asset.asset\_symbol from Alpaca (client.get\_position()). Handle APIError if no position.  
       * If no position exists on Alpaca (or quantity is effectively zero):  
         * Log inconsistency.  
         * Update current cycle: update\_cycle(db\_conn, cycle.id, {'status': 'error', 'completed\_at': datetime.utcnow()}).  
         * Create new cycle for this asset: create\_cycle(db\_conn, asset\_id=cycle.asset\_id, status='watching', quantity=Decimal(0), ...).  
   * Add logging.

**Gotchas to Watch For:**

* Alpaca's get\_position() raises APIError if no position exists; catch this specifically.  
* Defining what "no corresponding active order" means for Scenario 1 (not found, terminal state, or stale).  
* Ensuring the new cycle in Scenario 2 is created with all necessary fields zeroed out or set to defaults.

**Functional Tests (in tests/):**

* test\_stuck\_buying\_cycle\_no\_order\_on\_alpaca(): Mock DB cycle ('buying', latest\_order\_id set). Mock Alpaca client get\_order to raise "not found". Assert cycle updated to 'watching'.  
* test\_watching\_cycle\_no\_alpaca\_position(): Mock DB cycle ('watching', qty \> 0). Mock Alpaca get\_position to raise APIError (no position). Assert old cycle becomes 'error' and create\_cycle is called for a new 'watching' cycle.

**Integration Test (integration\_test.py \- new function):**

* test\_phase12\_consistency\_checker\_scenarios():  
  * Scenario 1: DB cycle 'buying', no live Alpaca order.  
    * Setup: Manually set a dca\_cycles row to status='buying', latest\_order\_id='fake\_id'.  
    * Action: Run scripts/consistency\_checker.py.  
    * Assert: Cycle status becomes 'watching', latest\_order\_id is None.  
  * Scenario 2: DB cycle 'watching' with qty, no Alpaca position.  
    * Setup: Manually set dca\_cycles to status='watching', quantity=Decimal('0.1'). Ensure no actual position for this asset on Alpaca paper.  
    * Action: Run scripts/consistency\_checker.py.  
    * Assert: The original cycle's status is 'error', completed\_at is set. A new cycle for the same asset exists with status='watching' and quantity=0.  
  * Report: Print success/failure and DB states.

### **Prompt for Phase 13: watchdog.py Script**

Overview:  
"Create scripts/watchdog.py. This script, run by cron, checks if the main WebSocket application (main\_app.py) is running. If not, it attempts to restart it. It should log its actions and optionally send an email alert on failures or restarts."  
**Tasks:**

1. Create scripts/watchdog.py.  
2. Import subprocess, os, sys, logging, smtplib, email.message (for optional email).  
3. Define path to main\_app.py and Python interpreter (ideally from venv).  
4. Define a PID file location (e.g., /tmp/main\_app.pid or in project dir).  
5. **Main logic:**  
   * **Check if running:**  
     * Try to read PID from PID file. If PID file exists, check if a process with that PID is running and if its command line matches main\_app.py.  
     * (Simpler alternative if PID management is too complex for v1: use psutil if allowed, or a simple pgrep command via subprocess). For KISS, let's assume main\_app.py creates a PID file on startup and removes it on graceful exit. Watchdog checks this PID file.  
   * **If not running (or PID stale):**  
     * Log "Main app not running. Attempting restart."  
     * Construct command: \[path\_to\_python\_interpreter, path\_to\_main\_app\_py\].  
     * Use subprocess.Popen() to start main\_app.py in the background (detached).  
     * Log success or failure of restart attempt.  
     * Optional: Send email alert: "Main app restarted" or "Failed to restart main app".  
   * **If running:**  
     * Log "Main app is running."  
6. Implement a basic send\_email\_alert(subject, body) function (if email alerts desired) using smtplib. Load SMTP config from .env.  
7. main\_app.py needs to be modified to write its PID to the PID file on startup and remove it on clean shutdown.

**Gotchas to Watch For:**

* Reliably checking if a process is running and is the correct one. PID files are common but can become stale if app crashes without cleanup.  
* Permissions if writing PID file to system locations like /tmp.  
* Ensuring main\_app.py is started in the correct environment (with venv activated). Often, watchdog calls a wrapper shell script that handles venv activation.  
* Email sending can have its own set of issues (SMTP auth, firewalls).

**Functional Tests:**

* (Difficult to test process management directly in unit tests).  
* Test send\_email\_alert function logic (mock smtplib).  
* Test PID file reading/writing logic if separated.

**Integration Test (integration\_test.py \- likely manual for this phase):**

* test\_phase13\_watchdog\_restarts\_app():  
  * Scenario: main\_app.py is not running, watchdog should start it.  
  * Setup: Ensure main\_app.py is NOT running. Delete any existing PID file.  
  * Action: Run scripts/watchdog.py.  
  * Assert: main\_app.py process starts (check ps or if it creates its PID file). Check watchdog logs.  
  * Scenario 2: main\_app.py is running.  
  * Setup: Start main\_app.py (ensure it creates PID file).  
  * Action: Run scripts/watchdog.py.  
  * Assert: Watchdog logs that app is running and does not try to restart.  
  * Teardown: Stop main\_app.py.  
  * Report: Manual observations.

### **Prompt for Phase 14: Configuration, Logging, and Error Handling**

Overview:  
"This phase is about ensuring robust practices across the entire application. Standardize configuration loading via python-dotenv. Implement comprehensive, structured logging. Review all components for graceful error handling using try-except blocks for I/O operations (Alpaca API, DB) and other foreseeable issues."  
**Tasks:**

1. **Configuration (src/config.py or similar):**  
   * Create a module to load all settings from .env (API keys, DB creds, paths, thresholds like stale order age).  
   * All other modules should import configurations from this central place, not directly use os.getenv.  
2. **Logging:**  
   * Set up a global logging configuration (e.g., in main\_app.py and at the start of each script).  
   * Configure formatters (timestamp, level, module name, message).  
   * Configure handlers: StreamHandler for console output, RotatingFileHandler for writing to log files (e.g., logs/app.log, logs/script\_name.log).  
   * Ensure appropriate log levels are used: INFO for routine operations, WARNING for non-critical issues or unusual situations, ERROR for failures that prevent an operation, CRITICAL for severe errors. DEBUG for verbose dev info.  
3. **Error Handling:**  
   * Review all Alpaca API call sites: Wrap in try-except APIError (from alpaca\_trade\_api.rest or alpaca.common.exceptions) and handle specific exceptions if possible (e.g., rate limits, auth errors, insufficient funds). Log errors.  
   * Review all DB interaction sites: Wrap in try-except mysql.connector.Error. Log errors.  
   * Review WebSocket connection logic for robust error handling and reconnection attempts.  
   * Ensure caretaker scripts can handle transient errors (e.g., temporary DB unavailability) and exit gracefully or retry if appropriate for their design.  
4. **Email Alert Utility (if built in Phase 13, refine it):**  
   * Make it a reusable utility function in src/utils/notifications.py.  
   * Ensure it handles SMTP errors gracefully.

**Gotchas to Watch For:**

* Overly broad except Exception: blocks; catch specific exceptions where possible.  
* Logging sensitive information (like full API responses if they contain private data).  
* Circular dependencies if config module imports from too many places.  
* Log file rotation and size management.

**Functional Tests:**

* Test that config values are loaded correctly.  
* Test that specific API errors or DB errors are caught and logged as expected in key functions (using mocking).  
* Test the email alert utility by mocking smtplib.

**Integration Test (integration\_test.py):**

* No new specific test *function* for this phase. Instead:  
  * **Review logs:** Run all existing integration tests. Examine the generated log files for clarity, completeness, and proper formatting. Ensure errors encountered during tests (e.g., a deliberately misconfigured API key for one test run) are logged appropriately.  
  * **Induce errors:** Temporarily modify code to force an API or DB error during an existing integration test run (e.g., wrong table name, incorrect API endpoint) and verify the error is handled and logged, and the system behaves as gracefully as possible. Revert changes after test.

### **Prompt for Phase 15: Final Integration Testing & Refinement**

Overview:  
"This is the final phase for v1.0. The goal is to conduct comprehensive end-to-end integration testing of the entire system. Run the bot on an Alpaca paper trading account for an extended period, monitor its behavior closely, identify and fix bugs, refine logic, and prepare for a stable v1.0 release. This includes updating all documentation."  
**Tasks:**

1. **Expand integration\_test.py:**  
   * Add more complex scenarios:  
     * Full DCA cycle: Base order \-\> multiple safety orders \-\> take-profit.  
     * Cooldown period followed by price deviation trigger for new cycle.  
     * Cooldown period expiry trigger for new cycle.  
     * Interaction of order\_manager.py canceling a stale order that TradingStream then processes.  
     * consistency\_checker.py correcting a deliberately introduced inconsistency.  
     * Simulate WebSocket disconnections and verify reconnection and watchdog behavior (harder to automate, may require manual parts).  
2. **Extended Paper Trading Run:**  
   * Configure several diverse assets in dca\_assets.  
   * Run the entire system (main app \+ cron scripts) on your paper trading account for at least several days, ideally a week or more.  
   * Monitor:  
     * Alpaca dashboard (orders, positions, equity curve).  
     * Database tables (dca\_assets, dca\_cycles) for correct state transitions and data integrity.  
     * All log files for errors, warnings, and operational flow.  
3. **Bug Fixing & Refinement:**  
   * Address any issues identified during testing.  
   * Refine configuration parameters (e.g., stale order thresholds, cooldown periods) based on observed behavior.  
4. **Code Review & Cleanup:**  
   * Review all code for clarity, efficiency, and adherence to principles.  
   * Remove any dead code or unnecessary comments.  
5. **Documentation:**  
   * Thoroughly review and update README.md to reflect the final state of the application, setup, and usage.  
   * Ensure all Python files have appropriate module/function docstrings.  
6. **Finalize requirements.txt:**  
   * Pin dependency versions (e.g., pip freeze \> requirements.txt).

**Gotchas to Watch For:**

* Subtle race conditions or timing issues between WebSocket events and caretaker scripts (though the design aims to minimize these).  
* Performance issues if DB queries are inefficient or WebSocket message handling is too slow (unlikely with current scope but good to keep in mind).  
* Resource leaks (e.g., DB connections not closed, though connection pooling or context managers should handle this).  
* Edge cases not previously considered.

**Functional Tests:**

* Ensure all existing functional tests are still passing. Add new ones if significant logic changes were made during bug fixing.

**Integration Test (integration\_test.py):**

* This entire phase *is* about running and expanding the integration tests. The goal is for integration\_test.py to be as comprehensive as possible, acting as a regression suite for v1.0. Ensure all tests pass reliably.

This concludes the AI model prompts for all 15 phases of v1.0 development.