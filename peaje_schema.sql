-- ═══════════════════════════════════════════════════════════════
-- EL PEAJE - Schema SQL v1.0
-- Data Flywheel para SHIFTY 2.0
-- Punto Medio: Captura de conocimiento táctil
-- ═══════════════════════════════════════════════════════════════

-- Base de datos: shift_peaje
-- CREATE DATABASE IF NOT EXISTS shift_peaje CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
-- USE shift_peaje;

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_insights
-- Almacena insights extraídos de cada conversación (Taxonomía Ejecutiva)
-- PREPARACIÓN PARA MIGRACIÓN A GRAFO DE CONOCIMIENTO (Neo4j)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_insights (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL COMMENT 'corporate_tenant_uuid',
    session_id VARCHAR(100) NOT NULL COMMENT 'executive_session_id',
    agent_id VARCHAR(50) NOT NULL COMMENT 'agent_swarm_node',
    insight_text TEXT COMMENT 'Estructura anonimizada (Entidad-Contexto-Valor)',
    category VARCHAR(100) COMMENT 'Taxonomía: Riesgos Ciegos, Patrones Sectoriales, Gaps Productividad, Vectores',
    sentiment VARCHAR(20) COMMENT 'positive, negative, neutral',
    confidence_score DECIMAL(3,2) COMMENT 'Score emitido por el LLM Extractor',
    anonymized_hash VARCHAR(64) COMMENT 'SHA-256 hash para anonimización (NER)',
    raw_conversation_hash VARCHAR(64) COMMENT 'Referencia cruzada aislada',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_agent_id (agent_id),
    INDEX idx_category (category),
    INDEX idx_created_at (created_at),
    INDEX idx_tenant_category (tenant_id, category),
    INDEX idx_tenant_agent (tenant_id, agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Insights extraídos de conversaciones - El Peaje v1.0';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_sessions
-- Tracking de sesiones por tenant
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    session_id VARCHAR(100) NOT NULL UNIQUE,
    user_id VARCHAR(100) COMMENT 'Identificador anónimo del usuario',
    message_count INT DEFAULT 0,
    agents_used JSON COMMENT 'Array de IDs de agentes usados en la sesión',
    topics_discussed JSON COMMENT 'Array de tópicos identificados',
    session_duration_seconds INT COMMENT 'Duración de la sesión en segundos',
    source VARCHAR(50) DEFAULT 'standalone' COMMENT 'standalone, brandhub, embed',
    ip_hash VARCHAR(64) COMMENT 'Hash de IP para prevención de abuso',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP NULL,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_session_id (session_id),
    INDEX idx_created_at (created_at),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Sesiones de chat por tenant';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_patterns
-- Inteligencia acumulada - Patrones macro-regionales (Futuros Nodos Neo4j)
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_patterns (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pattern_type VARCHAR(100) NOT NULL COMMENT 'Taxonomía Ejecutiva Macro',
    category VARCHAR(100) NOT NULL,
    pattern_text TEXT NOT NULL COMMENT 'Patrón estructural de inteligencia colectiva',
    occurrence_count INT DEFAULT 1 COMMENT 'Densidad del nodo en la red',
    confidence_score DECIMAL(3,2) COMMENT 'Confianza estadística del patrón',
    related_agents JSON COMMENT 'Agentes que más contribuyen a este patrón',
    tenant_distribution JSON COMMENT 'Distribución por tenant',
    first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_pattern_type (pattern_type),
    INDEX idx_category (category),
    INDEX idx_occurrence_count (occurrence_count),
    INDEX idx_last_seen (last_seen_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Patrones identificados acumulados - Inteligencia colectiva';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: peaje_tenants
-- Configuración y metadata de tenants
-- ═══════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS peaje_tenants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL UNIQUE,
    tenant_name VARCHAR(100) NOT NULL,
    tenant_type VARCHAR(50) COMMENT 'internal, client, partner',
    brand_color VARCHAR(7) DEFAULT '#0047AB',
    logo_url VARCHAR(255),
    allowed_agents JSON COMMENT 'Agentes disponibles para este tenant',
    config JSON COMMENT 'Configuración específica del tenant',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_is_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Tenants configurados en el sistema';

-- ═══════════════════════════════════════════════════════════════
-- INSERTS INICIALES: Tenants
-- ═══════════════════════════════════════════════════════════════
INSERT INTO peaje_tenants (tenant_id, tenant_name, tenant_type, brand_color, allowed_agents) VALUES
('shift', 'Shift Lab', 'internal', '#0047AB', '["pedro","susana","carlos","maria","jorge","lucia","andres","patricia","roberto","carmen","diego","fernanda","martin","sofia","gabriel"]'),
('garnier', 'Garnier', 'client', '#00A651', '["maria","jorge","lucia","andres","carmen"]'),
('tres_pinos', 'Tres Pinos', 'client', '#8B4513', '["maria","jorge","diego","roberto"]')
ON DUPLICATE KEY UPDATE updated_at = CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════
-- VISTAS ÚTILES
-- ═══════════════════════════════════════════════════════════════

-- Vista: Insights recientes por tenant
CREATE OR REPLACE VIEW view_recent_insights AS
SELECT 
    i.*,
    t.tenant_name,
    t.tenant_type
FROM peaje_insights i
JOIN peaje_tenants t ON i.tenant_id = t.tenant_id
WHERE i.created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY i.created_at DESC;

-- Vista: Agentes más utilizados por tenant
CREATE OR REPLACE VIEW view_agent_usage AS
SELECT 
    tenant_id,
    agent_id,
    COUNT(*) as usage_count,
    COUNT(DISTINCT session_id) as unique_sessions
FROM peaje_insights
GROUP BY tenant_id, agent_id
ORDER BY usage_count DESC;

-- Vista: Patrones más frecuentes
CREATE OR REPLACE VIEW view_top_patterns AS
SELECT 
    pattern_type,
    category,
    pattern_text,
    occurrence_count,
    confidence_score
FROM peaje_patterns
WHERE occurrence_count > 5
ORDER BY occurrence_count DESC, confidence_score DESC;

-- ═══════════════════════════════════════════════════════════════
-- STORED PROCEDURES
-- ═══════════════════════════════════════════════════════════════

DELIMITER //

-- Procedimiento: Insertar insight con anonimización
CREATE PROCEDURE sp_insert_insight(
    IN p_tenant_id VARCHAR(50),
    IN p_session_id VARCHAR(100),
    IN p_agent_id VARCHAR(50),
    IN p_insight_text TEXT,
    IN p_category VARCHAR(50),
    IN p_sentiment VARCHAR(20),
    IN p_raw_conversation TEXT
)
BEGIN
    DECLARE v_anonymized_hash VARCHAR(64);
    DECLARE v_conversation_hash VARCHAR(64);
    
    -- Generar hashes (simulado - en producción usar SHA2)
    SET v_anonymized_hash = MD5(CONCAT(p_tenant_id, p_session_id, NOW()));
    SET v_conversation_hash = MD5(p_raw_conversation);
    
    INSERT INTO peaje_insights (
        tenant_id, session_id, agent_id, insight_text,
        category, sentiment, anonymized_hash, raw_conversation_hash
    ) VALUES (
        p_tenant_id, p_session_id, p_agent_id, p_insight_text,
        p_category, p_sentiment, v_anonymized_hash, v_conversation_hash
    );
    
    SELECT LAST_INSERT_ID() as insight_id;
END //

-- Procedimiento: Actualizar o crear patrón
CREATE PROCEDURE sp_upsert_pattern(
    IN p_pattern_type VARCHAR(50),
    IN p_category VARCHAR(50),
    IN p_pattern_text TEXT
)
BEGIN
    DECLARE v_existing_id INT;
    
    SELECT id INTO v_existing_id
    FROM peaje_patterns
    WHERE pattern_type = p_pattern_type 
      AND category = p_category
      AND pattern_text = p_pattern_text
    LIMIT 1;
    
    IF v_existing_id IS NOT NULL THEN
        UPDATE peaje_patterns 
        SET occurrence_count = occurrence_count + 1,
            last_seen_at = NOW()
        WHERE id = v_existing_id;
    ELSE
        INSERT INTO peaje_patterns (pattern_type, category, pattern_text)
        VALUES (p_pattern_type, p_category, p_pattern_text);
    END IF;
END //

DELIMITER ;

-- ═══════════════════════════════════════════════════════════════
-- COMENTARIOS FINALES
-- ═══════════════════════════════════════════════════════════════
-- 
-- Para ejecutar este schema en phpMyAdmin:
-- 1. Seleccionar la base de datos shift_peaje (o crearla)
-- 2. Importar este archivo SQL
-- 3. Verificar que las tablas se crearon correctamente
--
-- Notas:
-- - Todos los campos de texto usan utf8mb4 para soporte completo de emojis
-- - Los índices están optimizados para queries frecuentes
-- - JSON columns requieren MySQL 5.7+ o MariaDB 10.2+
-- - Para MySQL < 5.7, reemplazar JSON con TEXT y manejar en la aplicación
--
-- El Peaje v1.0 - 12 Marzo 2026
-- ═══════════════════════════════════════════════════════════════
