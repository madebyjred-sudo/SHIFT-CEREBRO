#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
FLYWHEEL SIMULATOR v1.0 — Simula ejecutivos de Shift usando el Swarm
═══════════════════════════════════════════════════════════════
Generates realistic business conversations against the backend API,
triggering El Peaje ingestion to populate Punto Medio with real data.

Usage:
  python3 simulate_flywheel.py                  # Uses Railway production URL
  python3 simulate_flywheel.py --local           # Uses localhost:8000
  python3 simulate_flywheel.py --rounds 5        # Run 5 simulation rounds
"""

import os
import sys
import json
import time
import random
import asyncio
import hashlib
from datetime import datetime

try:
    import httpx
    HTTP_CLIENT = "httpx"
except ImportError:
    import urllib.request
    import ssl
    HTTP_CLIENT = "urllib"
    SSL_CONTEXT = ssl._create_unverified_context()

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

DEFAULT_API_URL = os.getenv("SWARM_API_URL", "https://web-production-143119.up.railway.app")
LOCAL_API_URL = "http://localhost:8000"

# Simulated Shift team members and their typical queries
SHIFT_PERSONAS = [
    {
        "name": "Juan (CEO)",
        "agent": "carmen",
        "queries": [
            "Necesito un análisis de nuestra posición competitiva en el mercado de IA generativa para LATAM. ¿Cuáles son los 3 principales riesgos ciegos que no estamos viendo?",
            "Estamos considerando expandir a Brasil. ¿Qué fricciones regulatorias y logísticas debería anticipar en los próximos 6 meses?",
            "¿Cuál es la estrategia óptima para posicionar Shifty como el estándar de IA corporativa en Centroamérica?",
        ],
    },
    {
        "name": "Dev Lead (Backend)",
        "agent": "susana",
        "queries": [
            "¿Cómo debería diseñar la arquitectura de microservicios para soportar 50 tenants simultáneos con aislamiento total de datos?",
            "Necesito optimizar las queries de consolidación del Punto Medio. Las GROUP BY con GROUP_CONCAT están lentas con 10K+ registros. ¿Alternativas?",
            "Dame un plan de migración de MySQL a PostgreSQL que no rompa la producción actual. Quiero aprovechar JSONB y full-text search nativo.",
        ],
    },
    {
        "name": "Growth Lead",
        "agent": "lucia",
        "queries": [
            "Nuestro funnel de conversión para clientes enterprise tiene un drop-off del 60% entre demo y cierre. ¿Qué tácticas de CRO recomiendas para B2B SaaS en LATAM?",
            "¿Cómo puedo estructurar un programa de referral para agencias de marketing que ya usan nuestra plataforma?",
            "Diseña una estrategia SEO para posicionar 'IA para empresas LATAM' como nuestra keyword principal en 90 días.",
        ],
    },
    {
        "name": "Product Manager",
        "agent": "diego",
        "queries": [
            "Necesito priorizar entre: (A) Dashboard analytics para tenants, (B) API pública de integración, (C) Marketplace de agentes custom. ¿Cómo aplicarías RICE?",
            "¿Cuál sería el roadmap ideal Now/Next/Later para el producto Shifty en los próximos 2 quarters?",
            "Tenemos reportes de que el debate arena se cae con más de 3 turnos. ¿Cómo diseñarías la feature flag para un rollout gradual?",
        ],
    },
    {
        "name": "Finance Lead",
        "agent": "roberto",
        "queries": [
            "Con un burn rate de $8K USD/mes y un runway de 18 meses, ¿cuál es la estrategia de pricing óptima para nuestro SaaS por tenant?",
            "Necesito modelar el unit economics de Shifty: CAC, LTV y payback period para el segmento enterprise LATAM.",
            "¿Cómo debería estructurar la propuesta financiera para una ronda seed de $500K enfocada en IA generativa B2B?",
        ],
    },
    {
        "name": "AI Engineer",
        "agent": "sofia",
        "queries": [
            "Estoy evaluando fine-tuning vs RAG vs prompt engineering para personalizar las respuestas de los agentes por tenant. ¿Cuál es el trade-off correcto para nuestro caso?",
            "¿Cómo puedo implementar un sistema de embeddings incrementales que se actualice cada vez que El Peaje procesa un nuevo insight?",
            "Diseña un pipeline de evaluación automatizada para medir la calidad de las respuestas del Swarm. Quiero métricas como relevancia, accionabilidad y coherencia.",
        ],
    },
]

# ═══════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════

def make_request(api_url: str, endpoint: str, payload: dict) -> dict:
    """Make HTTP POST request to the backend."""
    url = f"{api_url}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    
    if HTTP_CLIENT == "httpx":
        import httpx
        with httpx.Client(timeout=120.0, verify=False) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    else:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))


def make_get_request(api_url: str, endpoint: str) -> dict:
    """Make HTTP GET request."""
    url = f"{api_url}{endpoint}"
    if HTTP_CLIENT == "httpx":
        import httpx
        with httpx.Client(timeout=30.0, verify=False) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return resp.json()
    else:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode("utf-8"))


def simulate_conversation(api_url: str, persona: dict, query: str, round_num: int):
    """Simulate a single conversation from a team member → chat → ingest."""
    session_id = f"sim-{hashlib.md5(f'{persona["name"]}:{round_num}:{time.time()}'.encode()).hexdigest()[:12]}"
    
    print(f"\n  💬 {persona['name']} → Agent: {persona['agent']}")
    print(f"     Query: {query[:80]}...")
    
    # Step 1: Send chat to /swarm/chat
    chat_payload = {
        "messages": [{"role": "user", "content": query}],
        "preferred_agent": persona["agent"],
        "model": "Gemini 3.1 Flash Lite",  # Cost-effective for simulation
        "tenant_id": "shift",
        "session_id": session_id,
        "search_enabled": False,
        "attachments": [],
    }
    
    try:
        chat_result = make_request(api_url, "/swarm/chat", chat_payload)
        response_text = chat_result.get("content", "")[:200]
        agent_used = chat_result.get("agent_active", "unknown")
        print(f"     ✅ Response from {agent_used}: {response_text[:100]}...")
        
        # Step 2: Ingest into El Peaje
        ingest_payload = {
            "tenantId": "shift",
            "sessionId": session_id,
            "agentId": agent_used,
            "messages": [{"role": "user", "content": query}],
            "response": response_text,
        }
        
        ingest_result = make_request(api_url, "/peaje/ingest", ingest_payload)
        status = ingest_result.get("status", "unknown")
        category = ingest_result.get("category", "N/A")
        confidence = ingest_result.get("confidence_score", 0)
        print(f"     📊 Peaje: {status} | Category: {category} | Confidence: {confidence}")
        
        return {"success": True, "agent": agent_used, "category": category, "confidence": confidence}
        
    except Exception as e:
        print(f"     ❌ Error: {e}")
        return {"success": False, "error": str(e)}


def run_simulation(api_url: str, rounds: int = 3):
    """Run the full simulation."""
    print("═" * 70)
    print(f"  FLYWHEEL SIMULATOR v1.0 — Populating El Peaje")
    print(f"  Target: {api_url}")
    print(f"  Rounds: {rounds}")
    print(f"  Personas: {len(SHIFT_PERSONAS)}")
    print("═" * 70)
    
    # Health check
    try:
        health = make_get_request(api_url, "/health")
        print(f"\n  🏥 Backend Health: {health.get('status', 'unknown')} — {health.get('service', 'N/A')}")
    except Exception as e:
        print(f"\n  ❌ Backend unreachable: {e}")
        print(f"     Check that the server is running at {api_url}")
        return
    
    total_success = 0
    total_errors = 0
    categories_seen = {}
    
    for round_num in range(1, rounds + 1):
        print(f"\n{'─' * 50}")
        print(f"  ROUND {round_num}/{rounds}")
        print(f"{'─' * 50}")
        
        # Shuffle personas and pick random queries
        personas_this_round = random.sample(SHIFT_PERSONAS, min(len(SHIFT_PERSONAS), 3))
        
        for persona in personas_this_round:
            query = random.choice(persona["queries"])
            result = simulate_conversation(api_url, persona, query, round_num)
            
            if result["success"]:
                total_success += 1
                cat = result.get("category", "unknown")
                categories_seen[cat] = categories_seen.get(cat, 0) + 1
            else:
                total_errors += 1
            
            time.sleep(1)  # Be nice to the API
    
    # Summary
    print(f"\n{'═' * 70}")
    print(f"  SIMULATION COMPLETE")
    print(f"  ✅ Successful: {total_success}")
    print(f"  ❌ Errors: {total_errors}")
    print(f"  📊 Categories populated:")
    for cat, count in sorted(categories_seen.items(), key=lambda x: -x[1]):
        print(f"     • {cat}: {count} insights")
    print(f"{'═' * 70}")
    
    # Trigger consolidation
    print(f"\n  🔄 Triggering Punto Medio consolidation...")
    try:
        consolidation = make_request(api_url, "/punto-medio/consolidate", {})
        print(f"     ✅ Consolidation: {json.dumps(consolidation, indent=2, default=str)[:500]}")
    except Exception as e:
        print(f"     ⚠️  Consolidation trigger failed (may need POST): {e}")
    
    # Check pending reviews
    print(f"\n  📋 Checking pending reviews...")
    try:
        reviews = make_get_request(api_url, "/punto-medio/review")
        pending_c = reviews.get("pending_consolidations_count", 0)
        pending_p = reviews.get("pending_patterns_count", 0)
        print(f"     🔘 Pending consolidations: {pending_c}")
        print(f"     🔘 Pending patterns: {pending_p}")
        print(f"     → These are 'grey' — use /punto-medio/review/{{id}} to approve them!")
    except Exception as e:
        print(f"     ⚠️  Review check failed: {e}")


if __name__ == "__main__":
    use_local = "--local" in sys.argv
    api_url = LOCAL_API_URL if use_local else DEFAULT_API_URL
    
    rounds = 3
    for i, arg in enumerate(sys.argv):
        if arg == "--rounds" and i + 1 < len(sys.argv):
            rounds = int(sys.argv[i + 1])
    
    run_simulation(api_url, rounds)
