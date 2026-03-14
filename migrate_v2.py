"""
═══════════════════════════════════════════════════════════════
MIGRACIÓN v1.0 → v2.0 — El Peaje / Punto Medio
Ejecuta este script UNA SOLA VEZ para actualizar tu base de datos.

Uso:
    cd shift-cerebro
    python migrate_v2.py

Lo que hace:
1. Crea las tablas NUEVAS (peaje_taxonomy, punto_medio_consolidated, etc.)
2. Altera las tablas EXISTENTES (agrega columnas nuevas)
3. Inserta la taxonomía C-Suite (4 categorías + 16 sub-categorías)
4. Actualiza los tenants con industry_vertical
5. Crea las vistas v2.0
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()

# Colores para output
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

def log_ok(msg):
    print(f"{GREEN}  ✓ {msg}{RESET}")

def log_err(msg):
    print(f"{RED}  ✗ {msg}{RESET}")

def log_info(msg):
    print(f"{BLUE}  ℹ {msg}{RESET}")

def log_warn(msg):
    print(f"{YELLOW}  ⚠ {msg}{RESET}")

def get_connection():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def execute_sql(cursor, sql, description, ignore_errors=False):
    """Execute SQL and handle errors gracefully."""
    try:
        cursor.execute(sql)
        log_ok(description)
        return True
    except pymysql.err.OperationalError as e:
        code = e.args[0]
        if code == 1060:  # Duplicate column
            log_warn(f"{description} — columna ya existe, saltando")
        elif code == 1061:  # Duplicate key name
            log_warn(f"{description} — índice ya existe, saltando")
        elif code == 1050:  # Table already exists
            log_warn(f"{description} — tabla ya existe, saltando")
        elif ignore_errors:
            log_warn(f"{description} — {e}")
        else:
            log_err(f"{description} — ERROR: {e}")
            return False
        return True
    except Exception as e:
        if ignore_errors:
            log_warn(f"{description} — {e}")
            return True
        log_err(f"{description} — ERROR: {e}")
        return False


def main():
    print(f"\n{BLUE}{'='*60}")
    print(f"  MIGRACIÓN El Peaje v1.0 → v2.0")
    print(f"  Membrana Neuronal Corporativa — Punto Medio")
    print(f"{'='*60}{RESET}\n")
    
    # Connect
    print(f"{BLUE}[1/6] Conectando a la base de datos...{RESET}")
    try:
        conn = get_connection()
        log_ok(f"Conectado a {os.getenv('MYSQL_HOST')} / {os.getenv('MYSQL_DATABASE')}")
    except Exception as e:
        log_err(f"No se pudo conectar: {e}")
        sys.exit(1)
    
    cursor = conn.cursor()
    
    # ═══ STEP 2: CREATE NEW TABLES ═══
    print(f"\n{BLUE}[2/6] Creando tablas nuevas...{RESET}")
    
    execute_sql(cursor, """
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
            INDEX idx_parent_key (parent_key),
            INDEX idx_is_active (is_active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """, "Tabla peaje_taxonomy")
    
    execute_sql(cursor, """
        CREATE TABLE IF NOT EXISTS punto_medio_consolidated (
            id INT AUTO_INCREMENT PRIMARY KEY,
            scope VARCHAR(20) NOT NULL DEFAULT 'global',
            tenant_id VARCHAR(50) NULL,
            category VARCHAR(60) NOT NULL,
            industry_vertical VARCHAR(60) NULL,
            region VARCHAR(60) DEFAULT 'LATAM',
            consolidated_text TEXT NOT NULL,
            executive_brief TEXT NULL,
            source_insight_count INT DEFAULT 0,
            source_pattern_count INT DEFAULT 0,
            contributing_tenants INT DEFAULT 0,
            confidence_score DECIMAL(3,2),
            is_active BOOLEAN DEFAULT TRUE,
            version INT DEFAULT 1,
            last_consolidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_scope (scope),
            INDEX idx_tenant_id (tenant_id),
            INDEX idx_category (category),
            INDEX idx_industry (industry_vertical),
            INDEX idx_is_active (is_active),
            INDEX idx_scope_category (scope, category),
            INDEX idx_tenant_category (tenant_id, category),
            INDEX idx_last_consolidated (last_consolidated_at),
            UNIQUE KEY uk_scope_tenant_cat_ind (scope, tenant_id, category, industry_vertical)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """, "Tabla punto_medio_consolidated")
    
    execute_sql(cursor, """
        CREATE TABLE IF NOT EXISTS peaje_pattern_tenants (
            id INT AUTO_INCREMENT PRIMARY KEY,
            pattern_id INT NOT NULL,
            tenant_id VARCHAR(50) NOT NULL,
            contribution_count INT DEFAULT 1,
            first_contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_pattern_tenant (pattern_id, tenant_id),
            INDEX idx_pattern_id (pattern_id),
            INDEX idx_tenant_id (tenant_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """, "Tabla peaje_pattern_tenants")
    
    execute_sql(cursor, """
        CREATE TABLE IF NOT EXISTS peaje_extraction_log (
            id INT AUTO_INCREMENT PRIMARY KEY,
            insight_id INT NULL,
            tenant_id VARCHAR(50) NOT NULL,
            session_id VARCHAR(100) NOT NULL,
            extraction_model VARCHAR(100),
            extraction_duration_ms INT,
            pii_items_scrubbed INT DEFAULT 0,
            pii_types_found JSON,
            extraction_status VARCHAR(20) DEFAULT 'success',
            category_validated BOOLEAN DEFAULT FALSE,
            original_category VARCHAR(100) NULL,
            input_message_count INT,
            input_char_count INT,
            conversation_hash VARCHAR(64),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_insight_id (insight_id),
            INDEX idx_tenant_id (tenant_id),
            INDEX idx_session_id (session_id),
            INDEX idx_status (extraction_status),
            INDEX idx_created_at (created_at),
            INDEX idx_conversation_hash (conversation_hash)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """, "Tabla peaje_extraction_log")
    
    execute_sql(cursor, """
        CREATE TABLE IF NOT EXISTS peaje_prompt_refinements (
            id INT AUTO_INCREMENT PRIMARY KEY,
            tenant_id VARCHAR(50) NULL,
            agent_id VARCHAR(50) NULL,
            refinement_type VARCHAR(50) NOT NULL,
            refinement_text TEXT NOT NULL,
            source_consolidation_id INT NULL,
            applied_count INT DEFAULT 0,
            feedback_score DECIMAL(3,2) NULL,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_tenant_id (tenant_id),
            INDEX idx_agent_id (agent_id),
            INDEX idx_refinement_type (refinement_type),
            INDEX idx_is_active (is_active)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """, "Tabla peaje_prompt_refinements")
    
    conn.commit()
    
    # ═══ STEP 3: ALTER EXISTING TABLES ═══
    print(f"\n{BLUE}[3/6] Actualizando tablas existentes...{RESET}")
    
    # peaje_insights — add new columns
    alters_insights = [
        ("ALTER TABLE peaje_insights ADD COLUMN sub_category VARCHAR(60) NULL AFTER category", "insights: +sub_category"),
        ("ALTER TABLE peaje_insights ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER sub_category", "insights: +industry_vertical"),
        ("ALTER TABLE peaje_insights ADD COLUMN extraction_model VARCHAR(100) NULL AFTER confidence_score", "insights: +extraction_model"),
        ("ALTER TABLE peaje_insights ADD COLUMN pii_scrubbed BOOLEAN DEFAULT FALSE AFTER extraction_model", "insights: +pii_scrubbed"),
        ("ALTER TABLE peaje_insights ADD COLUMN source_type VARCHAR(20) DEFAULT 'chat' AFTER raw_conversation_hash", "insights: +source_type"),
        ("ALTER TABLE peaje_insights ADD COLUMN debate_turn INT NULL AFTER source_type", "insights: +debate_turn"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_sub_category (sub_category)", "insights: +idx_sub_category"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_industry (industry_vertical)", "insights: +idx_industry"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_confidence (confidence_score)", "insights: +idx_confidence"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_source_type (source_type)", "insights: +idx_source_type"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_tenant_industry (tenant_id, industry_vertical)", "insights: +idx_tenant_industry"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_category_industry (category, industry_vertical)", "insights: +idx_category_industry"),
        ("ALTER TABLE peaje_insights ADD INDEX idx_pii_scrubbed (pii_scrubbed)", "insights: +idx_pii_scrubbed"),
    ]
    for sql, desc in alters_insights:
        execute_sql(cursor, sql, desc, ignore_errors=True)
    
    # peaje_sessions — add new columns
    alters_sessions = [
        ("ALTER TABLE peaje_sessions ADD COLUMN insight_count INT DEFAULT 0 AFTER message_count", "sessions: +insight_count"),
        ("ALTER TABLE peaje_sessions ADD COLUMN debate_mode BOOLEAN DEFAULT FALSE AFTER source", "sessions: +debate_mode"),
        ("ALTER TABLE peaje_sessions ADD INDEX idx_debate_mode (debate_mode)", "sessions: +idx_debate_mode"),
    ]
    for sql, desc in alters_sessions:
        execute_sql(cursor, sql, desc, ignore_errors=True)
    
    # peaje_patterns — add new columns
    alters_patterns = [
        ("ALTER TABLE peaje_patterns ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER pattern_text", "patterns: +industry_vertical"),
        ("ALTER TABLE peaje_patterns ADD COLUMN region VARCHAR(60) DEFAULT 'LATAM' AFTER industry_vertical", "patterns: +region"),
        ("ALTER TABLE peaje_patterns ADD COLUMN source_insight_count INT DEFAULT 1 AFTER occurrence_count", "patterns: +source_insight_count"),
        ("ALTER TABLE peaje_patterns ADD COLUMN is_active BOOLEAN DEFAULT TRUE AFTER confidence_score", "patterns: +is_active"),
        ("ALTER TABLE peaje_patterns ADD INDEX idx_industry (industry_vertical)", "patterns: +idx_industry"),
        ("ALTER TABLE peaje_patterns ADD INDEX idx_region (region)", "patterns: +idx_region"),
        ("ALTER TABLE peaje_patterns ADD INDEX idx_is_active (is_active)", "patterns: +idx_is_active"),
        ("ALTER TABLE peaje_patterns ADD INDEX idx_type_industry (pattern_type, industry_vertical)", "patterns: +idx_type_industry"),
    ]
    for sql, desc in alters_patterns:
        execute_sql(cursor, sql, desc, ignore_errors=True)
    
    # peaje_tenants — add new columns
    alters_tenants = [
        ("ALTER TABLE peaje_tenants ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER tenant_type", "tenants: +industry_vertical"),
        ("ALTER TABLE peaje_tenants ADD COLUMN punto_medio_access BOOLEAN DEFAULT FALSE AFTER config", "tenants: +punto_medio_access"),
        ("ALTER TABLE peaje_tenants ADD INDEX idx_industry (industry_vertical)", "tenants: +idx_industry"),
    ]
    for sql, desc in alters_tenants:
        execute_sql(cursor, sql, desc, ignore_errors=True)
    
    conn.commit()
    
    # ═══ STEP 4: INSERT TAXONOMY ═══
    print(f"\n{BLUE}[4/6] Insertando taxonomía C-Suite...{RESET}")
    
    taxonomy_data = [
        ('riesgos_ciegos', 'Riesgos Ciegos Detectados', 'Amenazas no visibles para el ejecutivo.', None, 1),
        ('patrones_sectoriales', 'Patrones de Decisión Sectorial', 'Tendencias macro de decisiones por industria en LATAM.', None, 2),
        ('gaps_productividad', 'Gaps de Productividad Institucional', 'Fricciones internas, desconexiones, ineficiencias sistémicas.', None, 3),
        ('vectores_aceleracion', 'Vectores de Aceleración Ocultos', 'Oportunidades no explotadas, palancas latentes.', None, 4),
        ('riesgo_talento', 'Riesgo de Fuga de Talento', 'Dependencia de personas clave sin sucesión.', 'riesgos_ciegos', 11),
        ('riesgo_tecnologico', 'Riesgo Tecnológico Oculto', 'Deuda técnica, vendor lock-in.', 'riesgos_ciegos', 12),
        ('riesgo_regulatorio', 'Riesgo Regulatorio Emergente', 'Cambios normativos no mapeados.', 'riesgos_ciegos', 13),
        ('riesgo_mercado', 'Riesgo de Mercado No Mapeado', 'Disrupción competitiva.', 'riesgos_ciegos', 14),
        ('patron_retail', 'Patrón Retail/Consumo', 'Decisiones del sector retail.', 'patrones_sectoriales', 21),
        ('patron_fintech', 'Patrón Fintech/Banca', 'Decisiones del sector financiero.', 'patrones_sectoriales', 22),
        ('patron_salud', 'Patrón Salud/Pharma', 'Decisiones del sector salud.', 'patrones_sectoriales', 23),
        ('patron_tech', 'Patrón Tecnología/SaaS', 'Decisiones del sector tech.', 'patrones_sectoriales', 24),
        ('patron_media', 'Patrón Media/Comunicación', 'Decisiones de agencias y medios.', 'patrones_sectoriales', 25),
        ('gap_comunicacion', 'Gap de Comunicación Inter-Área', 'Silos organizacionales.', 'gaps_productividad', 31),
        ('gap_contexto', 'Gap de Contexto (Reset Tax)', 'Pérdida de contexto entre sesiones.', 'gaps_productividad', 32),
        ('gap_herramientas', 'Gap de Herramientas/Procesos', 'Falta de tooling adecuado.', 'gaps_productividad', 33),
        ('gap_datos', 'Gap de Datos/Analytics', 'Decisiones sin datos.', 'gaps_productividad', 34),
        ('vector_automatizacion', 'Vector de Automatización', 'Procesos manuales automatizables.', 'vectores_aceleracion', 41),
        ('vector_expansion', 'Vector de Expansión', 'Mercados no explorados.', 'vectores_aceleracion', 42),
        ('vector_alianzas', 'Vector de Alianzas Estratégicas', 'Partnerships multiplicadores.', 'vectores_aceleracion', 43),
        ('vector_conocimiento', 'Vector de Conocimiento', 'Expertise no capturado.', 'vectores_aceleracion', 44),
    ]
    
    for key, label, desc, parent, sort in taxonomy_data:
        execute_sql(cursor, f"""
            INSERT INTO peaje_taxonomy (category_key, category_label, description, parent_key, sort_order)
            VALUES ('{key}', '{label}', '{desc}', {'NULL' if parent is None else f"'{parent}'"}, {sort})
            ON DUPLICATE KEY UPDATE category_label = VALUES(category_label)
        """, f"Taxonomía: {key}", ignore_errors=True)
    
    conn.commit()
    
    # ═══ STEP 5: UPDATE TENANTS ═══
    print(f"\n{BLUE}[5/6] Actualizando tenants con industry_vertical...{RESET}")
    
    execute_sql(cursor, """
        UPDATE peaje_tenants SET industry_vertical = 'tech_saas', punto_medio_access = TRUE
        WHERE tenant_id = 'shift'
    """, "Tenant shift → tech_saas + PM access", ignore_errors=True)
    
    execute_sql(cursor, """
        UPDATE peaje_tenants SET industry_vertical = 'media_comunicacion', punto_medio_access = TRUE
        WHERE tenant_id = 'garnier'
    """, "Tenant garnier → media_comunicacion + PM access", ignore_errors=True)
    
    execute_sql(cursor, """
        UPDATE peaje_tenants SET industry_vertical = 'retail_consumo', punto_medio_access = FALSE
        WHERE tenant_id = 'tres_pinos'
    """, "Tenant tres_pinos → retail_consumo", ignore_errors=True)
    
    conn.commit()
    
    # ═══ STEP 6: CREATE VIEWS ═══
    print(f"\n{BLUE}[6/6] Creando vistas v2.0...{RESET}")
    
    execute_sql(cursor, """
        CREATE OR REPLACE VIEW view_recent_insights AS
        SELECT i.*, t.tenant_name, t.tenant_type,
               t.industry_vertical AS tenant_industry
        FROM peaje_insights i
        JOIN peaje_tenants t ON i.tenant_id = t.tenant_id
        WHERE i.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        ORDER BY i.created_at DESC
    """, "Vista: view_recent_insights", ignore_errors=True)
    
    execute_sql(cursor, """
        CREATE OR REPLACE VIEW view_agent_usage AS
        SELECT tenant_id, agent_id, COUNT(*) as usage_count,
               COUNT(DISTINCT session_id) as unique_sessions,
               AVG(confidence_score) as avg_confidence
        FROM peaje_insights
        GROUP BY tenant_id, agent_id
        ORDER BY usage_count DESC
    """, "Vista: view_agent_usage", ignore_errors=True)
    
    execute_sql(cursor, """
        CREATE OR REPLACE VIEW view_top_patterns AS
        SELECT p.pattern_type, p.category, p.industry_vertical, p.region,
               p.pattern_text, p.occurrence_count, p.confidence_score, p.is_active
        FROM peaje_patterns p
        WHERE p.occurrence_count > 3 AND p.is_active = TRUE
        ORDER BY p.occurrence_count DESC, p.confidence_score DESC
    """, "Vista: view_top_patterns", ignore_errors=True)
    
    execute_sql(cursor, """
        CREATE OR REPLACE VIEW view_punto_medio_active AS
        SELECT pm.*, tax.category_label
        FROM punto_medio_consolidated pm
        LEFT JOIN peaje_taxonomy tax ON pm.category = tax.category_key
        WHERE pm.is_active = TRUE
          AND (pm.expires_at IS NULL OR pm.expires_at > NOW())
        ORDER BY pm.scope ASC, pm.confidence_score DESC
    """, "Vista: view_punto_medio_active", ignore_errors=True)
    
    execute_sql(cursor, """
        CREATE OR REPLACE VIEW view_peaje_health AS
        SELECT 
            (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS insights_24h,
            (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS insights_7d,
            (SELECT COUNT(*) FROM peaje_sessions WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS sessions_24h,
            (SELECT COUNT(*) FROM peaje_patterns WHERE is_active = TRUE) AS active_patterns,
            (SELECT COUNT(*) FROM punto_medio_consolidated WHERE is_active = TRUE) AS active_consolidations,
            (SELECT COUNT(*) FROM peaje_extraction_log WHERE extraction_status = 'error' AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS extraction_errors_24h,
            (SELECT AVG(confidence_score) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS avg_confidence_7d
    """, "Vista: view_peaje_health", ignore_errors=True)
    
    conn.commit()
    
    # ═══ VERIFICATION ═══
    print(f"\n{BLUE}{'='*60}")
    print(f"  VERIFICACIÓN FINAL")
    print(f"{'='*60}{RESET}\n")
    
    cursor.execute("SHOW TABLES")
    tables = [row[list(row.keys())[0]] for row in cursor.fetchall()]
    
    expected_tables = [
        'peaje_taxonomy', 'peaje_insights', 'peaje_sessions', 
        'peaje_patterns', 'peaje_pattern_tenants', 'peaje_tenants',
        'punto_medio_consolidated', 'peaje_extraction_log', 'peaje_prompt_refinements'
    ]
    
    for t in expected_tables:
        if t in tables:
            log_ok(f"Tabla {t} ✓")
        else:
            log_err(f"Tabla {t} NO ENCONTRADA")
    
    cursor.execute("SELECT COUNT(*) as cnt FROM peaje_taxonomy")
    tax_count = cursor.fetchone()["cnt"]
    log_info(f"Taxonomía: {tax_count} categorías cargadas")
    
    cursor.execute("SELECT tenant_id, industry_vertical, punto_medio_access FROM peaje_tenants")
    for row in cursor.fetchall():
        log_info(f"Tenant: {row['tenant_id']} | Industry: {row['industry_vertical']} | PM: {row['punto_medio_access']}")
    
    cursor.execute("SELECT COUNT(*) as cnt FROM peaje_insights")
    insights_count = cursor.fetchone()["cnt"]
    log_info(f"Insights existentes: {insights_count}")
    
    conn.close()
    
    print(f"\n{GREEN}{'='*60}")
    print(f"  ✅ MIGRACIÓN v2.0 COMPLETADA EXITOSAMENTE")
    print(f"{'='*60}{RESET}")
    print(f"""
{BLUE}PRÓXIMOS PASOS:{RESET}
  1. Haz push del código a Railway:
     {YELLOW}cd shift-cerebro && git add . && git commit -m "v2.0: Punto Medio + PII Scrubber" && git push{RESET}

  2. Verifica que Railway redeploy correctamente:
     {YELLOW}curl https://TU-URL-RAILWAY/health{RESET}

  3. Prueba el Peaje v2.0:
     {YELLOW}curl https://TU-URL-RAILWAY/peaje/health{RESET}

  4. Configura el cron de consolidación (cada 6h):
     {YELLOW}curl -X POST https://TU-URL-RAILWAY/punto-medio/consolidate{RESET}
""")


if __name__ == "__main__":
    main()
