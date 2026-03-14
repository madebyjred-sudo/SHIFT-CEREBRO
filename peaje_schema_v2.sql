-- ═══════════════════════════════════════════════════════════════
-- EL PEAJE - Schema SQL v2.0
-- Data Flywheel para SHIFTY 2.0 — Membrana Neuronal Corporativa
-- Punto Medio: Memoria Institucional Persistente
-- ═══════════════════════════════════════════════════════════════
-- 
-- CHANGELOG v2.0 (desde v1.0):
-- + peaje_taxonomy: Fuente de verdad para taxonomía C-Suite
-- + punto_medio_consolidated: Memoria institucional materializada
-- + peaje_pattern_tenants: Relación N:M patrones↔tenants (reemplaza JSON)
-- + peaje_extraction_log: Audit trail de extracciones NER
-- + peaje_prompt_refinements: Log de refinamiento dinámico de prompts
-- ~ peaje_insights: +industry_vertical, +sub_category, +extraction_model, +pii_scrubbed
-- ~ peaje_patterns: +region, +industry_vertical, +is_active, +source_insight_count
-- ~ peaje_sessions: +debate_mode, +insight_count
-- ~ peaje_tenants: +industry_vertical, +subscription_tier, +punto_medio_access
--
-- MIGRATION NOTES:
-- Si ya tienes v1.0 corriendo, ejecuta ALTER statements al final del archivo.
-- ═══════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_taxonomy
-- Fuente de verdad canónica para la Taxonomía Ejecutiva C-Suite
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_taxonomy (
    id INT AUTO_INCREMENT PRIMARY KEY,
    category_key VARCHAR(60) NOT NULL UNIQUE COMMENT 'Clave canónica interna',
    category_label VARCHAR(120) NOT NULL COMMENT 'Label para UI/reportes',
    description TEXT COMMENT 'Descripción ejecutiva de la categoría',
    parent_key VARCHAR(60) NULL COMMENT 'Para sub-categorías futuras',
    sort_order INT DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_category_key (category_key),
    INDEX idx_parent_key (parent_key),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Taxonomía C-Suite canónica — fuente de verdad';

-- Insertar las 4 categorías canónicas + sub-categorías
INSERT INTO peaje_taxonomy (category_key, category_label, description, parent_key, sort_order) VALUES
-- Categorías principales
('riesgos_ciegos', 'Riesgos Ciegos Detectados', 'Amenazas no visibles para el ejecutivo: puntos ciegos estratégicos, riesgos emergentes subestimados, dependencias ocultas.', NULL, 1),
('patrones_sectoriales', 'Patrones de Decisión Sectorial', 'Tendencias macro de toma de decisiones por industria/vertical en LATAM: preferencias recurrentes, sesgos sectoriales, ciclos de decisión.', NULL, 2),
('gaps_productividad', 'Gaps de Productividad Institucional', 'Fricciones internas, desconexiones entre equipos, ineficiencias sistémicas, impuesto invisible de la fragmentación.', NULL, 3),
('vectores_aceleracion', 'Vectores de Aceleración Ocultos', 'Oportunidades no explotadas, palancas de crecimiento latentes, ventajas competitivas no articuladas.', NULL, 4),

-- Sub-categorías de Riesgos Ciegos
('riesgo_talento', 'Riesgo de Fuga de Talento', 'Dependencia crítica de personas clave sin plan de sucesión.', 'riesgos_ciegos', 11),
('riesgo_tecnologico', 'Riesgo Tecnológico Oculto', 'Deuda técnica, dependencias de vendor, obsolescencia no detectada.', 'riesgos_ciegos', 12),
('riesgo_regulatorio', 'Riesgo Regulatorio Emergente', 'Cambios normativos en camino que no están en el radar.', 'riesgos_ciegos', 13),
('riesgo_mercado', 'Riesgo de Mercado No Mapeado', 'Disrupción competitiva, cambios de comportamiento del consumidor.', 'riesgos_ciegos', 14),

-- Sub-categorías de Patrones Sectoriales
('patron_retail', 'Patrón Retail/Consumo', 'Decisiones típicas del sector retail y consumo masivo.', 'patrones_sectoriales', 21),
('patron_fintech', 'Patrón Fintech/Banca', 'Decisiones típicas del sector financiero y fintech.', 'patrones_sectoriales', 22),
('patron_salud', 'Patrón Salud/Pharma', 'Decisiones típicas del sector salud.', 'patrones_sectoriales', 23),
('patron_tech', 'Patrón Tecnología/SaaS', 'Decisiones típicas del sector tecnológico.', 'patrones_sectoriales', 24),
('patron_media', 'Patrón Media/Comunicación', 'Decisiones típicas de agencias y medios.', 'patrones_sectoriales', 25),

-- Sub-categorías de Gaps de Productividad
('gap_comunicacion', 'Gap de Comunicación Inter-Área', 'Silos organizacionales, información que no fluye.', 'gaps_productividad', 31),
('gap_contexto', 'Gap de Contexto (Reset Tax)', 'Pérdida de contexto entre sesiones, reuniones, rotaciones.', 'gaps_productividad', 32),
('gap_herramientas', 'Gap de Herramientas/Procesos', 'Ineficiencia por falta de tooling o procesos inadecuados.', 'gaps_productividad', 33),
('gap_datos', 'Gap de Datos/Analytics', 'Decisiones sin datos, métricas no conectadas.', 'gaps_productividad', 34),

-- Sub-categorías de Vectores de Aceleración
('vector_automatizacion', 'Vector de Automatización', 'Procesos manuales que pueden automatizarse con alto ROI.', 'vectores_aceleracion', 41),
('vector_expansion', 'Vector de Expansión', 'Mercados, segmentos o canales no explorados.', 'vectores_aceleracion', 42),
('vector_alianzas', 'Vector de Alianzas Estratégicas', 'Partnerships que multiplicarían capacidades.', 'vectores_aceleracion', 43),
('vector_conocimiento', 'Vector de Conocimiento', 'Expertise interno no capturado ni distribuido.', 'vectores_aceleracion', 44)
ON DUPLICATE KEY UPDATE category_label = VALUES(category_label);

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_insights (v2.0 — REFORZADA)
-- Insights extraídos con taxonomía enforceada y PII scrubbing
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_insights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL COMMENT 'corporate_tenant_uuid',
    session_id VARCHAR(100) NOT NULL COMMENT 'executive_session_id',
    agent_id VARCHAR(50) NOT NULL COMMENT 'agent_swarm_node',
    
    -- Contenido anonimizado
    insight_text TEXT COMMENT 'Estructura anonimizada (Entidad-Contexto-Valor)',
    category VARCHAR(60) NOT NULL COMMENT 'FK lógica → peaje_taxonomy.category_key',
    sub_category VARCHAR(60) NULL COMMENT 'Sub-categoría opcional → peaje_taxonomy.category_key',
    industry_vertical VARCHAR(60) NULL COMMENT 'Vertical de industria detectada',
    
    -- Scoring y metadata
    sentiment VARCHAR(20) COMMENT 'positive, negative, neutral',
    confidence_score DECIMAL(3,2) COMMENT 'Score emitido por el LLM Extractor (0.00-1.00)',
    extraction_model VARCHAR(100) COMMENT 'Modelo usado para extracción',
    pii_scrubbed BOOLEAN DEFAULT FALSE COMMENT 'TRUE si pasó por PII Scrubber determinístico',
    
    -- Hashes de anonimización
    anonymized_hash VARCHAR(64) COMMENT 'SHA-256 hash para anonimización (NER)',
    raw_conversation_hash VARCHAR(64) COMMENT 'Referencia cruzada aislada (nunca almacenamos raw)',
    
    -- Debate metadata
    source_type VARCHAR(20) DEFAULT 'chat' COMMENT 'chat, debate, embed',
    debate_turn INT NULL COMMENT 'Turno del debate (si aplica)',
    
    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_category (category),
    INDEX idx_sub_category (sub_category),
    INDEX idx_industry (industry_vertical),
    INDEX idx_created_at (created_at),
    INDEX idx_confidence (confidence_score),
    INDEX idx_source_type (source_type),
    INDEX idx_tenant_category (tenant_id, category),
    INDEX idx_tenant_agent (tenant_id, agent_id),
    INDEX idx_tenant_industry (tenant_id, industry_vertical),
    INDEX idx_category_industry (category, industry_vertical),
    INDEX idx_pii_scrubbed (pii_scrubbed)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Insights extraídos de conversaciones - El Peaje v2.0';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_sessions (v2.0)
-- Tracking de sesiones por tenant — ahora incluye debates
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100) COMMENT 'Identificador anónimo del usuario',
    message_count INT DEFAULT 0,
    insight_count INT DEFAULT 0 COMMENT 'Cuántos insights se extrajeron de esta sesión',
    agents_used JSON COMMENT 'Array de IDs de agentes usados en la sesión',
    topics_discussed JSON COMMENT 'Array de tópicos identificados',
    session_duration_seconds INT COMMENT 'Duración de la sesión en segundos',
    source VARCHAR(50) DEFAULT 'standalone' COMMENT 'standalone, brandhub, embed',
    debate_mode BOOLEAN DEFAULT FALSE COMMENT 'TRUE si fue una sesión de debate',
    ip_hash VARCHAR(64) COMMENT 'Hash de IP para prevención de abuso',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP NULL,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_created_at (created_at),
    INDEX idx_source (source),
    INDEX idx_debate_mode (debate_mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Sesiones de chat/debate por tenant - v2.0';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_patterns (v2.0 — REFORZADA)
-- Inteligencia acumulada — Patrones macro-regionales
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pattern_type VARCHAR(60) NOT NULL COMMENT 'FK lógica → peaje_taxonomy.category_key',
    category VARCHAR(60) NOT NULL,
    pattern_text TEXT NOT NULL COMMENT 'Patrón estructural de inteligencia colectiva',
    
    -- Metadata enriquecida
    industry_vertical VARCHAR(60) NULL COMMENT 'Vertical de industria (si aplica)',
    region VARCHAR(60) DEFAULT 'LATAM' COMMENT 'Región geográfica macro',
    occurrence_count INT DEFAULT 1 COMMENT 'Densidad del nodo en la red',
    source_insight_count INT DEFAULT 1 COMMENT 'Cuántos insights alimentaron este patrón',
    confidence_score DECIMAL(3,2) COMMENT 'Confianza estadística del patrón',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'FALSE = patrón obsoleto/expirado',
    
    -- Relaciones (los JSON se mantienen como cache, la tabla N:M es fuente de verdad)
    related_agents JSON COMMENT 'Agentes que más contribuyen a este patrón',
    
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_pattern_type (pattern_type),
    INDEX idx_category (category),
    INDEX idx_industry (industry_vertical),
    INDEX idx_region (region),
    INDEX idx_occurrence_count (occurrence_count),
    INDEX idx_last_seen (last_seen_at),
    INDEX idx_is_active (is_active),
    INDEX idx_type_industry (pattern_type, industry_vertical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Patrones identificados acumulados - Inteligencia colectiva v2.0';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_pattern_tenants
-- Relación N:M entre patrones y tenants (reemplaza JSON opaco)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_pattern_tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pattern_id INT NOT NULL,
    tenant_id VARCHAR(50) NOT NULL,
    contribution_count INT DEFAULT 1 COMMENT 'Cuántas veces este tenant contribuyó al patrón',
    first_contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_contributed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    UNIQUE KEY uk_pattern_tenant (pattern_id, tenant_id),
    INDEX idx_pattern_id (pattern_id),
    INDEX idx_tenant_id (tenant_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Relación N:M entre patrones y tenants contribuyentes';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_tenants (v2.0)
-- Configuración y metadata de tenants — con vertical y acceso PM
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL UNIQUE,
    tenant_name VARCHAR(100) NOT NULL,
    tenant_type VARCHAR(50) COMMENT 'internal, client, partner',
    industry_vertical VARCHAR(60) NULL COMMENT 'Vertical principal del tenant',
    brand_color VARCHAR(7) DEFAULT '#0047AB',
    logo_url VARCHAR(255),
    allowed_agents JSON COMMENT 'Agentes disponibles para este tenant',
    config JSON COMMENT 'Configuración específica del tenant',
    punto_medio_access BOOLEAN DEFAULT FALSE COMMENT 'TRUE = acceso a su Punto Medio institucional',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_is_active (is_active),
    INDEX idx_industry (industry_vertical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tenants configurados en el sistema v2.0';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: punto_medio_consolidated
-- EL CORAZÓN: Memoria Institucional Persistente
-- Insights anonimizados consolidados en inteligencia accionable
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS punto_medio_consolidated (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Scope: Global (sector-wide) o Tenant-specific
    scope VARCHAR(20) NOT NULL DEFAULT 'global' COMMENT 'global = cross-tenant, tenant = single-tenant',
    tenant_id VARCHAR(50) NULL COMMENT 'NULL para scope=global, tenant_id para scope=tenant',
    
    -- Contenido consolidado
    category VARCHAR(60) NOT NULL COMMENT 'FK lógica → peaje_taxonomy.category_key',
    industry_vertical VARCHAR(60) NULL COMMENT 'Vertical de industria',
    region VARCHAR(60) DEFAULT 'LATAM',
    
    -- La inteligencia destilada
    consolidated_text TEXT NOT NULL COMMENT 'Resumen ejecutivo consolidado — listo para inyección RAG',
    executive_brief TEXT NULL COMMENT 'Versión ultra-corta para system prompts (max 200 chars)',
    
    -- Estadísticas
    source_insight_count INT DEFAULT 0 COMMENT 'Cuántos insights alimentaron esta consolidación',
    source_pattern_count INT DEFAULT 0 COMMENT 'Cuántos patrones contribuyeron',
    contributing_tenants INT DEFAULT 0 COMMENT 'Cuántos tenants distintos (solo para scope=global)',
    confidence_score DECIMAL(3,2) COMMENT 'Confianza estadística agregada',
    
    -- Lifecycle
    is_active BOOLEAN DEFAULT TRUE,
    version INT DEFAULT 1 COMMENT 'Versión del consolidado (se incrementa en cada refresh)',
    last_consolidated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT 'Última vez que se ejecutó la consolidación',
    expires_at TIMESTAMP NULL COMMENT 'Fecha de expiración (data decay)',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_scope (scope),
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_category (category),
    INDEX idx_industry (industry_vertical),
    INDEX idx_region (region),
    INDEX idx_is_active (is_active),
    INDEX idx_scope_category (scope, category),
    INDEX idx_tenant_category (tenant_id, category),
    INDEX idx_last_consolidated (last_consolidated_at),
    UNIQUE KEY uk_scope_tenant_cat_ind (scope, tenant_id, category, industry_vertical)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Punto Medio: Memoria Institucional Persistente — El corazón del Flywheel';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_extraction_log
-- Audit trail de todas las extracciones NER/PII
-- No almacena PII, solo metadata de la operación
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_extraction_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    insight_id INT NULL COMMENT 'FK → peaje_insights.id (si se insertó)',
    tenant_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) NOT NULL,
    
    -- Metadata de extracción
    extraction_model VARCHAR(100) COMMENT 'Modelo LLM usado',
    extraction_duration_ms INT COMMENT 'Tiempo de extracción en ms',
    pii_items_scrubbed INT DEFAULT 0 COMMENT 'Cantidad de items PII eliminados por scrubber',
    pii_types_found JSON COMMENT '{"emails": 2, "phones": 1, "names": 3}',
    
    -- Resultado
    extraction_status VARCHAR(20) DEFAULT 'success' COMMENT 'success, fallback, error',
    category_validated BOOLEAN DEFAULT FALSE COMMENT 'TRUE si la categoría pasó validación contra taxonomy',
    original_category VARCHAR(100) NULL COMMENT 'Categoría original del LLM (antes de validación)',
    
    -- Input metrics (sin almacenar contenido)
    input_message_count INT COMMENT 'Cantidad de mensajes en la conversación',
    input_char_count INT COMMENT 'Cantidad total de caracteres procesados',
    conversation_hash VARCHAR(64) COMMENT 'Hash de la conversación (para deduplicación)',
    
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_insight_id (insight_id),
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_status (extraction_status),
    INDEX idx_created_at (created_at),
    INDEX idx_conversation_hash (conversation_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Audit trail de extracciones NER — no almacena PII';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_prompt_refinements
-- Log de cómo el Punto Medio refina los system prompts
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_prompt_refinements (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NULL COMMENT 'NULL = refinamiento global',
    agent_id VARCHAR(50) NULL COMMENT 'Agente que recibió el refinamiento',
    
    -- El refinamiento
    refinement_type VARCHAR(50) NOT NULL COMMENT 'rag_injection, prompt_tweak, context_enrichment',
    refinement_text TEXT NOT NULL COMMENT 'El texto inyectado/modificado',
    source_consolidation_id INT NULL COMMENT 'FK → punto_medio_consolidated.id',
    
    -- Efectividad
    applied_count INT DEFAULT 0 COMMENT 'Cuántas veces se ha aplicado',
    feedback_score DECIMAL(3,2) NULL COMMENT 'Score de feedback implícito (0.00-1.00)',
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_refinement_type (refinement_type),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Refinamientos de prompts basados en Punto Medio';

-- ═══════════════════════════════════════════════════════════════
-- INSERTS INICIALES: Tenants (v2.0 con industry_vertical)
-- ═══════════════════════════════════════════════════════════════
INSERT INTO peaje_tenants (tenant_id, tenant_name, tenant_type, industry_vertical, brand_color, allowed_agents, punto_medio_access) VALUES
('shift', 'Shift Lab', 'internal', 'tech_saas', '#0047AB', '["pedro","susana","carlos","maria","jorge","lucia","andres","patricia","roberto","carmen","diego","fernanda","martin","sofia","gabriel"]', TRUE),
('garnier', 'Garnier', 'client', 'media_comunicacion', '#00A651', '["maria","jorge","lucia","andres","carmen"]', TRUE),
('tres_pinos', 'Tres Pinos', 'client', 'retail_consumo', '#8B4513', '["maria","jorge","diego","roberto"]', FALSE)
ON DUPLICATE KEY UPDATE 
    industry_vertical = VALUES(industry_vertical),
    punto_medio_access = VALUES(punto_medio_access),
    updated_at = CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════
-- VISTAS v2.0
-- ═══════════════════════════════════════════════════════════════

-- Vista: Insights recientes por tenant con taxonomía
CREATE OR REPLACE VIEW view_recent_insights AS
SELECT 
    i.*,
    t.tenant_name,
    t.tenant_type,
    t.industry_vertical AS tenant_industry,
    tax.category_label,
    tax.description AS category_description
FROM peaje_insights i
JOIN peaje_tenants t ON i.tenant_id = t.tenant_id
LEFT JOIN peaje_taxonomy tax ON i.category = tax.category_key
WHERE i.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY i.created_at DESC;

-- Vista: Agentes más utilizados por tenant
CREATE OR REPLACE VIEW view_agent_usage AS
SELECT 
    tenant_id,
    agent_id,
    COUNT(*) as usage_count,
    COUNT(DISTINCT session_id) as unique_sessions,
    AVG(confidence_score) as avg_confidence
FROM peaje_insights
GROUP BY tenant_id, agent_id
ORDER BY usage_count DESC;

-- Vista: Patrones más frecuentes con industria
CREATE OR REPLACE VIEW view_top_patterns AS
SELECT 
    p.pattern_type,
    p.category,
    p.industry_vertical,
    p.region,
    p.pattern_text,
    p.occurrence_count,
    p.confidence_score,
    p.is_active,
    COUNT(DISTINCT pt.tenant_id) AS tenant_count
FROM peaje_patterns p
LEFT JOIN peaje_pattern_tenants pt ON p.id = pt.pattern_id
WHERE p.occurrence_count > 3 AND p.is_active = TRUE
GROUP BY p.id
ORDER BY p.occurrence_count DESC, p.confidence_score DESC;

-- Vista: Punto Medio activo para inyección RAG
CREATE OR REPLACE VIEW view_punto_medio_active AS
SELECT 
    pm.*,
    tax.category_label
FROM punto_medio_consolidated pm
LEFT JOIN peaje_taxonomy tax ON pm.category = tax.category_key
WHERE pm.is_active = TRUE
  AND (pm.expires_at IS NULL OR pm.expires_at > NOW())
ORDER BY pm.scope ASC, pm.confidence_score DESC;

-- Vista: Dashboard de salud del Peaje
CREATE OR REPLACE VIEW view_peaje_health AS
SELECT 
    (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS insights_24h,
    (SELECT COUNT(*) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS insights_7d,
    (SELECT COUNT(*) FROM peaje_sessions WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS sessions_24h,
    (SELECT COUNT(*) FROM peaje_patterns WHERE is_active = TRUE) AS active_patterns,
    (SELECT COUNT(*) FROM punto_medio_consolidated WHERE is_active = TRUE) AS active_consolidations,
    (SELECT COUNT(*) FROM peaje_extraction_log WHERE extraction_status = 'error' AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)) AS extraction_errors_24h,
    (SELECT AVG(confidence_score) FROM peaje_insights WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)) AS avg_confidence_7d;

-- ═══════════════════════════════════════════════════════════════
-- STORED PROCEDURES v2.0
-- ═══════════════════════════════════════════════════════════════

DELIMITER //

-- Procedimiento: Insertar insight con validación de taxonomía
CREATE PROCEDURE sp_insert_insight_v2(
    IN p_tenant_id VARCHAR(50),
    IN p_session_id VARCHAR(100),
    IN p_agent_id VARCHAR(50),
    IN p_insight_text TEXT,
    IN p_category VARCHAR(60),
    IN p_sub_category VARCHAR(60),
    IN p_industry_vertical VARCHAR(60),
    IN p_sentiment VARCHAR(20),
    IN p_confidence_score DECIMAL(3,2),
    IN p_extraction_model VARCHAR(100),
    IN p_pii_scrubbed BOOLEAN,
    IN p_source_type VARCHAR(20),
    IN p_anonymized_hash VARCHAR(64),
    IN p_conversation_hash VARCHAR(64)
)
BEGIN
    DECLARE v_valid_category BOOLEAN DEFAULT FALSE;
    DECLARE v_final_category VARCHAR(60);
    DECLARE v_insight_id INT;
    
    -- Validar categoría contra taxonomía
    SELECT COUNT(*) > 0 INTO v_valid_category
    FROM peaje_taxonomy 
    WHERE category_key = p_category AND is_active = TRUE;
    
    -- Si la categoría no es válida, mapear al parent más cercano o default
    IF v_valid_category THEN
        SET v_final_category = p_category;
    ELSE
        -- Intentar match parcial contra las 4 categorías principales
        SET v_final_category = CASE
            WHEN LOWER(p_category) LIKE '%riesgo%' THEN 'riesgos_ciegos'
            WHEN LOWER(p_category) LIKE '%patr%n%' OR LOWER(p_category) LIKE '%sector%' THEN 'patrones_sectoriales'
            WHEN LOWER(p_category) LIKE '%gap%' OR LOWER(p_category) LIKE '%productiv%' THEN 'gaps_productividad'
            WHEN LOWER(p_category) LIKE '%vector%' OR LOWER(p_category) LIKE '%aceler%' THEN 'vectores_aceleracion'
            ELSE 'vectores_aceleracion'
        END;
    END IF;
    
    INSERT INTO peaje_insights (
        tenant_id, session_id, agent_id, insight_text,
        category, sub_category, industry_vertical,
        sentiment, confidence_score, extraction_model, pii_scrubbed,
        source_type, anonymized_hash, raw_conversation_hash
    ) VALUES (
        p_tenant_id, p_session_id, p_agent_id, p_insight_text,
        v_final_category, p_sub_category, p_industry_vertical,
        p_sentiment, p_confidence_score, p_extraction_model, p_pii_scrubbed,
        p_source_type, p_anonymized_hash, p_conversation_hash
    );
    
    SET v_insight_id = LAST_INSERT_ID();
    
    -- Actualizar insight_count en la sesión
    UPDATE peaje_sessions 
    SET insight_count = insight_count + 1 
    WHERE session_id = p_session_id;
    
    SELECT v_insight_id AS insight_id, v_final_category AS validated_category, v_valid_category AS was_valid;
END //

-- Procedimiento: Actualizar o crear patrón v2.0
CREATE PROCEDURE sp_upsert_pattern_v2(
    IN p_pattern_type VARCHAR(60),
    IN p_category VARCHAR(60),
    IN p_pattern_text TEXT,
    IN p_industry_vertical VARCHAR(60),
    IN p_region VARCHAR(60),
    IN p_tenant_id VARCHAR(50)
)
BEGIN
    DECLARE v_pattern_id INT;
    
    -- Buscar patrón existente similar
    SELECT id INTO v_pattern_id
    FROM peaje_patterns
    WHERE pattern_type = p_pattern_type 
      AND category = p_category
      AND (industry_vertical = p_industry_vertical OR (industry_vertical IS NULL AND p_industry_vertical IS NULL))
      AND pattern_text = p_pattern_text
    LIMIT 1;
    
    IF v_pattern_id IS NOT NULL THEN
        -- Actualizar patrón existente
        UPDATE peaje_patterns 
        SET occurrence_count = occurrence_count + 1,
            source_insight_count = source_insight_count + 1,
            last_seen_at = NOW()
        WHERE id = v_pattern_id;
    ELSE
        -- Crear nuevo patrón
        INSERT INTO peaje_patterns (pattern_type, category, pattern_text, industry_vertical, region)
        VALUES (p_pattern_type, p_category, p_pattern_text, p_industry_vertical, COALESCE(p_region, 'LATAM'));
        SET v_pattern_id = LAST_INSERT_ID();
    END IF;
    
    -- Registrar contribución del tenant (N:M)
    IF p_tenant_id IS NOT NULL THEN
        INSERT INTO peaje_pattern_tenants (pattern_id, tenant_id, contribution_count)
        VALUES (v_pattern_id, p_tenant_id, 1)
        ON DUPLICATE KEY UPDATE 
            contribution_count = contribution_count + 1,
            last_contributed_at = NOW();
    END IF;
    
    SELECT v_pattern_id AS pattern_id;
END //

DELIMITER ;

-- ═══════════════════════════════════════════════════════════════
-- MIGRATION PATH: ALTER STATEMENTS (v1.0 → v2.0)
-- Solo ejecutar si ya tienes las tablas v1.0
-- ═══════════════════════════════════════════════════════════════

-- ALTER TABLE peaje_insights 
--     ADD COLUMN sub_category VARCHAR(60) NULL AFTER category,
--     ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER sub_category,
--     ADD COLUMN extraction_model VARCHAR(100) NULL AFTER confidence_score,
--     ADD COLUMN pii_scrubbed BOOLEAN DEFAULT FALSE AFTER extraction_model,
--     ADD COLUMN source_type VARCHAR(20) DEFAULT 'chat' AFTER raw_conversation_hash,
--     ADD COLUMN debate_turn INT NULL AFTER source_type,
--     ADD INDEX idx_sub_category (sub_category),
--     ADD INDEX idx_industry (industry_vertical),
--     ADD INDEX idx_confidence (confidence_score),
--     ADD INDEX idx_source_type (source_type),
--     ADD INDEX idx_tenant_industry (tenant_id, industry_vertical),
--     ADD INDEX idx_category_industry (category, industry_vertical),
--     ADD INDEX idx_pii_scrubbed (pii_scrubbed);

-- ALTER TABLE peaje_sessions
--     ADD COLUMN insight_count INT DEFAULT 0 AFTER message_count,
--     ADD COLUMN debate_mode BOOLEAN DEFAULT FALSE AFTER source,
--     ADD INDEX idx_debate_mode (debate_mode);

-- ALTER TABLE peaje_patterns
--     ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER pattern_text,
--     ADD COLUMN region VARCHAR(60) DEFAULT 'LATAM' AFTER industry_vertical,
--     ADD COLUMN source_insight_count INT DEFAULT 1 AFTER occurrence_count,
--     ADD COLUMN is_active BOOLEAN DEFAULT TRUE AFTER confidence_score,
--     ADD INDEX idx_industry (industry_vertical),
--     ADD INDEX idx_region (region),
--     ADD INDEX idx_is_active (is_active),
--     ADD INDEX idx_type_industry (pattern_type, industry_vertical);

-- ALTER TABLE peaje_tenants
--     ADD COLUMN industry_vertical VARCHAR(60) NULL AFTER tenant_type,
--     ADD COLUMN punto_medio_access BOOLEAN DEFAULT FALSE AFTER config,
--     ADD INDEX idx_industry (industry_vertical);

-- ═══════════════════════════════════════════════════════════════
-- El Peaje v2.0 — Membrana Neuronal Corporativa
-- 14 Marzo 2026
-- ═══════════════════════════════════════════════════════════════
