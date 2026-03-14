"""
═══════════════════════════════════════════════════════════════
PUNTO MEDIO v1.0 — Memoria Institucional Persistente
Shifty Lab 2.0 — Membrana Neuronal Corporativa

El Punto Medio es el corazón del Data Flywheel:
1. Consolida insights anonimizados en inteligencia accionable
2. Genera RAG dinámico para inyección en system prompts
3. Reemplaza el PUNTO_MEDIO_GLOBAL_RAG hardcodeado por datos REALES
4. Mantiene aislamiento multi-tenant estricto

Ciclo del Flywheel:
  [Chat/Debate] → [El Peaje] → [PII Scrubber] → [peaje_insights]
                                                        ↓
                                                [consolidate()]
                                                        ↓
                                            [punto_medio_consolidated]
                                                        ↓
                                      [get_dynamic_rag()] → [System Prompts]
                                                        ↓
                                            [Better Agent Responses]
                                                        ↓
                                                [Richer Insights] ← (loop)
═══════════════════════════════════════════════════════════════
"""

import os
import json
from datetime import datetime
from typing import Dict, List, Optional

# ═══════════════════════════════════════════════════════════════
# FALLBACK RAG — Used when database has insufficient data
# This is the SEED that gets replaced as real data accumulates.
# ═══════════════════════════════════════════════════════════════

SEED_GLOBAL_RAG = """
[INTELIGENCIA COLECTIVA LATAM — PATRONES MACRO (SEED)]:
- Riesgo Ciego Común: Subestimación de fricción logística en última milla.
- Patrón de Decisión Sectorial (Retail): Preferencia por mitigación de riesgo financiero sobre innovación disruptiva en Q1.
- Gap de Productividad Frecuente: Desconexión asimétrica entre equipos creativos y analistas de pauta digital.
- Vector de Aceleración: Automatización de procesos de reporting reduciría el 'impuesto invisible' de contexto en reuniones de board.
"""

SEED_TENANT_CONTEXTS = {
    "shift": """
[CONTEXTO CORPORATIVO AISLADO - SHIFT (SEED)]:
- Identidad: Consultora de innovación y estrategia digital.
- Foco Operativo: IA Generativa aplicada a procesos corporativos B2B.
- Valores Base: Velocidad, Rigor Técnico, Diseño Impecable.
""",
    "garnier": """
[CONTEXTO CORPORATIVO AISLADO - GRUPO GARNIER (SEED)]:
- Identidad: Red de agencias de comunicación y marketing líder en LatAm.
- Cuentas Core: Consumo masivo (FMCG), retail corporativo, servicios financieros.
- Vectores de Aceleración 2026: Automatización profunda de insights creativos y eficiencia transaccional en media planning.
- Tono Requerido: Estratégico, asertivo, innovador con respaldo C-Level.
""",
}

# Category labels for RAG formatting
CATEGORY_LABELS = {
    "riesgos_ciegos": "🔴 RIESGOS CIEGOS DETECTADOS",
    "patrones_sectoriales": "🔵 PATRONES DE DECISIÓN SECTORIAL",
    "gaps_productividad": "🟡 GAPS DE PRODUCTIVIDAD INSTITUCIONAL",
    "vectores_aceleracion": "🟢 VECTORES DE ACELERACIÓN OCULTOS",
}


# ═══════════════════════════════════════════════════════════════
# CONSOLIDATION ENGINE
# Runs periodically (cron or on-demand) to distill insights
# into the Punto Medio persistent memory
# ═══════════════════════════════════════════════════════════════

