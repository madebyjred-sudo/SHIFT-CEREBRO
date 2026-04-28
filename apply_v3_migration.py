"""
One-shot applier for peaje_schema_v3_multi_app.sql.

Usage:
    railway run --service shift-cerebro -- venv/bin/python apply_v3_migration.py

Runs LOCALLY — `railway run` injects MYSQL_* env vars from the
linked service into this process. No credentials ever printed.

Splits the SQL on `;` boundaries (respecting DELIMITER blocks for
the stored procedure) and runs each statement, reporting per-stmt
status. Idempotent SQL by design — safe to re-run.
"""
import os
import re
import sys
import pymysql

SQL_PATH = os.path.join(os.path.dirname(__file__), "peaje_schema_v3_multi_app.sql")


def split_statements(sql_text: str):
    """Split on `;` but respect DELIMITER $$ ... $$ blocks (stored
    procedures contain inner `;`s that aren't statement terminators).

    Yields (statement_text, source_line_hint) tuples.
    """
    out = []
    buf = []
    delimiter = ";"
    line_start = 1
    cur_line = 1
    in_block = False

    for raw_line in sql_text.splitlines(keepends=True):
        stripped = raw_line.strip()
        cur_line_record = cur_line
        cur_line += 1

        # DELIMITER directive — switches the terminator.
        m = re.match(r"^\s*DELIMITER\s+(\S+)\s*$", stripped, re.IGNORECASE)
        if m:
            # Flush whatever's in buf first (with old delimiter)
            if buf:
                out.append(("\n".join(buf).strip(), line_start))
                buf = []
            delimiter = m.group(1)
            in_block = (delimiter != ";")
            line_start = cur_line
            continue

        # Skip pure comment-only lines outside of blocks (cleaner logs)
        if not in_block and (stripped.startswith("--") or stripped == ""):
            buf.append(raw_line.rstrip("\n"))
            continue

        buf.append(raw_line.rstrip("\n"))
        # Statement boundary?
        if stripped.endswith(delimiter):
            full = "\n".join(buf).strip()
            # Strip the trailing delimiter
            if full.endswith(delimiter):
                full = full[: -len(delimiter)].strip()
            if full:
                out.append((full, line_start))
            buf = []
            line_start = cur_line

    if buf:
        tail = "\n".join(buf).strip()
        if tail:
            out.append((tail, line_start))

    return out


def main() -> int:
    host = os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST")
    user = os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER")
    password = os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD")
    database = os.getenv("MYSQL_DATABASE") or os.getenv("MYSQLDATABASE", "railway")
    port = int(os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT", "3306"))

    if not all([host, user, password]):
        print("[APPLIER] ERROR: MYSQL_* env vars missing. "
              "Run via: railway run --service shift-cerebro -- venv/bin/python apply_v3_migration.py")
        return 2

    print(f"[APPLIER] Connecting to {host}:{port}/{database} as {user}…")
    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            charset="utf8mb4",
            autocommit=False,
            connect_timeout=15,
        )
    except Exception as e:
        print(f"[APPLIER] connect failed: {e}")
        return 3

    with open(SQL_PATH, "r", encoding="utf-8") as f:
        sql_text = f.read()

    statements = split_statements(sql_text)
    print(f"[APPLIER] {len(statements)} statements parsed from {SQL_PATH}")

    ok, fail = 0, 0
    failures = []
    try:
        with conn.cursor() as cursor:
            for i, (stmt, line) in enumerate(statements, 1):
                # Skip empty / comment-only chunks
                no_comments = "\n".join(
                    ln for ln in stmt.splitlines() if not ln.strip().startswith("--")
                ).strip()
                if not no_comments:
                    continue

                preview = stmt.splitlines()[0][:80].replace("\n", " ")
                # Find first non-comment line for the preview
                for ln in stmt.splitlines():
                    s = ln.strip()
                    if s and not s.startswith("--"):
                        preview = s[:90]
                        break

                try:
                    cursor.execute(stmt)
                    # Drain any result-sets (status SELECTs in the SQL)
                    while True:
                        try:
                            rows = cursor.fetchall()
                            if rows:
                                # Print compact status rows
                                for r in rows[:3]:
                                    print(f"     ↳ {r}")
                        except Exception:
                            pass
                        if not cursor.nextset():
                            break
                    ok += 1
                    print(f"[{i:02d}/{len(statements)}] OK   {preview}")
                except Exception as e:
                    fail += 1
                    failures.append((i, line, preview, str(e)[:200]))
                    print(f"[{i:02d}/{len(statements)}] FAIL {preview}")
                    print(f"     ↳ line {line}: {e}")
        conn.commit()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    print(f"\n[APPLIER] DONE — ok={ok}  fail={fail}")
    if failures:
        print("[APPLIER] Failures:")
        for i, line, prev, err in failures:
            print(f"   #{i} (line {line}): {prev}\n      → {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
