import os
from dotenv import load_dotenv

load_dotenv()

# MySQL Connection
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("[WARNING] pymysql not installed. El Peaje will run in mock mode.")


def get_db_connection():
    """Get MySQL database connection.
    Supports both Railway auto-injected vars (MYSQLHOST) and custom vars (MYSQL_HOST)."""
    if not MYSQL_AVAILABLE:
        return None
    
    # Railway injects MYSQLHOST, MYSQLUSER, etc. (no underscore)
    # Our custom vars use MYSQL_HOST, MYSQL_USER, etc.
    db_host = os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST", "localhost")
    db_user = os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER", "root")
    db_pass = os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD", "")
    db_name = os.getenv("MYSQL_DATABASE") or os.getenv("MYSQLDATABASE", "railway")
    db_port = int(os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT", "3306"))
    
    try:
        conn = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_pass,
            database=db_name,
            port=db_port,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        return conn
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e} (host={db_host}, port={db_port}, db={db_name})")
        return None