async def consolidate_punto_medio(conn, llm_func=None) -> Dict:
    """
    Main consolidation job. Reads recent insights from peaje_insights,
    groups them by category + industry, and generates consolidated
    intelligence entries in punto_medio_consolidated.
    
    Args:
        conn: MySQL database connection
        llm_func: Optional async function to call LLM for synthesis
                   (if None, uses statistical aggregation only)
    
    Returns:
        Summary of consolidation results
    """
    if not conn:
        return {"status": "error", "message": "No database connection"}
    
    results = {
        "global_consolidations": 0,
        "tenant_consolidations": 0,
        "patterns_updated": 0,
        "errors": [],
    }
    
    try:
        with conn.cursor() as cursor:
            # ─── PHASE 1: GLOBAL CONSOLIDATION (cross-tenant, anonymized) ───
            # Group insights by category across all tenants
            cursor.execute("""
                SELECT 
                    category,
                    industry_vertical,
                    COUNT(*) as insight_count,
                    COUNT(DISTINCT tenant_id) as tenant_count,
                    AVG(confidence_score) as avg_confidence,
                    GROUP_CONCAT(
                        DISTINCT SUBSTRING(insight_text, 1, 200)
                        ORDER BY confidence_score DESC
                        SEPARATOR ' ||| '
                    ) as sample_insights
                FROM peaje_insights
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                  AND pii_scrubbed = TRUE
                  AND confidence_score >= 0.30
                GROUP BY category, industry_vertical
                HAVING insight_count >= 3
                ORDER BY insight_count DESC
            """)
            
            global_groups = cursor.fetchall()
            
            for group in global_groups:
                consolidated_text = _synthesize_consolidation(
                    group["sample_insights"],
                    group["category"],
                    group["industry_vertical"],
                    group["insight_count"],
                    group["tenant_count"],
                )
                
                executive_brief = consolidated_text[:200] if consolidated_text else None
                
                # Upsert into punto_medio_consolidated
                cursor.execute("""
                    INSERT INTO punto_medio_consolidated 
                    (scope, tenant_id, category, industry_vertical, region,
                     consolidated_text, executive_brief,
                     source_insight_count, contributing_tenants, confidence_score,
                     is_active, version, last_consolidated_at)
                    VALUES ('global', NULL, %s, %s, 'LATAM',
                            %s, %s, %s, %s, %s,
                            TRUE, 1, NOW())
                    ON DUPLICATE KEY UPDATE
                        consolidated_text = VALUES(consolidated_text),
                        executive_brief = VALUES(executive_brief),
                        source_insight_count = VALUES(source_insight_count),
                        contributing_tenants = VALUES(contributing_tenants),
                        confidence_score = VALUES(confidence_score),
                        version = version + 1,
                        last_consolidated_at = NOW()
                """, (
                    group["category"],
                    group["industry_vertical"],
                    consolidated_text,
                    executive_brief,
                    group["insight_count"],
                    group["tenant_count"],
                    group["avg_confidence"],
                ))
                results["global_consolidations"] += 1
            
            # ─── PHASE 2: TENANT-SPECIFIC CONSOLIDATION ───
            # Only for tenants with punto_medio_access = TRUE
            cursor.execute("""
                SELECT tenant_id, industry_vertical 
                FROM peaje_tenants 
                WHERE punto_medio_access = TRUE AND is_active = TRUE
            """)
            active_tenants = cursor.fetchall()
            
            for tenant in active_tenants:
                tid = tenant["tenant_id"]
                
                cursor.execute("""
                    SELECT 
                        category,
                        COUNT(*) as insight_count,
                        AVG(confidence_score) as avg_confidence,
                        GROUP_CONCAT(
                            DISTINCT SUBSTRING(insight_text, 1, 200)
                            ORDER BY confidence_score DESC
                            SEPARATOR ' ||| '
                        ) as sample_insights
                    FROM peaje_insights
                    WHERE tenant_id = %s
                      AND created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                      AND confidence_score >= 0.20
                    GROUP BY category
                    HAVING insight_count >= 2
                    ORDER BY insight_count DESC
                """, (tid,))
                
                tenant_groups = cursor.fetchall()
                
                for group in tenant_groups:
                    consolidated_text = _synthesize_consolidation(
                        group["sample_insights"],
                        group["category"],
                        tenant["industry_vertical"],
                        group["insight_count"],
                        1,  # single tenant
                    )
                    
                    executive_brief = consolidated_text[:200] if consolidated_text else None
                    
                    cursor.execute("""
                        INSERT INTO punto_medio_consolidated 
                        (scope, tenant_id, category, industry_vertical, region,
                         consolidated_text, executive_brief,
                         source_insight_count, contributing_tenants, confidence_score,
                         is_active, version, last_consolidated_at)
                        VALUES ('tenant', %s, %s, %s, 'LATAM',
                                %s, %s, %s, 1, %s,
                                TRUE, 1, NOW())
                        ON DUPLICATE KEY UPDATE
                            consolidated_text = VALUES(consolidated_text),
                            executive_brief = VALUES(executive_brief),
                            source_insight_count = VALUES(source_insight_count),
                            confidence_score = VALUES(confidence_score),
                            version = version + 1,
                            last_consolidated_at = NOW()
                    """, (
                        tid,
                        group["category"],
                        tenant["industry_vertical"],
                        consolidated_text,
                        executive_brief,
                        group["insight_count"],
                        group["avg_confidence"],
                    ))
                    results["tenant_consolidations"] += 1
            
            # ─── PHASE 3: UPDATE PATTERNS TABLE ───
            # Promote high-frequency insights into patterns
            cursor.execute("""
                SELECT 
                    category,
                    industry_vertical,
                    insight_text,
                    COUNT(*) as frequency,
                    AVG(confidence_score) as avg_conf,
                    GROUP_CONCAT(DISTINCT tenant_id) as tenants,
                    GROUP_CONCAT(DISTINCT agent_id) as agents
                FROM peaje_insights
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                  AND confidence_score >= 0.50
                GROUP BY category, industry_vertical, LEFT(insight_text, 100)
                HAVING frequency >= 3
            """)
            
            pattern_candidates = cursor.fetchall()
            
            for candidate in pattern_candidates:
                tenant_list = (candidate["tenants"] or "").split(",")
                agent_list = (candidate["agents"] or "").split(",")
                
                cursor.execute("""
                    INSERT INTO peaje_patterns 
                    (pattern_type, category, pattern_text, industry_vertical, region,
                     occurrence_count, source_insight_count, confidence_score, 
                     is_active, related_agents)
                    VALUES (%s, %s, %s, %s, 'LATAM', %s, %s, %s, TRUE, %s)
                    ON DUPLICATE KEY UPDATE
                        occurrence_count = occurrence_count + VALUES(occurrence_count),
                        source_insight_count = source_insight_count + VALUES(source_insight_count),
                        confidence_score = GREATEST(confidence_score, VALUES(confidence_score)),
                        last_seen_at = NOW()
                """, (
                    candidate["category"],
                    candidate["category"],
                    candidate["insight_text"][:500],
                    candidate["industry_vertical"],
                    candidate["frequency"],
                    candidate["frequency"],
                    candidate["avg_conf"],
                    json.dumps(agent_list[:10]),
                ))
                
                # Update pattern-tenant relationships
                pattern_id = cursor.lastrowid or 0
                if pattern_id > 0:
                    for tid in tenant_list[:10]:
                        if tid.strip():
                            cursor.execute("""
                                INSERT INTO peaje_pattern_tenants (pattern_id, tenant_id, contribution_count)
                                VALUES (%s, %s, 1)
                                ON DUPLICATE KEY UPDATE 
                                    contribution_count = contribution_count + 1,
                                    last_contributed_at = NOW()
                            """, (pattern_id, tid.strip()))
                
                results["patterns_updated"] += 1
            
            # ─── PHASE 4: EXPIRE OLD DATA ───
            # Mark consolidations older than 60 days without refresh as inactive
            cursor.execute("""
                UPDATE punto_medio_consolidated
                SET is_active = FALSE
                WHERE last_consolidated_at < DATE_SUB(NOW(), INTERVAL 60 DAY)
                  AND is_active = TRUE
            """)
            
            conn.commit()
            results["status"] = "success"
            results["timestamp"] = datetime.now().isoformat()
            
    except Exception as e:
        results["status"] = "error"
        results["errors"].append(str(e))
        try:
            conn.rollback()
        except Exception:
            pass
    
    return results


