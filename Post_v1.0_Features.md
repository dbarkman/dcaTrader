# **DCA Crypto Trading Bot \- Post-v1.0 Features List**

This document outlines features discussed and considered for development after the successful completion and stabilization of Version 1.0.

## **1\. Web Interface (Frontend)**

* **Technology:** React frontend communicating with a dedicated Node.js/Express API backend.  
* **Functionality:**  
  * **Dashboard:**  
    * Display current "cycles" (formerly "runs") for all assets.  
    * Show current Alpaca balance and positions.  
    * Display warnings for orphaned positions on Alpaca not managed by the bot.  
  * **Asset Management:**  
    * List all tradable assets from Alpaca.  
    * Allow users to enable/disable assets for DCA trading by the bot.  
    * Allow users to add new assets to be traded by the bot and configure all their DCA settings (base order, safety orders, triggers, cooldown, etc.).  
    * Display the maximum potential spend for an asset if all safety orders are filled.  
    * Allow users to remove an asset configuration (past cycle history would remain).  
  * **Cycle Control:**  
    * Allow users to manually liquidate an active trading cycle for an asset. Liquidating a cycle would place a market sell order for the asset's current position on Alpaca and automatically disable the asset for further DCA trading by the bot (until re-enabled by the user).  
  * **History & Performance:**  
    * View overall trading history for all assets.  
    * List each completed cycle's Profit/Loss (P/L).  
    * Display total P/L across all assets and cycles.  
    * Potentially paginate and filter Alpaca order history through the interface.  
  * **User Authentication:**  
    * Simple, password-based authentication for a single user.  
    * Method for initial user setup (e.g., SQL script, command-line tool).  
  * **Responsiveness:** Mobile-first design, also viewable on desktop.

## **2\. Trailing Take Profit**

* **Concept:** Once the initial take-profit percentage is reached, instead of immediately selling, the system starts "trailing" the price upwards. A sell order is only triggered if the price then drops by a specified "deviation percentage" from the highest point reached after the initial take-profit target was met.  
* **Settings (per asset):**  
  * Enable/Disable Trailing Take Profit (boolean toggle).  
  * Trailing Deviation Percent (e.g., 0.5% drop from peak triggers sell).  
* **Order Type:** The sell order triggered by the trailing take profit would likely be a market order for quick execution.

## **3\. Enhanced Notifications**

* **Mechanism:** Beyond basic email alerts from the watchdog.  
* **Events:**  
  * Successful take-profit.  
  * Start of a new trading cycle.  
  * Safety order fills.  
  * Errors or critical warnings (e.g., repeated failure to place orders, significant data inconsistencies detected).  
* **Channels:** Potentially expand to include other notification services (e.g., Telegram, Discord, Pushbullet) if desired.

## **4\. More Sophisticated Orphan/Sync Handling**

* **Orphaned Run Reconstruction (if Web UI allows enabling an asset with an existing position):** If the Web UI allows a user to enable an asset for which a position already exists on Alpaca (but no active bot cycle), provide a more guided way to either:  
  * Liquidate the existing position before starting bot trading.  
  * Attempt to "adopt" the position by creating an estimated dca\_cycles entry (potentially with user input to confirm estimated average price or number of safety orders already "filled").

## **5\. Advanced Reporting & Analytics (Web UI)**

* Charts for portfolio performance over time.  
* Breakdown of P/L by asset.  
* Statistics on average cycle duration, number of safety orders per profitable cycle, etc.

## **6\. Dynamic Configuration Adjustments**

* Potentially allow certain non-critical configuration parameters to be adjusted via the Web UI without needing to restart the core trading bot (would require careful thought about how the running bot picks up these changes).

## **7\. Support for Other Order Types or Strategies**

* (Further out) Explore options like:  
  * Trailing BUY orders for safety orders.  
  * Different conditions for starting new cycles.

*This list serves as a collection of ideas and potential future enhancements. Prioritization and feasibility would need to be assessed when approaching post-v1.0 development.*