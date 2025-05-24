"""
Database utility functions for the DCA trading bot.
Handles MySQL/MariaDB connections and query execution.
"""

import os
import logging
import mysql.connector
from mysql.connector import Error
from dotenv import load_dotenv
from typing import Any, Dict, List, Optional, Tuple, Union

# Load environment variables
load_dotenv()

logger = logging.getLogger(__name__)


def get_db_connection() -> mysql.connector.MySQLConnection:
    """
    Establishes and returns a MySQL database connection using credentials from .env file.
    
    Returns:
        mysql.connector.MySQLConnection: Database connection object
        
    Raises:
        mysql.connector.Error: If connection fails
    """
    try:
        connection = mysql.connector.connect(
            host=os.getenv('DB_HOST', 'localhost'),
            user=os.getenv('DB_USER'),
            password=os.getenv('DB_PASSWORD'),
            database=os.getenv('DB_NAME'),
            port=int(os.getenv('DB_PORT', 3306)),
            autocommit=False,
            charset='utf8mb4',
            collation='utf8mb4_unicode_ci'
        )
        
        if connection.is_connected():
            logger.info("Successfully connected to MySQL database")
            return connection
        else:
            raise Error("Failed to establish database connection")
            
    except Error as e:
        logger.error(f"Database connection error: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during database connection: {e}")
        raise


def execute_query(
    query: str,
    params: Optional[Union[Tuple, Dict, List]] = None,
    fetch_one: bool = False,
    fetch_all: bool = False,
    commit: bool = False
) -> Optional[Union[Dict, List[Dict], Any]]:
    """
    Executes a SQL query with optional parameters and various return modes.
    
    Args:
        query: SQL query string with placeholders for parameters
        params: Parameters for the query (tuple, dict, or list)
        fetch_one: If True, returns a single row as a dictionary
        fetch_all: If True, returns all rows as a list of dictionaries
        commit: If True, commits the transaction (for INSERT, UPDATE, DELETE)
        
    Returns:
        - If fetch_one=True: Single row as dict or None
        - If fetch_all=True: List of rows as dicts
        - If commit=True: Number of affected rows or last insert ID
        - Otherwise: None
        
    Raises:
        mysql.connector.Error: If query execution fails
    """
    connection = None
    cursor = None
    
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        
        # Execute the query with parameters
        cursor.execute(query, params)
        
        if fetch_one:
            result = cursor.fetchone()
            logger.debug(f"Query executed, fetched one row: {result is not None}")
            return result
            
        elif fetch_all:
            result = cursor.fetchall()
            logger.debug(f"Query executed, fetched {len(result)} rows")
            return result
            
        elif commit:
            connection.commit()
            # For INSERT operations, return the last insert ID if available
            if cursor.lastrowid:
                logger.debug(f"Query executed, last insert ID: {cursor.lastrowid}")
                return cursor.lastrowid
            else:
                logger.debug(f"Query executed, {cursor.rowcount} rows affected")
                return cursor.rowcount
        else:
            # Query executed but no specific return requested
            logger.debug("Query executed successfully")
            return None
            
    except Error as e:
        if connection:
            connection.rollback()
        logger.error(f"Database query error: {e}")
        logger.error(f"Query: {query}")
        logger.error(f"Params: {params}")
        raise
        
    except Exception as e:
        if connection:
            connection.rollback()
        logger.error(f"Unexpected error during query execution: {e}")
        raise
        
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def check_connection() -> bool:
    """
    Test the database connection.
    
    Returns:
        bool: True if connection successful, False otherwise
    """
    try:
        conn = get_db_connection()
        if conn and conn.is_connected():
            conn.close()
            logging.info("Database connection test successful")
            return True
        else:
            logging.error("Database connection test failed - not connected")
            return False
    except Error as e:
        logging.error(f"Database connection test failed: {e}")
        return False 