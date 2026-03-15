#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
TENANT CONSTITUTION MIGRATION — Ejecuta el schema v2.0
═══════════════════════════════════════════════════════════════
"""

import os
import sys
import pymysql
from dotenv import load_dotenv

load_dotenv()

def get_connection():
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST"),
        user=os.getenv("MYSQL_USER"),
        password=os.getenv("MYSQL_PASSWORD"),
        database=os.getenv("MYSQL_DATABASE"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor
    )

def main():
    print("=== TENANT CONSTITUTION SCHEMA MIGRATION ===")
    
    # Leer el archivo SQL
    sql_path = os.path.join(os.path.dirname(__file__), "tenant_context_schema.sql")
    with open(sql_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()
    
    # Separar sentencias SQL (simplificación)
    statements = sql_content.split(';')
    
    conn = None
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        for i, stmt in enumerate(statements):
            stmt = stmt.strip()
            if not stmt:
                continue
            if stmt.startswith('--') or stmt.startswith('/*'):
                continue
            try:
                print(f"[{i+1}] Executing...")
                cursor.execute(stmt)
                print(f"    ✓ OK")
            except pymysql.err.OperationalError as e:
                # Ignorar errores de tabla ya existe
                if e.args[0] == 1050:
                    print(f"    ⚠ Table already exists (OK)")
                else:
                    print(f"    ✗ Error: {e}")
                    raise
            except Exception as e:
                print(f"    ✗ Error: {e}")
                raise
        
        conn.commit()
        
        # Verificar creación
        cursor.execute("SHOW TABLES LIKE 'tenant_constitutions'")
        if cursor.fetchone():
            print("\n✅ Tabla 'tenant_constitutions' creada correctamente")
        else:
            print("\n❌ Tabla 'tenant_constitutions' NO creada")
            
        cursor.execute("SHOW TABLES LIKE 'tenant_constitution_history'")
        if cursor.fetchone():
            print("✅ Tabla 'tenant_constitution_history' creada correctamente")
        else:
            print("❌ Tabla 'tenant_constitution_history' NO creada")
            
        # Insertar datos seed si no existen
        cursor.execute("SELECT COUNT(*) as cnt FROM tenant_constitutions")
        count = cursor.fetchone()['cnt']
        if count == 0:
            print("\n🔧 Insertando datos seed...")
            seed_sql = """
                INSERT INTO tenant_constitutions 
                (tenant_id, tenant_name, slug, mission, vision, values_json, 
                 industry, tone_voice, brand_archetype, created_by)
                VALUES 
                ('shift', 'Shift AI Lab', 'shift-ai-lab', 
                 'Consultora de innovación y estrategia digital con IA Generativa aplicada a procesos corporativos B2B.',
                 'Ser el socio estratégico preferido de empresas LATAM para transformación digital acelerada.',
                 '[{"name": "Velocidad", "desc": "Acción táctica sobre planeación interminable"}, {"name": "Rigor Técnico", "desc": "Soluciones basadas en estándares de industria verificables"}, {"name": "Diseño Impecable", "desc": "Experiencias y arquitecturas elegantes, simples y funcionales"}]',
                 'tech_saas', 'Bold-Disruptivo', 'The Sage', 'system'),
                
                ('garnier', 'Grupo Garnier', 'grupo-garnier',
                 'Red de agencias de comunicación y marketing líder en LatAm, especializada en consumo masivo, retail corporativo y servicios financieros.',
                 'Consolidar la hegemonía en comunicación estratégica en LATAM mediante automatización profunda de insights creativos y eficiencia transaccional en media planning.',
                 '[{"name": "Estrategia Asertiva", "desc": "Posturas claras con respaldo C-Level"}, {"name": "Innovación con Respaldo", "desc": "Disrupción basada en datos, no intuición"}, {"name": "Ejecución Transaccional", "desc": "Resultados medibles en tiempo real"}]',
                 'media_comunicacion', 'Estratégico-Asertivo', 'The Explorer', 'system')
            """
            try:
                cursor.execute(seed_sql)
                conn.commit()
                print("✅ Datos seed insertados")
            except Exception as e:
                print(f"⚠ Error insertando seed (puede ya existir): {e}")
                conn.rollback()
        else:
            print(f"\n📊 Ya existen {count} registros en tenant_constitutions")
        
        print("\n✅ MIGRACIÓN COMPLETADA EXITOSAMENTE")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        sys.exit(1)
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    main()