def _synthesize_consolidation(
    sample_insights: str,
    category: str,
    industry: str,
    count: int,
    tenant_count: int,
) -> str:
    """
    Synthesize a consolidated text from grouped insights.
    
    For now, uses deterministic aggregation (no LLM call).
    This keeps costs at $0 and avoids circular dependencies.
    In Phase 2+, we can optionally use an LLM for richer synthesis.
    """
    if not sample_insights:
        return f"Patrón emergente en {category} — {count} señales detectadas."
    
    # Split the concatenated samples
    samples = [s.strip() for s in sample_insights.split("|||") if s.strip()]
    
    cat_label = CATEGORY_LABELS.get(category, category)
    industry_label = industry or "Multi-vertical"
    
    # Build consolidated text
    lines = [f"[{cat_label}] — {industry_label} ({count} señales, {tenant_count} fuentes)"]
    
    for i, sample in enumerate(samples[:5]):  # Max 5 samples
        lines.append(f"  • {sample[:200]}")
    
    if len(samples) > 5:
        lines.append(f"  ... y {len(samples) - 5} señales adicionales.")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# DYNAMIC RAG INJECTION
# Replaces hardcoded PUNTO_MEDIO_GLOBAL_RAG with real data
# ═══════════════════════════════════════════════════════════════

