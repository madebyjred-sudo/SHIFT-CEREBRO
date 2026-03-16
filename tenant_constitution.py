ex"""
═══════════════════════════════════════════════════════════════
TENANT CONSTITUTION v2.0 — Contexto Corporativo Dinámico
Shift AI Gateway — De hardcodeo a escala Enterprise

Reemplaza TENANT_CONTEXTS hardcodeado en main.py
Soporta jerarquía: Holding → Division → Business Unit
Token budget: ~800 tokens compilados
═══════════════════════════════════════════════════════════════
"""

import json
import re
from typing import Dict, List, Optional, Any
from datetime import datetime


# ═══════════════════════════════════════════════════════════════
# FALLBACK: Seed data para tenants sin configuración en DB
# Mismo formato que TENANT_CONTEXTS original pero estructurado
# ═══════════════════════════════════════════════════════════════

SEED_TENANT_CONTEXTS = {
    "shift": {
        "mission": "Democratizar el acceso a consultoría estratégica de clase mundial para empresas LATAM mediante Inteligencia Artificial.",
        "vision": "Ser el sistema operativo de la toma de decisiones empresariales en América Latina para 2030.",
        "values": [
            {"name": "Velocidad", "desc": "Decisiones en horas, no semanas"},
            {"name": "Rigor Técnico", "desc": "Datos antes que opiniones"},
            {"name": "Diseño Impecable", "desc": "La forma es función"}
        ],
        "industry": "tech_saas",
        "tone_voice": "Bold-Disruptivo",
        "brand_archetype": "The Explorer",
        "negative_constraints": ["modelo de lenguaje", "como agente", "swarm", "AI dice", "no puedo"],
        "internal_jargon": {
            "Punto Medio": "Memoria institucional materializada",
            "El Peaje": "Sistema de extracción de insights",
            "Shift Way": "Metodología de respuesta"
        }
    },
    "garnier": {
        "mission": "Transformar la comunicación corporativa en LATAM combinando creatividad estratégica con ejecución impecable.",
        "vision": "Ser la red de agencias de comunicación más influyente y premiada de Iberoamérica.",
        "values": [
            {"name": "Excelencia", "desc": "Solo entregamos lo que nos enorgullece"},
            {"name": "Cercanía", "desc": "Entendemos el negocio del cliente mejor que él"}
        ],
        "industry": "media_comunicacion",
        "tone_voice": "Creativo-Estratégico",
        "brand_archetype": "The Creator",
        "negative_constraints": ["barato", "descuento", "solo agencia"],
        "internal_jargon": {
            "Big Idea": "Concepto central de campaña",
            "Pitch": "Presentación a cliente para ganar cuenta"
        }
    }
}


# ═══════════════════════════════════════════════════════════════
# TOKEN MANAGEMENT
# ═══════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """Estimación conservadora: ~4 chars por token promedio en español/inglés"""
    if not text:
        return 0
    return len(text) // 4 + 1


def truncate_text(text: str, max_tokens: int) -> str:
    """Trunca texto manteniendo oraciones completas"""
    if estimate_tokens(text) <= max_tokens:
        return text
    
    max_chars = max_tokens * 4
    truncated = text[:max_chars]
    
    # Buscar último punto o salto de línea para cortar limpio
    last_break = max(trunced.rfind('.'), truncated.rfind('\n'), truncated.rfind(';'))
    if last_break > max_chars * 0.7:  # Solo si encontramos break razonable
        return truncated[:last_break + 1] + "\n[...]"
    
    return truncated + " [...]"


# ═══════════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def compile_tenant_context(conn, tenant_id: str) -> str:
    """
    Compila la Constitución del Tenant desde DB aplicando herencia jerárquica.
    
    Args:
        conn: Conexión MySQL (pymysql)
        tenant_id: ID del tenant (ej: 'shift', 'garnier')
    
    Returns:
        Markdown estructurado listo para inyección en system prompt (~800 tokens)
    """
    if not conn:
        return _get_seed_context(tenant_id)
    
    try:
        with conn.cursor() as cursor:
            # 1. Recuperar tenant principal
            cursor.execute("""
                SELECT * FROM tenant_constitutions 
                WHERE tenant_id = %s AND is_active = TRUE
            """, (tenant_id,))
            
            tenant_row = cursor.fetchone()
            if not tenant_row:
                return _get_seed_context(tenant_id)
            
            # 2. Si tiene parent, recuperar para herencia
            parent_row = None
            parent_id = tenant_row.get('parent_id')
            if parent_id:
                cursor.execute("""
                    SELECT * FROM tenant_constitutions 
                    WHERE tenant_id = %s AND is_active = TRUE
                """, (parent_id,))
                parent_row = cursor.fetchone()
            
            # 3. Construir contexto mergeado
            context = _build_merged_context(tenant_row, parent_row)
            
            # 4. Compilar a Markdown
            markdown = _compile_to_markdown(context, tenant_row, parent_row)
            
            # 5. Token budget check
            if estimate_tokens(markdown) > 900:
                markdown = _prune_to_budget(markdown, max_tokens=800)
            
            return markdown
            
    except Exception as e:
        print(f"[TenantContext] Error compiling for {tenant_id}: {e}")
        return _get_seed_context(tenant_id)


