-- ============================================================
-- Cerebro Training Schema v1 — Fine-tune ready dataset capture
-- ============================================================
-- Tres tablas independientes pero relacionadas que capturan los
-- raw materials para entrenar "Shift Foundation" hacia 2027:
--
--   cerebro_skills_versions    : snapshot inmutable de cada skill
--                                YAML cuando cambia. Permite trazar
--                                qué versión de Carmen / Roberto /
--                                etc generó cada respuesta.
--
--   cerebro_training_pairs     : turn completo (system, user,
--                                response) con metadata de versionado
--                                y label de calidad. Esto es el
--                                dataset SFT.
--
--   cerebro_feedback_events    : raw signal del web component
--                                <cerebro-feedback>. Per-response
--                                like/dislike, chips, textbox + NPS
--                                per-session. Esto es el dataset RLHF.
--
-- Idempotente, aditivo. Aplicar:
--   railway ssh --service shift-cerebro -- /opt/venv/bin/python apply_training_schema.py
-- ============================================================

-- ─────────────────────────────────────────────────────────────
-- 1. cerebro_skills_versions
-- ─────────────────────────────────────────────────────────────
-- Cada vez que un skill_prompt cambia, se snapshotea acá. El job
-- de captura calcula sha256 del skill_prompt al momento de cada
-- ingest y si no existe, inserta el snapshot.