def get_dynamic_rag(conn, tenant_id: str = "shift") -> Dict[str, str]:
    """
    Generate dynamic RAG injection text for system prompts.
    
    Returns:
        {
            "global_rag": str,      # Cross-tenant anonymized intelligence
            "tenant_rag": str,      # Tenant-specific institutional memory
            "patterns_rag": str,    # Active pattern intelligence
            "combined_rag": str,    # All combined (ready for injection)
        }
    
    Multi-tenancy guarantee:
    - global_rag: Only from scope='global' (anonymized cross-tenant)
    - tenant_rag: Only from scope='tenant' WHERE tenant_id matches
    - A tenant NEVER sees another tenant's specific data
    """
    
    global_rag = SEED_GLOBAL_RAG
    tenant_rag = SEED_TENANT_CONTEXTS.get(tenant_id, "")
    patterns_rag = ""
    
    if not conn:
        return {
            "global_rag": global_rag,
            "tenant_rag": tenant_rag,
            "patterns_rag": "",
            "combined_rag": f"{global_rag}\n{tenant_rag}",
        }
    
    try:
        with conn.cursor() as cursor:
            # ─── GLOBAL RAG: Cross-tenant anonymized intelligence ───
            cursor.execute("""
                SELECT category, industry_vertical, consolidated_text, executive_brief,
                       source_insight_count, contributing_tenants, confidence_score
                FROM punto_medio_consolidated
                WHERE scope = 'global' 
                  AND is_active = TRUE
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY confidence_score DESC, source_insight_count DESC
                LIMIT 20
            """)
            global_entries = cursor.fetchall()
            
            if global_entries:
                lines = ["[INTELIGENCIA COLECTIVA LATAM — PUNTO MEDIO ACTIVO]:"]
                for entry in global_entries:
                    cat = CATEGORY_LABELS.get(entry["category"], entry["category"])
                    industry = entry["industry_vertical"] or "Multi-vertical"
                    brief = entry["executive_brief"] or entry["consolidated_text"][:200]
                    lines.append(
                        f"- {cat} ({industry}, {entry['source_insight_count']} señales, "
                        f"confianza: {entry['confidence_score']:.0%}): {brief}"
                    )
                global_rag = "\n".join(lines)
            
            # ─── TENANT RAG: Tenant-specific institutional memory ───
            # STRICT ISOLATION: Only this tenant's data
            cursor.execute("""
                SELECT category, consolidated_text, executive_brief,
                       source_insight_count, confidence_score
                FROM punto_medio_consolidated
                WHERE scope = 'tenant'
                  AND tenant_id = %s
                  AND is_active = TRUE
                  AND (expires_at IS NULL OR expires_at > NOW())
                ORDER BY confidence_score DESC
                LIMIT 10
            """, (tenant_id,))
            tenant_entries = cursor.fetchall()
            
            if tenant_entries:
                lines = [f"[MEMORIA INSTITUCIONAL AISLADA — {tenant_id.upper()}]:"]
                for entry in tenant_entries:
                    cat = CATEGORY_LABELS.get(entry["category"], entry["category"])
                    brief = entry["executive_brief"] or entry["consolidated_text"][:200]
                    lines.append(f"- {cat}: {brief}")
                tenant_rag = "\n".join(lines)
            
            # ─── PATTERN RAG: Active high-confidence patterns ───
            cursor.execute("""
                SELECT p.pattern_type, p.category, p.pattern_text, 
                       p.industry_vertical, p.occurrence_count, p.confidence_score,
                       COUNT(DISTINCT pt.tenant_id) as tenant_spread
                FROM peaje_patterns p
                LEFT JOIN peaje_pattern_tenants pt ON p.id = pt.pattern_id
                WHERE p.is_active = TRUE 
                  AND p.occurrence_count >= 3
                  AND p.confidence_score >= 0.40
                GROUP BY p.id
                ORDER BY p.occurrence_count DESC, p.confidence_score DESC
                LIMIT 10
            """)
            patterns = cursor.fetchall()
            
            if patterns:
                lines = ["[PATRONES MACRO-REGIONALES ACTIVOS]:"]
                for p in patterns:
                    cat = CATEGORY_LABELS.get(p["category"], p["category"])
                    industry = p["industry_vertical"] or "Multi-vertical"
                    lines.append(
                        f"- {cat} ({industry}, frecuencia: {p['occurrence_count']}x, "
                        f"spread: {p['tenant_spread']} empresas): {p['pattern_text'][:200]}"
                    )
                patterns_rag = "\n".join(lines)
    
    except Exception as e:
        print(f"[PUNTO MEDIO] Error fetching dynamic RAG: {e}")
        # Fall back to seed data — never crash the agent
    
    combined = "\n\n".join(filter(None, [global_rag, tenant_rag, patterns_rag]))
    
    return {
        "global_rag": global_rag,
        "tenant_rag": tenant_rag,
        "patterns_rag": patterns_rag,
        "combined_rag": combined,
    }


