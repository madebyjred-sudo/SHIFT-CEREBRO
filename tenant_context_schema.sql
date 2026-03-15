-- ═══════════════════════════════════════════════════════════════
-- TENANT CONSTITUTION v2.0 — Contexto Corporativo Estructurado
-- Shift AI Gateway — De hardcodeo a escala Enterprise
-- 
-- Reemplaza TENANT_CONTEXTS hardcodeado en main.py
-- Soporta jerarquía: Holding → Division → Business Unit
-- Token budget: ~800 tokens compilados
-- ═══════════════════════════════════════════════════════════════

-- ═══════════════════════════════════════════════════════════════
-- TABLA: tenant_constitutions
-- El ADN corporativo de cada cliente, estructurado para LLMs
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tenant_constitutions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL UNIQUE COMMENT 'ID único del tenant (ej: garnier, coca_cola)',
    tenant_name VARCHAR(100) NOT NULL COMMENT 'Nombre legible del tenant',
    slug VARCHAR(100) UNIQUE NOT NULL COMMENT 'URL-friendly identifier',
    
    -- Jerarquía para multinacionales/holdings
    parent_id VARCHAR(50) NULL COMMENT 'tenant_id del padre (para divisions)',
    division_type VARCHAR(50) NULL COMMENT 'holding | subsidiary | division | business_unit | brand',
    hierarchy_path VARCHAR(500) NULL COMMENT 'Path materializado: garnier/media/planning',
    
    -- Identidad Corporativa (Core DNA)
    mission TEXT COMMENT 'Respuesta a: ¿qué echarían de menos si desaparecemos?',
    vision TEXT COMMENT 'Horizonte de 3-5 años',
    values_json JSON COMMENT '[{"name": "Velocidad", "desc": "Decisiones en 48h"}]',
    
    -- Contexto de Negocio
    industry VARCHAR(100) COMMENT 'Vertical (media, fintech, retail, etc)',
    sub_industry VARCHAR(100) COMMENT 'Sub-vertical específica',
    target_market TEXT COMMENT 'ICP: quién es el cliente ideal',
    core_challenges TEXT COMMENT 'Top 3 dolores que resuelven',
    competitive_landscape TEXT COMMENT 'Top 3 competidores y diferenciadores',
    
    -- Brand Voice & Personalidad
    tone_voice VARCHAR(100) COMMENT 'Formal-Ejecutivo | Bold-Disruptivo | Empático-Experto',
    brand_archetype VARCHAR(50) COMMENT 'The Sage, The Explorer, The Caregiver, etc',
    negative_constraints JSON COMMENT 'Palabras/frases prohibidas: ["barato", "descuento"]',
    communication_do JSON COMMENT 'Qué SÍ hacer: ["respaldar con datos", "ser conciso"]',
    
    -- Contexto Operativo
    kpis_focus JSON COMMENT '[{"name": "CAC", "why": "SaaS growth"}]',
    internal_jargon JSON COMMENT '{"Shift": "Transformación radical", "Peaje": "Extracción insights"}',
    strategic_priorities JSON COMMENT 'Prioridades del año fiscal actual',
    
    -- LATAM Context (especificidad regional)
    region_focus VARCHAR(50) COMMENT 'LATAM, Andino, ConoSur, México, etc',
    local_nuances TEXT COMMENT 'Matices culturales del mercado local',
    
    -- Metadata & Versionamiento
    version INT DEFAULT 1 COMMENT 'Versión del contexto (para audit trail)',
    is_active BOOLEAN DEFAULT TRUE,
    created_by VARCHAR(100) COMMENT 'Email del C-Level que completó onboarding',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    
    -- Constraints
    INDEX idx_tenant_id (tenant_id),
    INDEX idx_parent_id (parent_id),
    INDEX idx_division_type (division_type),
    INDEX idx_industry (industry),
    INDEX idx_is_active (is_active),
    CONSTRAINT fk_parent_tenant 
        FOREIGN KEY (parent_id) REFERENCES tenant_constitutions(tenant_id) 
        ON DELETE SET NULL,
    CONSTRAINT check_no_self_parent CHECK (tenant_id <> parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Constitución corporativa estructurada para inyección en prompts de agentes';

-- ═══════════════════════════════════════════════════════════════
-- TABLA: tenant_constitution_history
-- Audit trail de cambios (compliance & versionamiento)
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS tenant_constitution_history (
    id INT AUTO_INCREMENT PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    version INT NOT NULL,
    changed_fields JSON NOT NULL COMMENT 'Qué campos cambiaron en esta versión',
    previous_values JSON COMMENT 'Snapshot de valores anteriores',
    changed_by VARCHAR(100) COMMENT 'Quién hizo el cambio',
    change_reason TEXT COMMENT 'Por qué se hizo el cambio',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_tenant_version (tenant_id, version),
    INDEX idx_created_at (created_at),
    FOREIGN KEY (tenant_id) REFERENCES tenant_constitutions(tenant_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='Historial de versiones de la constitución del tenant';

-- ═══════════════════════════════════════════════════════════════
-- SEED DATA: Tenant Shift Lab (ejemplo de referencia)
-- ═══════════════════════════════════════════════════════════════

INSERT INTO tenant_constitutions (
    tenant_id, tenant_name, slug, division_type,
    mission, vision, values_json,
    industry, target_market, core_challenges,
    tone_voice, brand_archetype, negative_constraints,
    kpis_focus, internal_jargon, strategic_priorities,
    region_focus, local_nuances,
    version, is_active, created_by
) VALUES (
    'shift', 
    'Shift Lab', 
    'shift-lab',
    'holding',
    ' Democratizar el acceso a consultoría estratégica de clase mundial para empresas LATAM mediante Inteligencia Artificial.',
    'Ser el sistema operativo de la toma de decisiones empresariales en América Latina para 2030.',
    '[
        {"name": "Velocidad", "desc": "Decisiones en horas, no semanas"},
        {"name": "Rigor Técnico", "desc": "Datos antes que opiniones"},
        {"name": "Diseño Impecable", "desc": "La forma es función"}
    ]',
    'tech_saas',
    'C-Level de empresas medianas y grandes en LATAM que necesitan velocidad estratégica',
    'Inercia organizacional, análisis parálisis, falta de accesibilidad a consultoría de élite',
    'Bold-Disruptivo',
    'The Explorer',
    '["modelo de lenguaje", "como agente", "swarm", "AI dice", "no puedo"]',    '[
        {"name": "Time-to-Insight", "why": "Velocidad de decisión"},
        {"name": "NPS del Cliente", "why": "Calidad percebida"}
    ]',
    '{"Punto Medio": "Memoria institucional materializada", "El Peaje": "Sistema de extracción de insights", "Shift Way": "Metodología de respuesta"}',
    'Escalar arquitectura multi-tenant, lanzar mobile app, expandir a 3 países nuevos',
    'LATAM',
    'Los ejecutivos LATAM valoran la relación personal y la velocidad sobre la burocracia',
    1,
    TRUE,
    'admin@shiftlab.co'
) ON DUPLICATE KEY UPDATE
    mission = VALUES(mission),
    vision = VALUES(vision),
    updated_at = CURRENT_TIMESTAMP;

-- ═══════════════════════════════════════════════════════════════
-- VISTA: tenant_context_lineage
-- Para debugging y visualización de jerarquía
-- ═══════════════════════════════════════════════════════════════

CREATE OR REPLACE VIEW view_tenant_context_lineage AS
WITH RECURSIVE lineage AS (
    -- Base: tenants raíz (sin padre)
    SELECT 
        tenant_id, tenant_name, parent_id, division_type, hierarchy_path,
        0 as depth,
        tenant_id as root_id,
        CAST(tenant_id AS CHAR(500)) as path
    FROM tenant_constitutions
    WHERE parent_id IS NULL AND is_active = TRUE
    
    UNION ALL
    
    -- Recursivo: hijos
    SELECT 
        tc.tenant_id, tc.tenant_name, tc.parent_id, tc.division_type, tc.hierarchy_path,
        l.depth + 1,
        l.root_id,
        CONCAT(l.path, ' > ', tc.tenant_id)
    FROM tenant_constitutions tc
    INNER JOIN lineage l ON tc.parent_id = l.tenant_id
    WHERE tc.is_active = TRUE
)
SELECT 
    l.*,
    parent.tenant_name as parent_name
FROM lineage l
LEFT JOIN tenant_constitutions parent ON l.parent_id = parent.tenant_id
ORDER BY l.path;

-- ═══════════════════════════════════════════════════════════════
-- FIN DEL SCHEMA
-- ═══════════════════════════════════════════════════════════════