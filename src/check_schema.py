from utils.db_connection import get_db_connection, execute_query

try:
    conn = get_db_connection()
    result = execute_query(conn, 'DESCRIBE dca_cycles', fetch_all=True)
    print('dca_cycles table schema:')
    for row in result:
        print(f'  {row}')
    conn.close()
except Exception as e:
    print(f'Error: {e}') 