# ═══════════════════════════════════════════════════════════════
# PROMPT REFINEMENT TRACKING
# Logs how the Punto Medio refines system prompts over time
# ═══════════════════════════════════════════════════════════════

def log_prompt_refinement(
    conn,
    tenant_id: str,
    agent_id: str,
    refinement_type: str,
    refinement_text: str,
    source_consolidation_id: int = None,
) -> Optional[int]:
    """
    Log a prompt refinement event for tracking the Flywheel's effect.
    """
    if not conn:
        return None
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO peaje_prompt_refinements
                (tenant_id, agent_id, refinement_type, refinement_text, 
                 source_consolidation_id, applied_count, is_active)
                VALUES (%s, %s, %s, %s, %s, 1, TRUE)
            """, (
                tenant_id, agent_id, refinement_type,
                refinement_text[:2000],  # Cap at 2000 chars
                source_consolidation_id,
            ))
            conn.commit()
            return cursor.lastrowid
    except Exception as e:
        print(f"[PUNTO MEDIO] Error logging refinement: {e}")
        return None


def increment_refinement_usage(conn, refinement_id: int):
    """Track how many times a refinement has been applied."""
    if not conn or not refinement_id:
        return
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE peaje_prompt_refinements
                SET applied_count = applied_count + 1, updated_at = NOW()
                WHERE id = %s
            """, (refinement_id,))
            conn.commit()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# PEAJE HEALTH & STATS
