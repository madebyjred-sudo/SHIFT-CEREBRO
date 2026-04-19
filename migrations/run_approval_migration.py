#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
PUNTO MEDIO — MIGRATION RUNNER
Corre esto desde tu terminal para agregar las columnas de aprobación.
Usa las mismas variables de tu .env para conectarse a Railway MySQL.
═══════════════════════════════════════════════════════════════

Uso:
  python3 run_approval_migration.py
"""

import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    """Conecta a MySQL (Railway o local)."""
    host = os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST", "localhost")
    user = os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER", "root")
    pwd = os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD", "")
    db = os.getenv("MYSQL_DATABASE") or os.getenv("MYSQLDATABASE", "railway")
    port = int(os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT", "3306"))
    
    print(f"🔌 Conectando a {host}:{port}/{db} como {user}...")
    return pymysql.connect(
        host=host, user=user, password=pwd, database=db, port=port,
        charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor, connect_timeout=15
    )


MIGRATION_STEPS = [
    # Step 1: Verify punto_medio_consolidated exists
    {
        "desc": "Verificar tabla punto_medio_consolidated",
        "check": "SHOW TABLES LIKE 'punto_medio_consolidated'",
        "sql": None,  # Just a check
    },
    # Step 2: Add approval_status to punto_medio_consolidated
    {
        "desc": "Agregar approval_status a punto_medio_consolidated",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='punto_medio_consolidated' AND COLUMN_NAME='approval_status'",
        "sql": """ALTER TABLE punto_medio_consolidated
  ADD COLUMN approval_status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending'
    COMMENT 'pending = grey (not injected), approved = green (live in RAG), rejected = discarded'
    AFTER is_active""",
    },
    # Step 3: Add reviewed_by
    {
        "desc": "Agregar reviewed_by a punto_medio_consolidated",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='punto_medio_consolidated' AND COLUMN_NAME='reviewed_by'",
        "sql": """ALTER TABLE punto_medio_consolidated
  ADD COLUMN reviewed_by VARCHAR(100) NULL COMMENT 'User or agent who approved/rejected'
    AFTER approval_status""",
    },
    # Step 4: Add reviewed_at
    {
        "desc": "Agregar reviewed_at a punto_medio_consolidated",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='punto_medio_consolidated' AND COLUMN_NAME='reviewed_at'",
        "sql": """ALTER TABLE punto_medio_consolidated
  ADD COLUMN reviewed_at TIMESTAMP NULL COMMENT 'When the review happened'
    AFTER reviewed_by""",
    },
    # Step 5: Add index
    {
        "desc": "Agregar índice approval_status a punto_medio_consolidated",
        "check": "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_NAME='punto_medio_consolidated' AND INDEX_NAME='idx_approval_status'",
        "sql": "ALTER TABLE punto_medio_consolidated ADD INDEX idx_approval_status (approval_status)",
    },
    # Step 6: Same for peaje_patterns
    {
        "desc": "Agregar approval_status a peaje_patterns",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='peaje_patterns' AND COLUMN_NAME='approval_status'",
        "sql": """ALTER TABLE peaje_patterns
  ADD COLUMN approval_status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending'
    COMMENT 'pending = not injected, approved = live' AFTER is_active""",
    },
    {
        "desc": "Agregar reviewed_by a peaje_patterns",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='peaje_patterns' AND COLUMN_NAME='reviewed_by'",
        "sql": """ALTER TABLE peaje_patterns
  ADD COLUMN reviewed_by VARCHAR(100) NULL COMMENT 'Who approved/rejected'
    AFTER approval_status""",
    },
    {
        "desc": "Agregar reviewed_at a peaje_patterns",
        "check": "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME='peaje_patterns' AND COLUMN_NAME='reviewed_at'",
        "sql": """ALTER TABLE peaje_patterns
  ADD COLUMN reviewed_at TIMESTAMP NULL COMMENT 'When reviewed'
    AFTER reviewed_by""",
    },
    {
        "desc": "Agregar índice approval_status a peaje_patterns",
        "check": "SELECT INDEX_NAME FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_NAME='peaje_patterns' AND INDEX_NAME='idx_approval_status'",
        "sql": "ALTER TABLE peaje_patterns ADD INDEX idx_approval_status (approval_status)",
    },
]


def main():
    print("═" * 60)
    print("  PUNTO MEDIO — APPROVAL MIGRATION")
    print("═" * 60)
    
    try:
        conn = get_connection()
        print("  ✅ Conexión exitosa\n")
    except Exception as e:
        print(f"  ❌ Error de conexión: {e}")
        print("\n  Asegúrate de tener las variables en tu .env:")
        print("    MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE, MYSQL_PORT")
        sys.exit(1)
    
    cursor = conn.cursor()
    
    for i, step in enumerate(MIGRATION_STEPS, 1):
        print(f"  [{i}/{len(MIGRATION_STEPS)}] {step['desc']}...")
        
        # Check if already exists
        cursor.execute(step["check"])
        result = cursor.fetchone()
        
        if step["sql"] is None:
            # Just a verification step
            if result:
                print(f"    ✅ Tabla existe")
            else:
                print(f"    ❌ Tabla NO existe — necesitas correr peaje_schema_v2.sql primero")
                print(f"       Ejecuta: python3 run_tenant_migration.py")
                conn.close()
                sys.exit(1)
            continue
        
        if result:
            print(f"    ⏭️  Ya existe, saltando")
            continue
        
        try:
            cursor.execute(step["sql"])
            conn.commit()
            print(f"    ✅ Aplicado")
        except Exception as e:
            print(f"    ❌ Error: {e}")
            conn.rollback()
    
    # Final verification
    print(f"\n{'─' * 60}")
    print("  VERIFICACIÓN FINAL:")
    
    cursor.execute("SELECT COUNT(*) as cnt FROM punto_medio_consolidated")
    count = cursor.fetchone()["cnt"]
    print(f"  📊 Consolidaciones existentes: {count}")
    
    cursor.execute("SELECT COUNT(*) as cnt FROM peaje_insights")
    count = cursor.fetchone()["cnt"]
    print(f"  📊 Insights totales: {count}")
    
    cursor.execute("SELECT COUNT(*) as cnt FROM peaje_patterns")
    count = cursor.fetchone()["cnt"]
    print(f"  📊 Patrones totales: {count}")
    
    conn.close()
    print(f"\n  ✅ MIGRACIÓN COMPLETADA")
    print("═" * 60)


if __name__ == "__main__":
    main()
