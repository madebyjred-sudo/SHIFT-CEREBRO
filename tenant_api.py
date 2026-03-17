"""
═══════════════════════════════════════════════════════════════
TENANT CONSTITUTION API v2.0 — Endpoints FastAPI
Shift AI Gateway — CRUD para Constitución Corporativa
═══════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from tenant_constitution import (
    compile_tenant_context,
    get_tenant_context_with_fallback,
    upsert_tenant_constitution,
)


# ═══════════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════════

router = APIRouter(prefix="/tenant", tags=["tenant-constitution"])


# ═══════════════════════════════════════════════════════════════
# PYDANTIC MODELS
# ═══════════════════════════════════════════════════════════════

class ConstitutionCreate(BaseModel):
    tenant_id: str = Field(..., min_length=2, max_length=50, description="ID único del tenant")
    tenant_name: str = Field(..., min_length=2, max_length=100)
    slug: str = Field(..., min_length=2, max_length=100, description="URL-friendly identifier")
    
    # Jerarquía
    parent_id: Optional[str] = Field(None, description="tenant_id del padre (para divisions)")
    division_type: Optional[str] = Field(None, description="holding | subsidiary | division | business_unit | brand")
    
    # Identidad
    mission: Optional[str] = Field(None, description="Misión corporativa")
    vision: Optional[str] = Field(None, description="Visión a 3-5 años")
    values_json: Optional[List[Dict[str, str]]] = Field(None, description="Valores: [{name, desc}]")
    
    # Negocio
    industry: Optional[str] = Field(None, description="Vertical principal")
    sub_industry: Optional[str] = Field(None, description="Sub-vertical")
    target_market: Optional[str] = Field(None, description="ICP - Cliente ideal")
    core_challenges: Optional[str] = Field(None, description="Top desafíos")
    competitive_landscape: Optional[str] = Field(None, description="Competidores y diferenciación")
    
    # Voz
    tone_voice: Optional[str] = Field(None, description="Formal-Ejecutivo | Bold-Disruptivo | Empático-Experto")
    brand_archetype: Optional[str] = Field(None, description="The Sage, The Explorer, etc")
    negative_constraints: Optional[List[str]] = Field(None, description="Palabras prohibidas")
    communication_do: Optional[List[str]] = Field(None, description="Qué SÍ hacer")
    
    # Operativo
    kpis_focus: Optional[List[Dict[str, str]]] = Field(None, description="KPIs: [{name, why}]")
    internal_jargon: Optional[Dict[str, str]] = Field(None, description="Términos: {term: definition}")
    strategic_priorities: Optional[str] = Field(None, description="Prioridades año fiscal")
    
    # Regional
    region_focus: Optional[str] = Field(None, description="LATAM, Andino, ConoSur, etc")
    local_nuances: Optional[str] = Field(None, description="Matices culturales locales")
    
    # Metadata
    created_by: Optional[str] = Field(None, description="Email del C-Level que completó onboarding")


class ConstitutionUpdate(BaseModel):
    """Para updates parciales - todos los campos son opcionales"""
    tenant_name: Optional[str] = None
    mission: Optional[str] = None
    vision: Optional[str] = None
    values_json: Optional[List[Dict[str, str]]] = None
    industry: Optional[str] = None
    target_market: Optional[str] = None
    core_challenges: Optional[str] = None
    tone_voice: Optional[str] = None
    brand_archetype: Optional[str] = None
    negative_constraints: Optional[List[str]] = None
    kpis_focus: Optional[List[Dict[str, str]]] = None
    internal_jargon: Optional[Dict[str, str]] = None
    strategic_priorities: Optional[str] = None
    region_focus: Optional[str] = None
    local_nuances: Optional[str] = None
    is_active: Optional[bool] = None
    change_reason: Optional[str] = Field(None, description="Motivo del cambio (para audit)")


class CloneRequest(BaseModel):
    new_tenant_id: str = Field(..., min_length=2, max_length=50)
    new_name: str = Field(..., min_length=2, max_length=100)
    division_type: str = Field(..., description="division | business_unit | brand")
    slug: Optional[str] = None  # Si no se provee, se genera de new_tenant_id


class ConstitutionResponse(BaseModel):
    tenant_id: str
    tenant_name: str
    version: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ═══════════════════════════════════════════════════════════════
# DEPENDENCY: Database Connection
# ═══════════════════════════════════════════════════════════════

def get_db_connection():
    """Factory para obtener conexión DB - importa desde main.py"""
    # Este import se resuelve en runtime cuando main.py ya cargó
    try:
        from main import get_db_connection as main_db_conn
        return main_db_conn()
    except ImportError:
        # Fallback para testing
        return None


# ═══════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@router.get("/constitution/{tenant_id}", response_model=Dict[str, Any])
async def get_constitution(tenant_id: str, raw: bool = False):
    """
    Obtiene la Constitución Corporativa compilada de un tenant.
    
    Args:
        tenant_id: ID del tenant
        raw: Si True, retorna el registro DB completo. Si False, retorna Markdown compilado.
    """
    conn = get_db_connection()
    
    if raw:
        # Retornar datos crudos de DB
        if not conn:
            raise HTTPException(status_code=503, detail="Database unavailable")
        
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM tenant_constitutions WHERE tenant_id = %s",
                    (tenant_id,)
                )
                row = cursor.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
                
                # Convertir JSON strings a objetos Python
                for key in ['values_json', 'kpis_focus', 'internal_jargon', 
                           'negative_constraints', 'communication_do']:
                    if row.get(key) and isinstance(row[key], str):
                        try:
                            row[key] = json.loads(row[key])
                        except:
                            pass
                
                return {
                    "status": "success",
                    "data": row,
                    "source": "database"
                }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    
    # Retornar Markdown compilado (default)
    markdown = get_tenant_context_with_fallback(conn, tenant_id)
    
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "compiled_context": markdown,
        "token_estimate": len(markdown) // 4,
        "source": "database" if conn else "seed_fallback"
    }


@router.post("/constitution", response_model=Dict[str, Any])
async def create_constitution(data: ConstitutionCreate):
    """
    Crea una nueva Constitución Corporativa.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    # Verificar si ya existe
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT tenant_id FROM tenant_constitutions WHERE tenant_id = %s",
                (data.tenant_id,)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=409, 
                    detail=f"Tenant {data.tenant_id} already exists. Use PUT to update."
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    # Convertir a dict para upsert
    data_dict = data.model_dump(exclude_none=True)
    data_dict['version'] = 1
    
    success = upsert_tenant_constitution(conn, data_dict)
    
    if success:
        # Retornar la constitución compilada
        compiled = compile_tenant_context(conn, data.tenant_id)
        return {
            "status": "created",
            "tenant_id": data.tenant_id,
            "tenant_name": data.tenant_name,
            "version": 1,
            "compiled_preview": compiled[:500] + "..." if len(compiled) > 500 else compiled,
            "token_estimate": len(compiled) // 4
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to create constitution")


@router.put("/constitution/{tenant_id}", response_model=Dict[str, Any])
async def update_constitution(tenant_id: str, data: ConstitutionUpdate):
    """
    Actualiza una Constitución Corporativa existente.
    Incrementa versión automáticamente y guarda historia.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    # Verificar que existe
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT id, version FROM tenant_constitutions WHERE tenant_id = %s",
                (tenant_id,)
            )
            existing = cursor.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail=f"Tenant {tenant_id} not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    # Preparar datos de update
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    update_data['tenant_id'] = tenant_id
    update_data['updated_by'] = data.change_reason or 'api_update'
    
    success = upsert_tenant_constitution(conn, update_data)
    
    if success:
        # Obtener nueva versión
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT version FROM tenant_constitutions WHERE tenant_id = %s",
                    (tenant_id,)
                )
                new_version = cursor.fetchone()['version']
        except:
            new_version = "unknown"
        
        compiled = compile_tenant_context(conn, tenant_id)
        return {
            "status": "updated",
            "tenant_id": tenant_id,
            "new_version": new_version,
            "changes": list(update_data.keys()),
            "compiled_preview": compiled[:500] + "..." if len(compiled) > 500 else compiled,
            "token_estimate": len(compiled) // 4
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to update constitution")


@router.get("/lineage/{tenant_id}", response_model=Dict[str, Any])
async def get_lineage(tenant_id: str):
    """
    Obtiene la línea de herencia de un tenant (para multinacionales con divisions).
    Muestra: Parent → Grandparent → etc.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    lineage = []
    current_id = tenant_id
    visited = set()  # Prevenir ciclos infinitos
    
    try:
        with conn.cursor() as cursor:
            while current_id and current_id not in visited:
                visited.add(current_id)
                
                cursor.execute(
                    """SELECT tenant_id, tenant_name, parent_id, division_type, 
                              hierarchy_path, version, is_active
                       FROM tenant_constitutions WHERE tenant_id = %s""",
                    (current_id,)
                )
                row = cursor.fetchone()
                
                if not row:
                    break
                
                lineage.append({
                    "tenant_id": row['tenant_id'],
                    "tenant_name": row['tenant_name'],
                    "division_type": row['division_type'],
                    "hierarchy_path": row['hierarchy_path'],
                    "version": row['version'],
                    "is_active": row['is_active']
                })
                
                current_id = row['parent_id']
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    return {
        "status": "success",
        "tenant_id": tenant_id,
        "lineage_depth": len(lineage),
        "lineage": lineage,  # Orden: [self, parent, grandparent, ...]
        "root_tenant": lineage[-1]['tenant_name'] if lineage else None
    }


@router.post("/constitution/{tenant_id}/clone", response_model=Dict[str, Any])
async def clone_constitution(tenant_id: str, request: CloneRequest):
    """
    Clona una constitución existente para crear una división/hija.
    Útil para multinacionales: crear Garnier-Media a partir de Garnier.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    # Verificar que source existe y target no existe
    try:
        with conn.cursor() as cursor:
            # Source
            cursor.execute(
                "SELECT * FROM tenant_constitutions WHERE tenant_id = %s AND is_active = TRUE",
                (tenant_id,)
            )
            source = cursor.fetchone()
            if not source:
                raise HTTPException(status_code=404, detail=f"Source tenant {tenant_id} not found")
            
            # Target
            cursor.execute(
                "SELECT tenant_id FROM tenant_constitutions WHERE tenant_id = %s",
                (request.new_tenant_id,)
            )
            if cursor.fetchone():
                raise HTTPException(
                    status_code=409,
                    detail=f"Target tenant {request.new_tenant_id} already exists"
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    
    # Preparar datos del clone
    clone_data = dict(source)
    
    # Override con nuevos valores
    clone_data['tenant_id'] = request.new_tenant_id
    clone_data['tenant_name'] = request.new_name
    clone_data['slug'] = request.slug or request.new_tenant_id.replace('_', '-')
    clone_data['parent_id'] = tenant_id
    clone_data['division_type'] = request.division_type
    clone_data['version'] = 1
    clone_data['created_at'] = datetime.now()
    clone_data['updated_at'] = datetime.now()
    clone_data['created_by'] = f"cloned_from:{tenant_id}"
    
    # Limpiar campos que no deben heredarse
    clone_data.pop('id', None)
    clone_data.pop('hierarchy_path', None)  # Se recalculará
    
    # Calcular hierarchy_path
    parent_path = source.get('hierarchy_path') or tenant_id
    clone_data['hierarchy_path'] = f"{parent_path}/{request.new_tenant_id}"
    
    success = upsert_tenant_constitution(conn, clone_data)
    
    if success:
        compiled = compile_tenant_context(conn, request.new_tenant_id)
        return {
            "status": "cloned",
            "source_tenant": tenant_id,
            "new_tenant_id": request.new_tenant_id,
            "new_name": request.new_name,
            "division_type": request.division_type,
            "hierarchy_path": clone_data['hierarchy_path'],
            "inherited_from": source['tenant_name'],
            "compiled_preview": compiled[:500] + "..." if len(compiled) > 500 else compiled,
            "token_estimate": len(compiled) // 4
        }
    else:
        raise HTTPException(status_code=500, detail="Failed to clone constitution")


@router.get("/constitutions/list", response_model=Dict[str, Any])
async def list_constitutions(
    industry: Optional[str] = None,
    division_type: Optional[str] = None,
    is_active: Optional[bool] = True,
    limit: int = 50
):
    """
    Lista todas las constituciones con filtros opcionales.
    """
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        with conn.cursor() as cursor:
            # Construir query dinámica
            conditions = ["1=1"]
            params = []
            
            if is_active is not None:
                conditions.append("is_active = %s")
                params.append(is_active)
            
            if industry:
                conditions.append("industry = %s")
                params.append(industry)
            
            if division_type:
                conditions.append("division_type = %s")
                params.append(division_type)
            
            sql = f"""
                SELECT tenant_id, tenant_name, slug, parent_id, division_type,
                       industry, tone_voice, version, is_active, created_at
                FROM tenant_constitutions
                WHERE {' AND '.join(conditions)}
                ORDER BY tenant_name
                LIMIT %s
            """
            params.append(limit)
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            return {
                "status": "success",
                "count": len(rows),
                "filters": {
                    "industry": industry,
                    "division_type": division_type,
                    "is_active": is_active
                },
                "constitutions": rows
            }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


# ═══════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════

__all__ = ['router']