def get_tenant_context_with_fallback(conn, tenant_id: str) -> str:
    """
    Wrapper con fallback: DB → Seed → Genérico.
    Nunca retorna vacío.
    """
    if conn:
        try:
            context = compile_tenant_context(conn, tenant_id)
            if context and len(context) > 100:
                return context
        except Exception:
            pass
    
    return _get_seed_context(tenant_id)


def upsert_tenant_constitution(conn, data: Dict[str, Any]) -> bool:
    """
    Inserta o actualiza una constitución de tenant.
    
    Args:
        conn: Conexión MySQL
        data: Dict con campos de tenant_constitutions
    
    Returns:
        True si exitoso, False si error
    """
    if not conn:
        return False
    
    required = ['tenant_id', 'tenant_name', 'slug']
    for field in required:
        if field not in data or not data[field]:
            print(f"[TenantContext] Campo requerido faltante: {field}")
            return False
    
    try:
        with conn.cursor() as cursor:
            # Verificar si existe
            cursor.execute(
                "SELECT id, version FROM tenant_constitutions WHERE tenant_id = %s",
                (data['tenant_id'],)
            )
            existing = cursor.fetchone()
            
            if existing:
                # Update: incrementar versión y guardar historia
                new_version = existing['version'] + 1
                data['version'] = new_version
                data['updated_at'] = datetime.now()
                
                # Guardar historia antes de actualizar
                _save_history(cursor, existing['id'], data['tenant_id'], 
                             existing['version'], data)
                
                # Construir UPDATE dinámico
                update_fields = []
                update_values = []
                for key, value in data.items():
                    if key not in ['tenant_id', 'id', 'created_at']:
                        update_fields.append(f"{key} = %s")
                        # JSON fields handling
                        if key.endswith('_json') and isinstance(value, (list, dict)):
                            value = json.dumps(value, ensure_ascii=False)
                        update_values.append(value)
                
                update_values.append(data['tenant_id'])
                sql = f"UPDATE tenant_constitutions SET {', '.join(update_fields)} WHERE tenant_id = %s"
                cursor.execute(sql, update_values)
                
            else:
                # Insert nuevo
                data['version'] = 1
                data['created_at'] = datetime.now()
                data['updated_at'] = datetime.now()
                
                # Preparar columnas y valores
                columns = []
                values = []
                for key, value in data.items():
                    if value is not None:
                        columns.append(key)
                        # JSON fields handling
                        if key.endswith('_json') and isinstance(value, (list, dict)):
                            value = json.dumps(value, ensure_ascii=False)
                        values.append(value)
                
                placeholders = ', '.join(['%s'] * len(columns))
                sql = f"INSERT INTO tenant_constitutions ({', '.join(columns)}) VALUES ({placeholders})"
                cursor.execute(sql, values)
            
            conn.commit()
            return True
            
    except Exception as e:
        print(f"[TenantContext] Error en upsert: {e}")
        try:
            conn.rollback()
        except:
            pass
        return False