CREATE TABLE IF NOT EXISTS cerebro_skills_versions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    agent_id VARCHAR(50) NOT NULL,
    version VARCHAR(40) NOT NULL,
    skill_prompt_hash CHAR(64) NOT NULL,
    skill_prompt MEDIUMTEXT NOT NULL,
    role VARCHAR(120),
    pod INT,
    pod_name VARCHAR(80),
    keywords JSON,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_hash (agent_id, skill_prompt_hash),
    INDEX idx_agent_version (agent_id, version),
    INDEX idx_captured (captured_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ─────────────────────────────────────────────────────────────
-- 2. cerebro_training_pairs
-- ─────────────────────────────────────────────────────────────
-- El turn completo. ESTE es el dataset SFT. Cada vez que un
-- agent responde y el insight pasa por /peaje/ingest, también
-- se persiste acá el (system, user, response) tuple.
--
-- quality_label evoluciona:
--   'unverified'  → recién creado, sin feedback
--   'liked'       → al menos un like, sin dislikes
--   'disliked'    → al menos un dislike (necesita revisión)
--   'approved'    → operador en /admin/punto-medio aprobó
--   'rejected'    → operador rechazó
--   'corrected'   → human_correction tiene texto alternativo

CREATE TABLE IF NOT EXISTS cerebro_training_pairs (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    insight_id BIGINT NULL COMMENT 'FK lógica → peaje_insights.id',
    message_id VARCHAR(120) NOT NULL UNIQUE
        COMMENT 'ID estable que el frontend usa para anclar feedback al turn',

    app_id VARCHAR(32) NOT NULL,
    tenant_id VARCHAR(50) NOT NULL,
    agent_id VARCHAR(50) NOT NULL,
    skill_version_id INT NULL COMMENT 'FK lógica → cerebro_skills_versions.id',

    -- Raw turn (input + output)
    system_prompt MEDIUMTEXT NOT NULL,
    user_message TEXT NOT NULL,
    user_message_scrubbed TEXT NULL,
    assistant_response MEDIUMTEXT NOT NULL,

    -- Optional reasoning trace (chain of thought) si el agente lo expone
    reasoning_trace JSON NULL,

    -- Modelo upstream que generó la respuesta
    upstream_model VARCHAR(80) NULL,

    -- Quality lifecycle
    quality_label ENUM(
        'unverified','liked','disliked','approved','rejected','corrected'
    ) NOT NULL DEFAULT 'unverified',
    human_correction MEDIUMTEXT NULL
        COMMENT 'Si quality_label=corrected, response alternativa preferida',

    -- Aggregated feedback signals (cached para queries rápidos)
    like_count INT NOT NULL DEFAULT 0,
    dislike_count INT NOT NULL DEFAULT 0,
    avg_rating DECIMAL(3,2) NULL COMMENT 'Si tier de stars/NPS, promedio',
    feedback_count INT NOT NULL DEFAULT 0,

    -- Legal status flag — se usa para filtrar el dataset al exportar
    -- 'unrestricted' = libre uso (kimi/llama/qwen — tunel material)
    -- 'tos_restricted' = TOS prohíbe training (claude/gpt outputs)
    -- 'consented' = cliente firmó cláusula explícita
    legal_status ENUM('unrestricted','tos_restricted','consented')
        NOT NULL DEFAULT 'unrestricted',

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_app (app_id),
    INDEX idx_tenant (tenant_id),
    INDEX idx_agent (agent_id),
    INDEX idx_quality (quality_label),
    INDEX idx_app_quality (app_id, quality_label),
    INDEX idx_legal (legal_status),
    INDEX idx_insight (insight_id),
    INDEX idx_skill_version (skill_version_id),
    INDEX idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ─────────────────────────────────────────────────────────────
-- 3. cerebro_feedback_events
-- ─────────────────────────────────────────────────────────────
-- Raw events del web component. Append-only — nunca se mutan
-- las filas, se agregan más. La columna feedback_type permite
-- mezclar:
--   'like'         → user hizo click en 👍
--   'dislike'      → 👎 (puede traer chips_reasons + free_text)
--   'chip'         → user marcó un chip de razón ("alucinó", "vago", etc)
--   'free_text'    → comment libre
--   'session_nps'  → al cerrar sesión, score 0-10 + opcional comment
--   'star_rating'  → 1-5 stars (futuro, no en MVP)

CREATE TABLE IF NOT EXISTS cerebro_feedback_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- Anchor — qué se está rateando
    message_id VARCHAR(120) NULL
        COMMENT 'NULL para session_nps (ranking global), set para per-message',
    session_id VARCHAR(120) NOT NULL,
    app_id VARCHAR(32) NOT NULL,
    tenant_id VARCHAR(50) NOT NULL,

    -- Identidad — Q5: B con anon fallback
    user_id VARCHAR(120) NULL
        COMMENT 'Supabase JWT sub o equivalente. NULL = anon',
    user_anonymous BOOLEAN NOT NULL DEFAULT FALSE,

    -- El feedback en sí
    feedback_type ENUM(
        'like','dislike','chip','free_text','session_nps','star_rating'
    ) NOT NULL,
    rating_value SMALLINT NULL
        COMMENT '1-5 stars, 0-10 NPS, NULL para like/dislike binary',
    chip_key VARCHAR(60) NULL
        COMMENT 'Una de las claves del taxonomy de chips: hallucinated|vague|wrong_tone|missed_point|too_long|perfect',
    free_text TEXT NULL,

    -- Context para debugging y signal
    upstream_model VARCHAR(80) NULL,
    agent_id VARCHAR(50) NULL,
    user_agent VARCHAR(255) NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    INDEX idx_message (message_id),
    INDEX idx_session (session_id),
    INDEX idx_app (app_id),
    INDEX idx_user (user_id),
    INDEX idx_type (feedback_type),
    INDEX idx_created (created_at),
    INDEX idx_app_type (app_id, feedback_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ─────────────────────────────────────────────────────────────
-- 4. Vista de cluster ratings — para el job consolidador del
--    Punto Medio. Auto-promote opera acá: cluster con avg_rating
--    ≥ 4.0 y ≥ 30 ratings → candidate for auto-approval.
-- ─────────────────────────────────────────────────────────────

CREATE OR REPLACE VIEW v_training_pairs_with_feedback AS
SELECT
    tp.id,
    tp.message_id,
    tp.app_id,
    tp.tenant_id,
    tp.agent_id,
    tp.quality_label,
    tp.upstream_model,
    tp.legal_status,
    tp.created_at,
    -- Aggregated from feedback events
    COALESCE(
        (SELECT COUNT(*) FROM cerebro_feedback_events fe
         WHERE fe.message_id = tp.message_id AND fe.feedback_type = 'like'),
        0
    ) AS likes,
    COALESCE(
        (SELECT COUNT(*) FROM cerebro_feedback_events fe
         WHERE fe.message_id = tp.message_id AND fe.feedback_type = 'dislike'),
        0
    ) AS dislikes,
    (SELECT GROUP_CONCAT(DISTINCT chip_key)
     FROM cerebro_feedback_events fe
     WHERE fe.message_id = tp.message_id AND fe.feedback_type = 'chip'
    ) AS chip_reasons
FROM cerebro_training_pairs tp;
