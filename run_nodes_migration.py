#!/usr/bin/env python3
"""
run_nodes_migration.py
---------------------
Ejecuta la migración de tablas para el Modo Nodos (Peaje 2.0).

Crea:
  - peaje_node_executions  (telemetría macro por canvas run)
  - peaje_node_outputs     (telemetría por nodo ejecutado)
  - ALTER peaje_sessions   (agrega nodes_mode, nodes_executions)
  - Vistas de analytics de Nodes

Uso:
  python run_nodes_migration.py
"""
import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()

DB_HOST     = os.getenv("DB_HOST", "localhost")
DB_PORT     = int(os.getenv("DB_PORT", "3306"))
DB_USER     = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME     = os.getenv("DB_NAME", "shift_peaje")

MIGRATION_FILE = os.path.join(os.path.dirname(__file__), "peaje_nodes_migration.sql")


def split_sql_statements(sql_text: str) -> list[str]:
    """Separa el SQL en statements individuales, ignorando comentarios de línea."""
    statements = []
    current = []
    for line in sql_text.splitlines():
        stripped = line.strip()
        # Ignorar líneas vacías y comentarios puros
        if not stripped or stripped.startswith("--"):
            continue
        current.append(line)
        # Termina un statement cuando la línea trimmed termina en ;
        if stripped.endswith(";"):
            stmt = "\n".join(current).strip()
            if stmt:
                statements.append(stmt)
            current = []
    return statements


def run_migration():
    print("=" * 60)
    print("EL PEAJE — Nodes Migration v2.0")
    print(f"DB: {DB_HOST}:{DB_PORT}/{DB_NAME}")
    print("=" * 60)

    if not os.path.exists(MIGRATION_FILE):
        print(f"❌ Archivo de migración no encontrado: {MIGRATION_FILE}")
        sys.exit(1)

    with open(MIGRATION_FILE, "r", encoding="utf-8") as f:
        sql_content = f.read()

    try:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            autocommit=False,
        )
        print(f"✓ Conectado a MySQL: {DB_NAME}")
    except Exception as e:
        print(f"❌ Conexión fallida: {e}")
        sys.exit(1)

    statements = split_sql_statements(sql_content)
    print(f"📋 {len(statements)} statements a ejecutar\n")

    success = 0
    errors = []

    with conn.cursor() as cursor:
        for i, stmt in enumerate(statements, 1):
            # Resumen del statement para el log
            label = stmt.split("\n")[0][:80].strip()
            try:
                cursor.execute(stmt)
                conn.commit()
                print(f"  [{i:02d}] ✓  {label}...")
                success += 1
            except pymysql.err.OperationalError as e:
                err_code = e.args[0]
                # 1060 = Duplicate column (columna ya existe → OK)
                # 1061 = Duplicate key name (índice ya existe → OK)
                # 1050 = Table already exists (aunque usamos IF NOT EXISTS → OK)
                if err_code in (1060, 1061, 1050):
                    print(f"  [{i:02d}] ℹ  {label}... (ya existe, skipped)")
                    conn.rollback()
                    success += 1
                else:
                    print(f"  [{i:02d}] ✗  {label}")
                    print(f"       ERROR: {e}")
                    conn.rollback()
                    errors.append((i, str(e)))
            except Exception as e:
                print(f"  [{i:02d}] ✗  {label}")
                print(f"       ERROR: {e}")
                conn.rollback()
                errors.append((i, str(e)))

    conn.close()

    print("\n" + "=" * 60)
    print(f"RESULTADO: {success}/{len(statements)} statements exitosos")
    if errors:
        print(f"\n⚠️  {len(errors)} errores:")
        for idx, err in errors:
            print(f"  Statement #{idx}: {err}")
        sys.exit(1)
    else:
        print("✅ Migración completada sin errores.")
        print("\nTablas creadas/actualizadas:")
        print("  + peaje_node_executions")
        print("  + peaje_node_outputs")
        print("  ~ peaje_sessions (nodes_mode, nodes_executions)")
        print("  + view_nodes_kpis")
        print("  + view_nodes_agent_usage")
        print("  + view_peaje_health_v2")


if __name__ == "__main__":
    run_migration()
