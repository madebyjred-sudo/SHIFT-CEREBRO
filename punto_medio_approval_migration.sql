-- ═══════════════════════════════════════════════════════════════
-- PUNTO MEDIO — CONTROLLED UPDATES MIGRATION v2.1
-- Adds approval gates so consolidations stay "grey" (pending)
-- until manually reviewed and "greened" (approved).
-- ═══════════════════════════════════════════════════════════════

-- 1. Add approval_status, reviewed_by, reviewed_at to punto_medio_consolidated
ALTER TABLE punto_medio_consolidated
  ADD COLUMN approval_status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending'
    COMMENT 'pending = grey (not injected), approved = green (live in RAG), rejected = discarded'
    AFTER is_active,
  ADD COLUMN reviewed_by VARCHAR(100) NULL
    COMMENT 'User or agent who approved/rejected'
    AFTER approval_status,
  ADD COLUMN reviewed_at TIMESTAMP NULL
    COMMENT 'When the review happened'
    AFTER reviewed_by,
  ADD INDEX idx_approval_status (approval_status);

-- 2. Add approval_status, reviewed_by, reviewed_at to peaje_patterns
ALTER TABLE peaje_patterns
  ADD COLUMN approval_status ENUM('pending', 'approved', 'rejected') NOT NULL DEFAULT 'pending'
    COMMENT 'pending = not injected into RAG, approved = live'
    AFTER is_active,
  ADD COLUMN reviewed_by VARCHAR(100) NULL
    COMMENT 'User or agent who approved/rejected'
    AFTER approval_status,
  ADD COLUMN reviewed_at TIMESTAMP NULL
    COMMENT 'When the review happened'
    AFTER reviewed_by,
  ADD INDEX idx_approval_status (approval_status);

-- 3. Update the active view to respect approval_status
DROP VIEW IF EXISTS view_punto_medio_active;
CREATE VIEW view_punto_medio_active AS
SELECT
    pmc.id, pmc.scope, pmc.tenant_id, pmc.category, pmc.industry_vertical,
    pmc.consolidated_text, pmc.executive_brief,
    pmc.source_insight_count, pmc.contributing_tenants, pmc.confidence_score,
    pmc.approval_status, pmc.reviewed_by, pmc.reviewed_at,
    pmc.version, pmc.last_consolidated_at, pmc.created_at
FROM punto_medio_consolidated pmc
WHERE pmc.is_active = TRUE
  AND pmc.approval_status = 'approved'
  AND (pmc.expires_at IS NULL OR pmc.expires_at > NOW());
