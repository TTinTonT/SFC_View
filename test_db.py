from config.app_config import ANALYTICS_CACHE_DIR
import os
import sqlite3

db_path = os.path.join(ANALYTICS_CACHE_DIR, 'analytics.db')
print(f"Checking DB: {db_path}")

try:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = cur.fetchall()
    print("Tables:", tables)

    for (table_name,) in tables:
        try:
            cur.execute(f"SELECT * FROM {table_name} WHERE sn LIKE '%2100926000%'")
            rows = cur.fetchall()
            if rows:
                print(f"Found in {table_name}:")
                for r in rows:
                    print("  ", r)
        except Exception as e:
            pass
    conn.close()
except Exception as e:
    print("Error:", e)
