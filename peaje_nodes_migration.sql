-- ═══════════════════════════════════════════════════════════════
-- EL PEAJE - Nodes Migration
-- Peaje 2.0: Telemetría completa de Modo Nodos (Shifty Studio)
-- Fecha: 2026-03-27
-- ═══════════════════════════════════════════════════════════════
--
-- PROBLEMA IDENTIFICADO:
-- El endpoint /peaje/nodes recibía y DESCARTABA:
--   ✗ Telemetría por ejecución (total_time_ms, user_interventions)
--   ✗ Métricas por nodo (tokens, time_ms, user_rating)
--   ✗ Topología del grafo (edges / conexiones)
--   ✗ Prompts por nodo
--   ✗ Flag nodes_mode en peaje_sessions
--
-- ESTA MIGRACIÓN:
--   + Crea peaje_node_executions (una fila por canvas run)
--   + Crea peaje_node_outputs (una fila por nodo ejecutado)
--   + Altera peaje_sessions para rastrear nodes_mode
--   + Agrega índice source_type='nodes_canvas' a insights
-- ═══════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_node_executions
-- Una fila por cada "Run" del canvas de nodos.
-- Captura la telemetría macro de la ejecución completa.
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_node_executions (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Identidad
    execution_id    VARCHAR(100) NOT NULL COMMENT 'UUID de la ejecución (session_id del canvas run)',
    session_id      VARCHAR(100) NOT NULL COMMENT 'session_id del usuario (puede ser distinto al execution_id)',
    tenant_id       VARCHAR(50)  NOT NULL DEFAULT 'shift',
    client_id       VARCHAR(100) NULL     COMMENT 'ID de cliente del frontend',
    
    -- Telemetría macro
    total_time_ms       INT      DEFAULT 0  COMMENT 'Tiempo total de ejecución del canvas en ms',
    user_interventions  INT      DEFAULT 0  COMMENT 'Cuántas veces el usuario editó/swapeó un nodo',
    node_count          INT      DEFAULT 0  COMMENT 'Cantidad de nodos ejecutados',
    nodes_succeeded     INT      DEFAULT 0,
    nodes_failed        INT      DEFAULT 0,
    
    -- Topología (JSON del grafo — solo metadata estructural, sin output_text)
    graph_topology      JSON     NULL       COMMENT 'Edges y posiciones del canvas (no outputs)',
    
    -- Resultado
    status              VARCHAR(20) DEFAULT 'completed' COMMENT 'completed, partial, error',
    insights_saved      INT         DEFAULT 0           COMMENT 'Insights ingresados a Minimax',
    
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY  uk_execution_id (execution_id),
    INDEX idx_session_id   (session_id),
    INDEX idx_tenant_id    (tenant_id),
    INDEX idx_created_at   (created_at),
    INDEX idx_status       (status),
    INDEX idx_tenant_date  (tenant_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Telemetría macro por ejecución de canvas de nodos — Peaje 2.0';


-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_node_outputs
-- Una fila por cada nodo ejecutado en cada canvas run.
-- Captura la telemetría granular + prompt + resumen de output.
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_node_outputs (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Relación con la ejecución
    execution_id    VARCHAR(100) NOT NULL COMMENT 'FK → peaje_node_executions.execution_id',
    tenant_id       VARCHAR(50)  NOT NULL DEFAULT 'shift',
    session_id      VARCHAR(100) NOT NULL,
    
    -- Identidad del nodo
    node_id         VARCHAR(100) NOT NULL COMMENT 'ID del nodo en React Flow',
    agent_id        VARCHAR(50)  NOT NULL COMMENT 'ID del agente especialista',
    node_order      TINYINT      DEFAULT 0 COMMENT 'Posición en el flujo secuencial',
    
    -- Input / Output (resumidos — nunca raw para privacidad)
    prompt_hash     VARCHAR(64)  NULL COMMENT 'SHA-256 del prompt (para deduplicación)',
    prompt_preview  VARCHAR(500) NULL COMMENT 'Primeros 500 chars del prompt (sanitizado)',
    output_chars    INT          DEFAULT 0 COMMENT 'Longitud del output para métricas de densidad',
    output_quality  DECIMAL(3,2) NULL COMMENT 'Score de calidad inferido (0.00-1.00)',
    
    -- Métricas de ejecución
    tokens_used     INT       DEFAULT 0,
    time_ms         INT       DEFAULT 0,
    user_rating     TINYINT   DEFAULT 0 COMMENT '1=thumbs up, -1=thumbs down, 0=sin rating',
    
    -- FK a peaje_insights (el insight semántico que generó este nodo)
    insight_id      INT       NULL COMMENT 'FK → peaje_insights.id',
    
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_execution_id  (execution_id),
    INDEX idx_session_id    (session_id),
    INDEX idx_tenant_id     (tenant_id),
    INDEX idx_agent_id      (agent_id),
    INDEX idx_user_rating   (user_rating),
    INDEX idx_created_at    (created_at),
    INDEX idx_tenant_agent  (tenant_id, agent_id),
    INDEX idx_exec_order    (execution_id, node_order)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Telemetría granular por nodo ejecutado — Peaje 2.0';


-- ═══════════════════════════════════════════════════════════════
-- ALTER: peaje_sessions
-- Agregar nodes_mode para diferenciar sesiones de canvas
-- de sesiones de chat clásico
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE peaje_sessions
    ADD COLUMN IF NOT EXISTS nodes_mode       BOOLEAN DEFAULT FALSE
        COMMENT 'TRUE si fue una sesión con Nodes Canvas' AFTER debate_mode,
    ADD COLUMN IF NOT EXISTS nodes_executions INT     DEFAULT 0
        COMMENT 'Cuántos canvas runs se hicieron en la sesión' AFTER nodes_mode;

-- Crear índice solo si no existe
CREATE INDEX IF NOT EXISTS idx_nodes_mode ON peaje_sessions (nodes_mode);


-- ═══════════════════════════════════════════════════════════════
-- VISTAS v2.0 — Nodes Analytics
-- ═══════════════════════════════════════════════════════════════

-- Vista: KPIs de ejecuciones de canvas por tenant
CREATE OR REPLACE VIEW view_nodes_kpis AS
SELECT
    ne.tenant_id,
    COUNT(DISTINCT ne.execution_id)         AS total_canvas_runs,
    SUM(ne.node_count)                      AS total_nodes_executed,
    SUM(ne.insights_saved)                  AS total_insights_from_canvas,
    AVG(ne.total_time_ms) / 1000            AS avg_execution_time_sec,
    SUM(ne.user_interventions)              AS total_user_interventions,
    AVG(no2.user_rating)                    AS avg_node_rating,
    AVG(no2.tokens_used)                    AS avg_tokens_per_node,
    COUNT(DISTINCT ne.session_id)           AS unique_sessions
FROM peaje_node_executions ne
LEFT JOIN peaje_node_outputs no2 ON ne.execution_id = no2.execution_id
GROUP BY ne.tenant_id
ORDER BY total_canvas_runs DESC;


-- Vista: Agentes más usados en canvas (vs chat)
CREATE OR REPLACE VIEW view_nodes_agent_usage AS
SELECT
    no2.tenant_id,
    no2.agent_id,
    COUNT(*)                                AS node_executions,
    AVG(no2.tokens_used)                    AS avg_tokens,
    AVG(no2.time_ms)                        AS avg_time_ms,
    SUM(CASE WHEN no2.user_rating = 1 THEN 1 ELSE 0 END)  AS thumbs_up,
    SUM(CASE WHEN no2.user_rating = -1 THEN 1 ELSE 0 END) AS thumbs_down,
    AVG(no2.output_quality)                 AS avg_quality_score
FROM peaje_node_outputs no2
GROUP BY no2.tenant_id, no2.agent_id
ORDER BY node_executions DESC;


-- Vista: Dashboard de salud ampliada (incluye nodes)
CREATE OR REPLACE VIEW view_peaje_health_v2 AS
SELECT
    (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR))                    AS insights_24h,
    (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR) AND source_type='nodes_canvas') AS node_insights_24h,
    (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR) AND source_type='chat')         AS chat_insights_24h,
    (SELECT COUNT(*) FROM peaje_node_executions WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR))             AS canvas_runs_24h,
    (SELECT COUNT(*) FROM peaje_sessions WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR))                    AS sessions_24h,
    (SELECT COUNT(*) FROM peaje_sessions WHERE nodes_mode = TRUE AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS nodes_sessions_24h,
    (SELECT COUNT(*) FROM peaje_patterns WHERE is_active = TRUE)                                                    AS active_patterns,
    (SELECT COUNT(*) FROM punto_medio_consolidated WHERE is_active = TRUE)                                          AS active_consolidations,
    (SELECT AVG(confidence_score) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY))         AS avg_confidence_7d,
    (SELECT SUM(user_interventions) FROM peaje_node_executions WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS total_hitl_7d;


-- ═══════════════════════════════════════════════════════════════
-- El Peaje Nodes Migration — 27 Marzo 2026
-- ═══════════════════════════════════════════════════════════════