def _save_history(cursor, constitution_id: int, tenant_id: str, old_version: int, new_data: dict):
    """Guarda snapshot de versión anterior en tabla de historia"""
    try:
        # Determinar qué campos cambiaron
        changed_fields = []
        previous_values = {}
        
        # Esto es simplificado - en producción haríamos SELECT previo completo
        # Por ahora, registramos que hubo un cambio de versión
        
        cursor.execute("""
            INSERT INTO tenant_constitution_history 
            (tenant_id, version, changed_fields, previous_values, changed_by, change_reason)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (
            tenant_id,
            old_version,
            json.dumps(["version_update"]),
            json.dumps({"version": old_version}),
            new_data.get('updated_by', 'system'),
            new_data.get('change_reason', 'Version update')
        ))
    except Exception as e:
        print(f"[TenantContext] Error guardando historia: {e}")
        # No fallamos el update principal por error en historia


# ═══════════════════════════════════════════════════════════════
# HELPERS INTERNOS
# ═══════════════════════════════════════════════════════════════

def _get_seed_context(tenant_id: str) -> str:
    """Fallback a seed data hardcodeado si DB falla"""
    seed = SEED_TENANT_CONTEXTS.get(tenant_id, SEED_TENANT_CONTEXTS.get('shift'))
    
    if not seed:
        return "[CONTEXTO CORPORATIVO NO CONFIGURADO]"
    
    # Compilar seed a markdown simple
    lines = [
        f"# CONSTITUCIÓN CORPORATIVA: {tenant_id.upper()}",
        "",
        "## 1. IDENTIDAD Y PROPÓSITO",
        f"**Misión:** {seed.get('mission', '')}",
        f"**Visión:** {seed.get('vision', '')}",
        "",
        "## 2. VALORES FUNDAMENTALES",
    ]
    
    for value in seed.get('values', []):
        lines.append(f"- **{value.get('name')}**: {value.get('desc')}")
    
    lines.extend([
        "",
        "## 3. VOZ Y RESTRICCIONES",
        f"**Tono:** {seed.get('tone_voice', 'Profesional')}",
        f"**Archetype:** {seed.get('brand_archetype', 'Professional')}",
    ])
    
    if seed.get('negative_constraints'):
        lines.append(f"**Prohibido mencionar:** {', '.join(seed['negative_constraints'][:5])}")
    
    return "\n".join(lines)


def _build_merged_context(tenant_row: dict, parent_row: Optional[dict]) -> dict:
    """Mergea campos de tenant hijo con herencia del padre"""
    
    def safe_json_loads(value):
        if isinstance(value, str):
            try:
                return json.loads(value)
            except:
                return []
        return value or []
    
    context = {}
    
    # Campos que se heredan si el hijo no los tiene
    inheritable_fields = [
        'mission', 'vision', 'values_json', 'industry', 'sub_industry',
        'tone_voice', 'brand_archetype', 'negative_constraints',
        'internal_jargon', 'region_focus', 'local_nuances'
    ]
    
    # Campos específicos del hijo (no heredables)
    own_fields = [
        'target_market', 'core_challenges', 'competitive_landscape',
        'strategic_priorities', 'kpis_focus'
    ]
    
    # Primero: valores del padre como base
    if parent_row:
        for field in inheritable_fields:
            value = parent_row.get(field)
            if field.endswith('_json') and isinstance(value, str):
                value = safe_json_loads(value)
            context[field] = value
    
    # Segundo: override con valores del hijo
    for field in inheritable_fields + own_fields:
        value = tenant_row.get(field)
        if value:  # Solo si no es None o vacío
            if field.endswith('_json') and isinstance(value, str):
                value = safe_json_loads(value)
            context[field] = value
    
    # Metadatos
    context['tenant_name'] = tenant_row.get('tenant_name', tenant_row.get('tenant_id'))
    context['division_type'] = tenant_row.get('division_type', 'tenant')
    if parent_row:
        context['parent_name'] = parent_row.get('tenant_name')
    
    return context


def _compile_to_markdown(context: dict, tenant_row: dict, parent_row: Optional[dict]) -> str:
    """Compila el contexto mergeado a formato Markdown jerárquico"""
    
    tenant_id = tenant_row.get('tenant_id', 'UNKNOWN')
    tenant_name = context.get('tenant_name', tenant_id)
    
    lines = [
        f"# CONSTITUCIÓN CORPORATIVA: {tenant_name.upper()}",
    ]
    
    # Si es división/hijo, indicar herencia
    if parent_row and context.get('parent_name'):
        lines.append(f"**División de:** {context['parent_name']} | **Tipo:** {context.get('division_type', 'N/A')}")
    
    lines.extend([
        "",
        "## 1. IDENTIDAD Y PROPÓSITO",
    ])
    
    if context.get('mission'):
        lines.append(f"**Misión:** {context['mission']}")
    if context.get('vision'):
        lines.append(f"**Visión:** {context['vision']}")
    
    # Valores
    values = context.get('values_json', [])
    if values:
        lines.extend(["", "**Valores Fundamentales:**"])
        for value in values[:5]:  # Max 5 valores
            if isinstance(value, dict):
                lines.append(f"- **{value.get('name')}**: {value.get('desc', '')}")
    
    # Contexto de negocio
    lines.extend([
        "",
        "## 2. CONTEXTO DE NEGOCIO",
    ])
    
    if context.get('industry'):
        lines.append(f"**Industria:** {context['industry']}")
    if context.get('target_market'):
        lines.append(f"**Mercado Objetivo:** {context['target_market']}")
    if context.get('core_challenges'):
        lines.append(f"**Desafíos Core:** {context['core_challenges']}")
    
    # Voz y personalidad
    lines.extend([
        "",
        "## 3. VOZ Y PERSONALIDAD",
    ])
    
    if context.get('tone_voice'):
        lines.append(f"**Tono:** {context['tone_voice']}")
    if context.get('brand_archetype'):
        lines.append(f"**Arquetipo:** {context['brand_archetype']}")
    
    # Restricciones
    constraints = context.get('negative_constraints', [])
    if constraints:
        lines.append(f"**Prohibido mencionar:** {', '.join(constraints[:8])}")
    
    # Jargon interno
    jargon = context.get('internal_jargon', {})
    if jargon:
        lines.extend(["", "**Glosario Interno:**"])
        for term, definition in list(jargon.items())[:10]:  # Max 10 términos
            lines.append(f"- *{term}*: {definition}")
    
    # Footer
    lines.extend([
        "",
        "---",
        f"*Constitución Corporativa v{tenant_row.get('version', 1)} | Actualizada: {tenant_row.get('updated_at', 'N/A')}*"
    ])
    
    return "\n".join(lines)


def _prune_to_budget(markdown: str, max_tokens: int = 800) -> str:
    """Reduce contenido si excede token budget"""
    
    current_tokens = estimate_tokens(markdown)
    if current_tokens <= max_tokens:
        return markdown
    
    lines = markdown.split('\n')
    
    # Estrategia de pruning por prioridad
    # 1. Quitar secciones menos críticas primero
    sections_to_prune = [
        "**Glosario Interno:**",
        "## 2. CONTEXTO DE NEGOCIO",
        "**Desafíos Core:**",
        "**Mercado Objetivo:**",
    ]
    
    pruned_lines = []
    skip_until_header = None
    
    for line in lines:
        # Si estamos en modo skip, buscar próximo header para salir
        if skip_until_header:
            if line.startswith('#') and not line.startswith('##'):
                skip_until_header = None
            else:
                continue
        
        # Verificar si esta línea inicia una sección a podar
        for prune_marker in sections_to_prune:
            if prune_marker in line:
                # Marcar para skip hasta siguiente sección principal
                skip_until_header = True
                pruned_lines.append(f"\n[... {prune_marker.replace('**', '').replace(':', '')} truncado por token budget ...]\n")
                break
        else:
            pruned_lines.append(line)
    
    result = '\n'.join(pruned_lines)
    
    # Si aún excede, truncar brutalmente al final
    if estimate_tokens(result) > max_tokens:
        max_chars = max_tokens * 4
        result = result[:max_chars] + "\n\n[... Truncado por límite de tokens ...]"
    
    return result


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _get_seed_context(tenant_id: str) -> str:
    """Fallback a seed data si DB no disponible"""
    seed_data = SEED_TENANT_CONTEXTS.get(tenant_id)
    
    if not seed_data:
        # Contexto genérico mínimo
        return """# CONSTITUCIÓN CORPORATIVA

## 1. IDENTIDAD
Consultor estratégico para mercados latinoamericanos.

## 2. PRINCIPIOS DE RESPUESTA
- Accionabilidad inmediata
- Rigor técnico
- Veracidad radical
"""
    
    # Compilar seed a markdown mínimo
    lines = [
        f"# CONSTITUCIÓN CORPORATIVA: {tenant_id.upper()}",
        "",
        "## 1. IDENTIDAD Y PROPÓSITO",
        f"**Misión:** {seed_data.get('mission', '')}",
    ]
    
    if seed_data.get('values'):
        lines.append("**Valores:** " + ", ".join([v.get('name', '') for v in seed_data['values'][:3]]))
    
    lines.extend([
        "",
        "## 2. VOZ Y PERSONALIDAD",
        f"**Tono:** {seed_data.get('tone_voice', 'Profesional')}",
    ])
    
    if seed_data.get('negative_constraints'):
        lines.append(f"**Prohibido:** {', '.join(seed_data['negative_constraints'][:5])}")
    
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════

__all__ = [
    'compile_tenant_context',
    'get_tenant_context_with_fallback', 
    'upsert_tenant_constitution',
    'SEED_TENANT_CONTEXTS',
    'estimate_tokens',
]
