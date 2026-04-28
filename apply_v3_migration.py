"""
Cerebro v3 multi-app schema applier — statement-by-statement.

Replaces the previous SQL-parser version (which choked on
PREPARE/EXECUTE/DEALLOCATE blocks on a single line). Now each step
is a Python function that issues exactly the SQL statements it
needs, gated by information_schema lookups for idempotency.

Also remediates v2 omissions found in production: peaje_taxonomy
(the 4 canonical anchors) and punto_medio_consolidated were never
created on prod. We create them here before applying the v3 ALTERs.

Run:
    railway ssh --service shift-cerebro -- /opt/venv/bin/python apply_v3_migration.py
"""
from __future__ import annotations

import os
import sys

import pymysql


DB = dict(
    host=os.getenv("MYSQL_HOST"),
    user=os.getenv("MYSQL_USER"),
    password=os.getenv("MYSQL_PASSWORD"),
    database=os.getenv("MYSQL_DATABASE", "railway"),
    port=int(os.getenv("MYSQL_PORT", "3306")),
    charset="utf8mb4",
    autocommit=False,
    connect_timeout=15,
)


def col_exists(c, table, col):
    c.execute(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME=%s",
        (table, col),
    )
    return (c.fetchone()[0] or 0) > 0


def idx_exists(c, table, idx):
    c.execute(
        "SELECT COUNT(*) FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s",
        (table, idx),
    )
    return (c.fetchone()[0] or 0) > 0


def run(label, fn):
    print(f"[ {label:<58} ]", end=" ", flush=True)
    try:
        fn()
        print("OK")
        return True
    except Exception as e:
        print(f"FAIL: {str(e)[:160]}")
        return False


