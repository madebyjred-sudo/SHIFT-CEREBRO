-- ============================================================
-- Peaje Schema v3.0 — MULTI-APP PLATFORM RESTRUCTURE
-- ============================================================
-- Cerebro deja de ser monolito CL2-centric y pasa a ser plataforma
-- compartida por las 4 apps Shift: cl2, eco, studio, sentinel.
--
-- Tesis: cada app tiene su propio RAG (sub-bucket) + existe un
-- GLOBAL RAG cross-app para patrones generalizables. Un agente
-- (insight-router) decide a dónde va cada insight.
--
-- Cambios principales:
--   + peaje_apps              : registry de las 4 apps Shift
--   + peaje_app_taxonomy      : sub-categorías domain-specific por app,
--                               colgando de las 4 anclas canónicas
--   ~ peaje_insights          : +app_id  (NOT NULL, default backfill)
--   ~ peaje_patterns          : +app_id
--   ~ peaje_tenants           : +allowed_apps  (JSON de apps habilitadas)
--   ~ punto_medio_consolidated:
--                               +app_id, +is_global, +promoted_from_app,
--                               UNIQUE KEY rebuild
--   + peaje_router_decisions  : audit trail del insight-router
--   ~ sp_insert_insight_v2    : reemplazo regex por hook a router
--                               (mantengo retrocompatibilidad)
--
-- Idempotente. Aditivo. Backfill `app_id='cl2'` para todo lo existente
-- (es lo único que vivía en Cerebro antes de esta migración).
--
-- Aplicar:
--   mysql -h <railway-host> -u <user> -p<pass> <db> < peaje_schema_v3_multi_app.sql
-- ============================================================

SET FOREIGN_KEY_CHECKS = 0;

-- ─────────────────────────────────────────────────────────────
-- 1. peaje_apps  (registry de aplicaciones Shift)
-- ─────────────────────────────────────────────────────────────
-- Cada app de Shift que alimenta y consume Cerebro. El campo
-- `rag_strategy` deja la puerta abierta a que cada app pida
-- recall distinto (ej: sentinel quiere recall agresivo cross-tenant
-- para detección de crisis; eco quiere recall preciso por industry).