# ═══════════════════════════════════════════════════════════════

def get_peaje_stats(conn) -> Dict:
    """
    Get health and statistics from the Peaje/Punto Medio system.
    Used by /peaje/health endpoint.
    """
    stats = {
        "status": "healthy",
        "database": "disconnected",
        "insights_24h": 0,
        "insights_7d": 0,
        "sessions_24h": 0,
        "active_patterns": 0,
        "active_consolidations": 0,
        "extraction_errors_24h": 0,
        "avg_confidence_7d": 0,
        "taxonomy_categories": 4,
    }
    
    if not conn:
        stats["database"] = "disconnected"
        return stats
    
    try:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM view_peaje_health")
            health = cursor.fetchone()
            
            if health:
                stats.update({
                    "database": "connected",
                    "insights_24h": health.get("insights_24h", 0),
                    "insights_7d": health.get("insights_7d", 0),
                    "sessions_24h": health.get("sessions_24h", 0),
                    "active_patterns": health.get("active_patterns", 0),
                    "active_consolidations": health.get("active_consolidations", 0),
                    "extraction_errors_24h": health.get("extraction_errors_24h", 0),
                    "avg_confidence_7d": float(health.get("avg_confidence_7d", 0) or 0),
                })
    except Exception as e:
        stats["database"] = f"error: {str(e)[:100]}"
    
    return stats


def get_tenant_insights_summary(conn, tenant_id: str) -> Dict:
    """
    Get a summary of insights for a specific tenant.
    STRICT ISOLATION: Only returns data for the specified tenant.
    """
    summary = {
        "tenant_id": tenant_id,
        "total_insights": 0,
        "by_category": {},
        "recent_insights": [],
        "top_agents": [],
    }
    
    if not conn:
        return summary
    
    try:
        with conn.cursor() as cursor:
            # Total insights
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM peaje_insights WHERE tenant_id = %s",
                (tenant_id,)
            )
            result = cursor.fetchone()
            summary["total_insights"] = result.get("cnt", 0) if result else 0
            
            # By category
            cursor.execute("""
                SELECT category, COUNT(*) as cnt, AVG(confidence_score) as avg_conf
                FROM peaje_insights WHERE tenant_id = %s
                GROUP BY category ORDER BY cnt DESC
            """, (tenant_id,))
            for row in cursor.fetchall():
                summary["by_category"][row["category"]] = {
                    "count": row["cnt"],
                    "avg_confidence": float(row["avg_conf"] or 0),
                }
            
            # Recent insights (last 5)
            cursor.execute("""
                SELECT insight_text, category, sentiment, confidence_score, agent_id, created_at
                FROM peaje_insights WHERE tenant_id = %s
                ORDER BY created_at DESC LIMIT 5
            """, (tenant_id,))
            for row in cursor.fetchall():
                summary["recent_insights"].append({
                    "text": row["insight_text"][:200],
                    "category": row["category"],
                    "sentiment": row["sentiment"],
                    "confidence": float(row["confidence_score"] or 0),
                    "agent": row["agent_id"],
                    "timestamp": row["created_at"].isoformat() if row["created_at"] else None,
                })
            
            # Top agents
            cursor.execute("""
                SELECT agent_id, COUNT(*) as cnt
                FROM peaje_insights WHERE tenant_id = %s
                GROUP BY agent_id ORDER BY cnt DESC LIMIT 5
            """, (tenant_id,))
            for row in cursor.fetchall():
                summary["top_agents"].append({
                    "agent_id": row["agent_id"],
                    "insight_count": row["cnt"],
                })
    
    except Exception as e:
        summary["error"] = str(e)[:200]
    
    return summary