def main():
    if not all([DB["host"], DB["user"], DB["password"]]):
        print("[APPLIER] MYSQL_* env vars missing")
        return 2

    print(f"[APPLIER] connect {DB['host']}:{DB['port']}/{DB['database']}")
    conn = pymysql.connect(**DB)
    c = conn.cursor()

    # ───────── (1) v2 missing — peaje_taxonomy + 4 canonical seed
    def step_taxonomy_table():
        c.execute("""
            CREATE TABLE IF NOT EXISTS peaje_taxonomy (
                id INT AUTO_INCREMENT PRIMARY KEY,
                category_key VARCHAR(60) NOT NULL UNIQUE,
                category_label VARCHAR(120) NOT NULL,
                description TEXT,
                parent_key VARCHAR(60) NULL,
                sort_order INT DEFAULT 0,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_category_key (category_key),
                INDEX idx_active (is_active),
                INDEX idx_parent (parent_key)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    def step_taxonomy_seed():
        anchors = [
            ('riesgos_ciegos', 'Riesgos Ciegos',
             'Lo que el cliente NO ve y tiene downside.', 10),
            ('patrones_sectoriales', 'Patrones Sectoriales',
             'Comportamientos recurrentes en sector/industria.', 20),
            ('gaps_productividad', 'Gaps de Productividad',
             'Procesos, coberturas o loops ineficientes.', 30),
            ('vectores_aceleracion', 'Vectores de Aceleración',
             'Señales positivas en aumento — momentum, autoridad emergente.', 40),
        ]
        for key, label, desc, sort in anchors:
            c.execute(
                "INSERT INTO peaje_taxonomy "
                "(category_key, category_label, description, sort_order) "
                "VALUES (%s, %s, %s, %s) "
                "ON DUPLICATE KEY UPDATE "
                "  category_label=VALUES(category_label), "
                "  description=VALUES(description)",
                (key, label, desc, sort),
            )

    # ───────── (2) v2 missing — punto_medio_consolidated
    def step_pmc_table():
        c.execute("""
            CREATE TABLE IF NOT EXISTS punto_medio_consolidated (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                scope VARCHAR(20) NOT NULL DEFAULT 'global'
                    COMMENT 'global = cross-tenant, tenant = single-tenant',
                tenant_id VARCHAR(50) NULL,
                category VARCHAR(60) NOT NULL,
                industry_vertical VARCHAR(60) NULL,
                consolidated_text TEXT NOT NULL,
                source_insight_ids JSON NULL,
                confidence_score DECIMAL(4,3) DEFAULT 0.0,
                contributing_tenants INT DEFAULT 0,
                approval_status VARCHAR(20) DEFAULT 'pending'
                    COMMENT 'pending | approved | rejected',
                approved_by VARCHAR(120) NULL,
                approved_at TIMESTAMP NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_scope (scope),
                INDEX idx_tenant (tenant_id),
                INDEX idx_category (category),
                INDEX idx_industry (industry_vertical),
                INDEX idx_approval (approval_status),
                INDEX idx_scope_category (scope, category),
                INDEX idx_tenant_category (tenant_id, category)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

    # ───────── (3) v3 — peaje_insights.app_id
    def step_insights_app_id():
        if not col_exists(c, "peaje_insights", "app_id"):
            c.execute(
                "ALTER TABLE peaje_insights "
                "ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT 'cl2' "
                "  COMMENT 'App de origen (FK lógica → peaje_apps.app_id)' "
                "  AFTER tenant_id, "
                "ADD INDEX idx_app (app_id), "
                "ADD INDEX idx_app_category (app_id, category), "
                "ADD INDEX idx_app_tenant (app_id, tenant_id)"
            )
        c.execute(
            "UPDATE peaje_insights SET app_id='cl2' "
            "WHERE app_id IS NULL OR app_id=''"
        )

    # ───────── (4) v3 — peaje_patterns.app_id
    def step_patterns_app_id():
        if not col_exists(c, "peaje_patterns", "app_id"):
            c.execute(
                "ALTER TABLE peaje_patterns "
                "ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT 'cl2' "
                "  COMMENT 'App donde el patrón aplica' "
                "  AFTER pattern_type, "
                "ADD INDEX idx_app (app_id)"
            )
        c.execute(
            "UPDATE peaje_patterns SET app_id='cl2' "
            "WHERE app_id IS NULL OR app_id=''"
        )

    # ───────── (5) v3 — peaje_tenants.allowed_apps
    def step_tenants_allowed_apps():
        if not col_exists(c, "peaje_tenants", "allowed_apps"):
            c.execute(
                "ALTER TABLE peaje_tenants "
                "ADD COLUMN allowed_apps JSON NULL "
                "  COMMENT 'Array JSON de app_ids habilitadas' "
                "  AFTER industry_vertical"
            )
        c.execute(
            "UPDATE peaje_tenants SET allowed_apps=JSON_ARRAY('cl2') "
            "WHERE allowed_apps IS NULL"
        )

    # ───────── (6) v3 — punto_medio_consolidated multi-app cols
    def step_pmc_columns():
        if not col_exists(c, "punto_medio_consolidated", "app_id"):
            c.execute(
                "ALTER TABLE punto_medio_consolidated "
                "ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT 'cl2' "
                "  COMMENT 'App dueña del bucket' AFTER scope, "
                "ADD COLUMN is_global BOOLEAN NOT NULL DEFAULT FALSE "
                "  COMMENT 'TRUE = visible cross-app (Global RAG)' AFTER app_id, "
                "ADD COLUMN promoted_from_app VARCHAR(32) NULL "
                "  COMMENT 'Si is_global=TRUE, app de origen' AFTER is_global, "
                "ADD COLUMN sub_category VARCHAR(80) NULL "
                "  COMMENT 'FK lógica → peaje_app_taxonomy.subcategory_key' "
                "  AFTER category, "
                "ADD INDEX idx_app (app_id), "
                "ADD INDEX idx_global (is_global), "
                "ADD INDEX idx_app_global (app_id, is_global), "
                "ADD INDEX idx_sub_category (sub_category)"
            )
        c.execute(
            "UPDATE punto_medio_consolidated SET app_id='cl2' "
            "WHERE app_id IS NULL OR app_id=''"
        )
        c.execute(
            "UPDATE punto_medio_consolidated SET is_global=FALSE "
            "WHERE is_global IS NULL"
        )

    # ───────── (7) UNIQUE KEY rebuild
    def step_pmc_unique_drop_old():
        if idx_exists(c, "punto_medio_consolidated", "uk_scope_tenant_cat_ind"):
            c.execute(
                "ALTER TABLE punto_medio_consolidated "
                "DROP INDEX uk_scope_tenant_cat_ind"
            )

    def step_pmc_unique_add_new():
        if not idx_exists(
            c, "punto_medio_consolidated", "uk_app_scope_tenant_cat_ind"
        ):
            c.execute(
                "ALTER TABLE punto_medio_consolidated "
                "ADD UNIQUE KEY uk_app_scope_tenant_cat_ind "
                "(app_id, scope, tenant_id, category, industry_vertical, is_global)"
            )

    # ───────── (8) View v_rag_retrieval_per_app
    def step_view():
        c.execute("""
            CREATE OR REPLACE VIEW v_rag_retrieval_per_app AS
            SELECT
                pm.id, pm.app_id, pm.is_global, pm.promoted_from_app,
                pm.scope, pm.tenant_id, pm.category, pm.sub_category,
                pm.industry_vertical, pm.consolidated_text,
                pm.confidence_score, pm.contributing_tenants,
                pm.approval_status, pm.approved_at, pm.created_at,
                a.display_name AS app_display_name,
                a.domain AS app_domain,
                tax.category_label,
                sub.subcategory_label
            FROM punto_medio_consolidated pm
            JOIN peaje_apps a              ON a.app_id = pm.app_id
            LEFT JOIN peaje_taxonomy tax   ON tax.category_key = pm.category
            LEFT JOIN peaje_app_taxonomy sub
                   ON sub.subcategory_key = pm.sub_category
                  AND sub.app_id = pm.app_id
        """)

    # ───────── pipeline
    steps = [
        ("v2 peaje_taxonomy table",                    step_taxonomy_table),
        ("v2 peaje_taxonomy 4 canonical seed",         step_taxonomy_seed),
        ("v2 punto_medio_consolidated table",          step_pmc_table),
        ("v3 peaje_insights.app_id + backfill",        step_insights_app_id),
        ("v3 peaje_patterns.app_id + backfill",        step_patterns_app_id),
        ("v3 peaje_tenants.allowed_apps + backfill",   step_tenants_allowed_apps),
        ("v3 punto_medio_consolidated multi-app cols", step_pmc_columns),
        ("v3 drop old uk_scope_tenant_cat_ind",        step_pmc_unique_drop_old),
        ("v3 add uk_app_scope_tenant_cat_ind",          step_pmc_unique_add_new),
        ("v3 view v_rag_retrieval_per_app",             step_view),
    ]

    ok = fail = 0
    for label, fn in steps:
        if run(label, fn):
            ok += 1
        else:
            fail += 1

    conn.commit()

    # ───────── verification
    print()
    print("─" * 70)
    print("Verification:")
    for t, col in [
        ("peaje_insights",            "app_id"),
        ("peaje_patterns",            "app_id"),
        ("peaje_tenants",             "allowed_apps"),
        ("punto_medio_consolidated",  "app_id"),
        ("punto_medio_consolidated",  "is_global"),
        ("punto_medio_consolidated",  "promoted_from_app"),
        ("punto_medio_consolidated",  "sub_category"),
    ]:
        print(f"  {'OK' if col_exists(c, t, col) else 'MISSING'}  {t}.{col}")

    c.execute("SELECT app_id, display_name FROM peaje_apps ORDER BY app_id")
    print(f"  apps registered: {c.fetchall()}")

    c.execute("SELECT category_key FROM peaje_taxonomy ORDER BY sort_order")
    print(f"  taxonomy anchors: {[r[0] for r in c.fetchall()]}")

    c.execute(
        "SELECT app_id, COUNT(*) FROM peaje_app_taxonomy "
        "GROUP BY app_id ORDER BY app_id"
    )
    print(f"  sub-cats per app: {c.fetchall()}")

    conn.close()
    print()
    print(f"[APPLIER] DONE — ok={ok}  fail={fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