CREATE TABLE IF NOT EXISTS peaje_apps (
    app_id          VARCHAR(32) PRIMARY KEY COMMENT 'cl2|eco|studio|sentinel',
    display_name    VARCHAR(120) NOT NULL,
    domain          VARCHAR(60)  NOT NULL COMMENT 'legislative|geo|creative|pr_risk',
    description     TEXT,
    rag_strategy    JSON NULL COMMENT 'Per-app retrieval tuning (k, thresholds, etc.)',
    active          BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_active (active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO peaje_apps (app_id, display_name, domain, description, rag_strategy) VALUES
    ('cl2',      'Shift CL2',       'legislative',
     'Inteligencia legislativa Costa Rica. Expedientes, comisiones, transcripciones.',
     JSON_OBJECT('k', 20, 'min_confidence', 0.55, 'cross_tenant', FALSE)),
    ('eco',      'Shifty Eco',      'geo',
     'Generative Engine Optimization. Mide presencia de marca en respuestas LLM.',
     JSON_OBJECT('k', 15, 'min_confidence', 0.60, 'cross_tenant', TRUE)),
    ('studio',   'Shifty Studio',   'creative',
     'Chat + DAG creativo. Ingesta briefs, outputs, iteraciones.',
     JSON_OBJECT('k', 25, 'min_confidence', 0.50, 'cross_tenant', TRUE)),
    ('sentinel', 'Centinela',       'pr_risk',
     'PR/risk monitoring enterprise. Meltwater, listening, big data.',
     JSON_OBJECT('k', 30, 'min_confidence', 0.65, 'cross_tenant', TRUE))
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    domain       = VALUES(domain);

-- ─────────────────────────────────────────────────────────────
-- 2. peaje_app_taxonomy  (sub-categorías domain-specific por app)
-- ─────────────────────────────────────────────────────────────
-- Las 4 anclas canónicas (riesgos_ciegos / patrones_sectoriales /
-- gaps_productividad / vectores_aceleracion) viven en peaje_taxonomy
-- y son CROSS-APP. Esta tabla extiende cada ancla con sub-categorías
-- que solo tienen sentido dentro de una app.
--
-- Convención: `subcategory_key` debe ser único globalmente para que
-- los buckets de punto_medio_consolidated no colisionen.

CREATE TABLE IF NOT EXISTS peaje_app_taxonomy (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    app_id              VARCHAR(32) NOT NULL,
    canonical_category  VARCHAR(60) NOT NULL COMMENT 'FK lógica → peaje_taxonomy.category_key (uno de los 4)',
    subcategory_key     VARCHAR(80) NOT NULL UNIQUE COMMENT 'globally unique, snake_case',
    subcategory_label   VARCHAR(160) NOT NULL,
    description         TEXT,
    sort_order          INT DEFAULT 0,
    is_active           BOOLEAN DEFAULT TRUE,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (app_id) REFERENCES peaje_apps(app_id),
    UNIQUE KEY uk_app_subcat (app_id, subcategory_key),
    INDEX idx_canonical (canonical_category),
    INDEX idx_app (app_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO peaje_app_taxonomy
    (app_id, canonical_category, subcategory_key, subcategory_label, description, sort_order) VALUES
    -- CL2 ────────────────────────────────────────────────
    ('cl2', 'riesgos_ciegos',        'cl2_riesgo_legislativo',
        'Riesgo legislativo no anticipado',
        'Proyecto/comisión con potencial de afectar regulación sin que actores clave lo detecten.', 10),
    ('cl2', 'riesgos_ciegos',        'cl2_comision_blind_spot',
        'Comisión con baja visibilidad pública',
        'Comisión activa cuyas decisiones no están siendo cubiertas por medios.', 11),
    ('cl2', 'patrones_sectoriales',  'cl2_patron_comision',
        'Patrón recurrente de comisión',
        'Comportamiento repetido en una comisión (ausentismo, tipo de votación, etc).', 20),
    ('cl2', 'gaps_productividad',    'cl2_gap_archivo',
        'Gap de archivo histórico',
        'Decisiones legislativas sin trazabilidad documental accesible.', 30),
    ('cl2', 'vectores_aceleracion',  'cl2_vector_legislativo',
        'Vector de aceleración legislativa',
        'Tema/framing que está acelerando consenso entre fracciones.', 40),

    -- ECO ────────────────────────────────────────────────
    ('eco', 'riesgos_ciegos',        'eco_hallucination_cluster',
        'Cluster de alucinaciones modelo',
        'Patrón donde múltiples LLMs alucinan claims similares sobre la marca.', 10),
    ('eco', 'riesgos_ciegos',        'eco_competitor_capture',
        'Captura por competidor en LLM',
        'Marca apareciendo dominada por competidor en respuestas LLM para queries propias.', 11),
    ('eco', 'riesgos_ciegos',        'eco_citation_gap',
        'Gap de citación',
        'LLM menciona la marca pero no cita el dominio canónico.', 12),
    ('eco', 'patrones_sectoriales',  'eco_drift_modelo',
        'Drift entre runs del mismo modelo',
        'Cambio significativo en cómo un modelo describe la marca entre runs cercanos.', 20),
    ('eco', 'patrones_sectoriales',  'eco_position_decay',
        'Decaimiento de Average Prompt Position',
        'Marca cayendo en orden de listas LLM versus baseline.', 21),
    ('eco', 'gaps_productividad',    'eco_gt_coverage_gap',
        'Gap de cobertura de Ground Truth',
        'Subjects mencionados por LLMs sin ground_truth declarado.', 30),
    ('eco', 'vectores_aceleracion',  'eco_authority_signal',
        'Señal de autoridad emergente',
        'Dominio/contenido que está empezando a ser citado consistentemente por LLMs.', 40),

    -- STUDIO ─────────────────────────────────────────────
    ('studio', 'riesgos_ciegos',     'studio_brief_blind_spot',
        'Blind spot en brief creativo',
        'Brief omite contexto cultural/legal que rompe entregables downstream.', 10),
    ('studio', 'patrones_sectoriales','studio_patron_creativo',
        'Patrón creativo que escala',
        'Estructura/tono/idea que aparece repetida con éxito cross-cliente.', 20),
    ('studio', 'gaps_productividad', 'studio_iteracion_loop',
        'Loop de iteración improductivo',
        'Ciclos de revisión sin convergencia detectados en DAG.', 30),
    ('studio', 'vectores_aceleracion','studio_vector_estetico',
        'Vector estético emergente',
        'Tendencia visual/copy que está siendo adoptada cross-cliente.', 40),

    -- SENTINEL ───────────────────────────────────────────
    ('sentinel', 'riesgos_ciegos',   'sentinel_vector_pr',
        'Vector de riesgo PR',
        'Narrativa emergente con potencial reputacional negativo.', 10),
    ('sentinel', 'riesgos_ciegos',   'sentinel_listening_anomaly',
        'Anomalía en social listening',
        'Spike anómalo en menciones (volumen, sentiment, fuente).', 11),
    ('sentinel', 'patrones_sectoriales','sentinel_patron_crisis',
        'Patrón histórico de crisis',
        'Estructura recurrente en crisis pasadas del cliente o industria.', 20),
    ('sentinel', 'gaps_productividad','sentinel_response_gap',
        'Gap de respuesta',
        'Tiempo de reacción del cliente excede ventana de control de daño.', 30),
    ('sentinel', 'vectores_aceleracion','sentinel_amplification_vector',
        'Vector de amplificación',
        'Canal/cuenta acelerando una narrativa relevante para el cliente.', 40)
ON DUPLICATE KEY UPDATE
    subcategory_label = VALUES(subcategory_label),
    description       = VALUES(description);

-- ─────────────────────────────────────────────────────────────
-- 3. peaje_insights : +app_id
-- ─────────────────────────────────────────────────────────────
-- IF NOT EXISTS no aplica a ALTER. Uso el patrón check-via-IS y
-- ejecuto solo si la columna falta.

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'peaje_insights'
      AND COLUMN_NAME  = 'app_id'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE peaje_insights
        ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT ''cl2''
            COMMENT ''App de origen del insight (FK lógica → peaje_apps.app_id)''
            AFTER tenant_id,
        ADD INDEX idx_app (app_id),
        ADD INDEX idx_app_category (app_id, category),
        ADD INDEX idx_app_tenant (app_id, tenant_id)',
    'SELECT ''peaje_insights.app_id ya existe — skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill (idempotente — UPDATE solo donde NULL/empty, default ya seteó cl2 igual)
UPDATE peaje_insights SET app_id = 'cl2' WHERE app_id IS NULL OR app_id = '';

-- ─────────────────────────────────────────────────────────────
-- 4. peaje_patterns : +app_id
-- ─────────────────────────────────────────────────────────────

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'peaje_patterns'
      AND COLUMN_NAME  = 'app_id'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE peaje_patterns
        ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT ''cl2''
            COMMENT ''App donde el patrón aplica (FK lógica → peaje_apps.app_id)''
            AFTER pattern_type,
        ADD INDEX idx_app (app_id)',
    'SELECT ''peaje_patterns.app_id ya existe — skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

UPDATE peaje_patterns SET app_id = 'cl2' WHERE app_id IS NULL OR app_id = '';

-- ─────────────────────────────────────────────────────────────
-- 5. peaje_tenants : +allowed_apps
-- ─────────────────────────────────────────────────────────────
-- Un tenant puede usar múltiples apps Shift (ej: un cliente
-- enterprise compra Eco + Sentinel). allowed_apps es un JSON array.

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'peaje_tenants'
      AND COLUMN_NAME  = 'allowed_apps'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE peaje_tenants
        ADD COLUMN allowed_apps JSON NULL
            COMMENT ''Array JSON de app_ids habilitadas para este tenant''
            AFTER industry_vertical',
    'SELECT ''peaje_tenants.allowed_apps ya existe — skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill: tenants existentes son CL2 por origen.
UPDATE peaje_tenants
   SET allowed_apps = JSON_ARRAY('cl2')
 WHERE allowed_apps IS NULL;

-- ─────────────────────────────────────────────────────────────
-- 6. punto_medio_consolidated : +app_id, +is_global, +promoted_from_app
-- ─────────────────────────────────────────────────────────────
-- ESTE ES EL CAMBIO CRÍTICO. La tabla pasa de "un bucket por
-- (scope, tenant, category, industry)" a "un bucket por
-- (app, scope, tenant, category, industry, is_global)".
--
-- is_global=TRUE  → fila vive en el GLOBAL RAG (visible cross-app).
-- is_global=FALSE → fila vive solo en APP RAG (visible solo a esa app).
--
-- Cuando el insight-router decide "promote_to_global", se inserta
-- DOS veces: una con app_id=<source>, is_global=FALSE; y otra con
-- is_global=TRUE, promoted_from_app=<source>. Permite trazabilidad
-- y deshacer la promoción sin perder el bucket app-local.

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'punto_medio_consolidated'
      AND COLUMN_NAME  = 'app_id'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE punto_medio_consolidated
        ADD COLUMN app_id VARCHAR(32) NOT NULL DEFAULT ''cl2''
            COMMENT ''App dueña del bucket (FK lógica → peaje_apps.app_id)''
            AFTER scope,
        ADD COLUMN is_global BOOLEAN NOT NULL DEFAULT FALSE
            COMMENT ''TRUE = visible cross-app (Global RAG); FALSE = solo App RAG''
            AFTER app_id,
        ADD COLUMN promoted_from_app VARCHAR(32) NULL
            COMMENT ''Si is_global=TRUE, app de origen del insight promovido''
            AFTER is_global,
        ADD COLUMN sub_category VARCHAR(80) NULL
            COMMENT ''Sub-categoría (FK lógica → peaje_app_taxonomy.subcategory_key)''
            AFTER category,
        ADD INDEX idx_app (app_id),
        ADD INDEX idx_global (is_global),
        ADD INDEX idx_app_global (app_id, is_global),
        ADD INDEX idx_sub_category (sub_category)',
    'SELECT ''punto_medio_consolidated columnas ya existen — skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- Backfill defaults (lo existente es CL2, no global)
UPDATE punto_medio_consolidated
   SET app_id = 'cl2'
 WHERE app_id IS NULL OR app_id = '';

UPDATE punto_medio_consolidated
   SET is_global = FALSE
 WHERE is_global IS NULL;

-- Drop+Recreate UNIQUE KEY para incluir app_id e is_global.
-- Patrón seguro: drop solo si existe, luego recreate.
SET @idx_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'punto_medio_consolidated'
      AND INDEX_NAME   = 'uk_scope_tenant_cat_ind'
);
SET @sql := IF(@idx_exists > 0,
    'ALTER TABLE punto_medio_consolidated DROP INDEX uk_scope_tenant_cat_ind',
    'SELECT ''uk_scope_tenant_cat_ind ya no existe — skip drop'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

SET @idx_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME   = 'punto_medio_consolidated'
      AND INDEX_NAME   = 'uk_app_scope_tenant_cat_ind'
);
SET @sql := IF(@idx_exists = 0,
    'ALTER TABLE punto_medio_consolidated
        ADD UNIQUE KEY uk_app_scope_tenant_cat_ind
            (app_id, scope, tenant_id, category, industry_vertical, is_global)',
    'SELECT ''uk_app_scope_tenant_cat_ind ya existe — skip'' AS msg');
PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- ─────────────────────────────────────────────────────────────
-- 7. peaje_router_decisions  (audit del insight-router)
-- ─────────────────────────────────────────────────────────────
-- Cada decisión del agente queda loggeada. Sirve para:
--  (a) post-mortem cuando el routing no se sintió bien
--  (b) entrenar refinamientos del prompt del router
--  (c) métricas de calidad del clasificador

CREATE TABLE IF NOT EXISTS peaje_router_decisions (
    id                  BIGINT AUTO_INCREMENT PRIMARY KEY,
    insight_id          BIGINT NOT NULL,
    source_app          VARCHAR(32) NOT NULL,
    decided_app         VARCHAR(32) NOT NULL COMMENT 'app destino tras routing',
    canonical_category  VARCHAR(60) NOT NULL,
    sub_category        VARCHAR(80) NULL,
    promote_to_global   BOOLEAN NOT NULL DEFAULT FALSE,
    promote_rationale   TEXT NULL COMMENT 'Texto del agente justificando promoción',
    confidence          DECIMAL(4,3) NOT NULL,
    review_required     BOOLEAN NOT NULL DEFAULT FALSE COMMENT 'TRUE si conf < umbral',
    router_model        VARCHAR(80) NULL COMMENT 'modelo LLM usado',
    router_version      VARCHAR(20) NULL COMMENT 'versión del skill insight-router',
    raw_output          JSON NULL COMMENT 'output JSON crudo del agente',
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_insight (insight_id),
    INDEX idx_source_app (source_app),
    INDEX idx_decided_app (decided_app),
    INDEX idx_review (review_required),
    INDEX idx_promoted (promote_to_global)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ─────────────────────────────────────────────────────────────
-- 8. Stored procedure v3: sp_insert_insight_v3
-- ─────────────────────────────────────────────────────────────
-- v2 hace routing por regex. v3 acepta el output del insight-router
-- (campos ya decididos) y se limita a persistir. La invocación al
-- agente la hace la capa Python (peaje/extractor.py) ANTES de
-- llamar al SP — así el LLM-call no vive dentro del SP.
--
-- Mantengo v2 vivo para retrocompat (peaje legacy CL2 no rompe).

DROP PROCEDURE IF EXISTS sp_insert_insight_v3;
DELIMITER $$

CREATE PROCEDURE sp_insert_insight_v3(
    IN p_app_id VARCHAR(32),
    IN p_tenant_id VARCHAR(50),
    IN p_session_id VARCHAR(100),
    IN p_insight_text TEXT,
    IN p_canonical_category VARCHAR(60),
    IN p_sub_category VARCHAR(80),
    IN p_industry_vertical VARCHAR(60),
    IN p_extraction_model VARCHAR(80),
    IN p_extraction_confidence DECIMAL(4,3),
    IN p_pii_scrubbed BOOLEAN,
    IN p_metadata JSON
)
BEGIN
    DECLARE v_insight_id BIGINT;
    DECLARE v_app_valid BOOLEAN DEFAULT FALSE;
    DECLARE v_cat_valid BOOLEAN DEFAULT FALSE;
    DECLARE v_subcat_valid BOOLEAN DEFAULT TRUE;  -- NULL es válido

    -- Validar app
    SELECT COUNT(*) > 0 INTO v_app_valid
      FROM peaje_apps WHERE app_id = p_app_id AND active = TRUE;
    IF NOT v_app_valid THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_insert_insight_v3: app_id desconocido o inactivo';
    END IF;

    -- Validar canonical category
    SELECT COUNT(*) > 0 INTO v_cat_valid
      FROM peaje_taxonomy WHERE category_key = p_canonical_category AND is_active = TRUE;
    IF NOT v_cat_valid THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_insert_insight_v3: canonical_category inválida';
    END IF;

    -- Validar sub_category (solo si se pasa no-NULL)
    IF p_sub_category IS NOT NULL AND p_sub_category <> '' THEN
        SELECT COUNT(*) > 0 INTO v_subcat_valid
          FROM peaje_app_taxonomy
         WHERE subcategory_key = p_sub_category
           AND app_id = p_app_id
           AND is_active = TRUE;
        IF NOT v_subcat_valid THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'sp_insert_insight_v3: sub_category no pertenece a esta app';
        END IF;
    END IF;

    INSERT INTO peaje_insights (
        app_id, tenant_id, session_id, insight_text,
        category, sub_category, industry_vertical,
        extraction_model, extraction_confidence,
        pii_scrubbed, metadata, created_at
    ) VALUES (
        p_app_id, p_tenant_id, p_session_id, p_insight_text,
        p_canonical_category, NULLIF(p_sub_category,''), p_industry_vertical,
        p_extraction_model, p_extraction_confidence,
        p_pii_scrubbed, p_metadata, NOW()
    );

    SET v_insight_id = LAST_INSERT_ID();
    SELECT v_insight_id AS insight_id;
END$$

DELIMITER ;

-- ─────────────────────────────────────────────────────────────
-- 9. View: v_rag_retrieval_per_app
-- ─────────────────────────────────────────────────────────────
-- Endpoint /v1/rag/retrieve?app=eco&tenant=acme la consulta así:
--   SELECT * FROM v_rag_retrieval_per_app
--    WHERE (app_id = 'eco' OR is_global = TRUE)
--      AND (tenant_id IS NULL OR tenant_id = 'acme')
--      AND approval_status = 'approved'
--    ORDER BY confidence_score DESC LIMIT k;
--
-- La capa Python aplica el k según rag_strategy del app.

CREATE OR REPLACE VIEW v_rag_retrieval_per_app AS
SELECT
    pm.id,
    pm.app_id,
    pm.is_global,
    pm.promoted_from_app,
    pm.scope,
    pm.tenant_id,
    pm.category,
    pm.sub_category,
    pm.industry_vertical,
    pm.consolidated_text,
    pm.confidence_score,
    pm.contributing_tenants,
    pm.approval_status,
    pm.approved_at,
    pm.created_at,
    a.display_name AS app_display_name,
    a.domain AS app_domain,
    tax.category_label,
    sub.subcategory_label
FROM punto_medio_consolidated pm
JOIN peaje_apps a              ON a.app_id = pm.app_id
LEFT JOIN peaje_taxonomy tax   ON tax.category_key = pm.category
LEFT JOIN peaje_app_taxonomy sub
       ON sub.subcategory_key = pm.sub_category
      AND sub.app_id = pm.app_id;

-- ─────────────────────────────────────────────────────────────
-- DONE
-- ─────────────────────────────────────────────────────────────

SET FOREIGN_KEY_CHECKS = 1;

SELECT
    'peaje_schema_v3_multi_app applied' AS status,
    (SELECT COUNT(*) FROM peaje_apps) AS apps_registered,
    (SELECT COUNT(*) FROM peaje_app_taxonomy) AS subcategories_registered;
