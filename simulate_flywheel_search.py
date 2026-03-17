#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════
FLYWHEEL SIMULATOR v2.0 — SEARCH ENABLED 🔍
═══════════════════════════════════════════════════════════════════
Simula ejecutivos de Shift usando el Swarm con BÚSQUEDA WEB ACTIVADA.
Todas las queries requieren datos en tiempo real de internet.

Usage:
  python3 simulate_flywheel_search.py                  # Production (search ON)
  python3 simulate_flywheel_search.py --local          # Localhost
  python3 simulate_flywheel_search.py --rounds 3       # 3 rounds
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

# ═══════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════

DEFAULT_API_URL = os.getenv("SWARM_API_URL", "https://web-production-143119.up.railway.app")
LOCAL_API_URL = "http://localhost:8000"

# ═══════════════════════════════════════════════════════════════════
# QUERIES CON DATOS EN TIEMPO REAL (requieren búsqueda web)
# ═══════════════════════════════════════════════════════════════════

SHIFT_PERSONAS_SEARCH = [
    {
        "name": "Juan (CEO)",
        "agent": "carmen",
        "queries": [
            "¿Cuáles son las últimas noticias de regulación de inteligencia artificial en Latinoamérica en marzo 2026? ¿Qué países ya tienen leyes aprobadas?",
            "Busca las rondas de inversión más recientes en startups de IA B2B en Centroamérica y México durante Q1 2026. ¿Cuánto capital se ha movido?",
            "¿Qué competidores de Shifty Studio han lanzado nuevas funcionalidades de IA generativa para empresas en los últimos 30 días?",
        ],
    },
    {
        "name": "Dev Lead (Backend)",
        "agent": "susana",
        "queries": [
            "¿Cuáles son las últimas vulnerabilidades de seguridad críticas reportadas en FastAPI, Python 3.12 o PostgreSQL en febrero-marzo 2026?",
            "Busca los benchmarks más recientes de rendimiento entre PostgreSQL 16 vs MySQL 8.4 para cargas de trabajo de analytics en 2026.",
            "¿Qué novedades hay sobre LangChain, LangGraph o frameworks de agentes AI lanzadas en las últimas semanas?",
        ],
    },
    {
        "name": "Growth Lead",
        "agent": "lucia",
        "queries": [
            "¿Cuál es el market share actual de herramientas de IA generativa B2B en Latinoamérica en 2026? ¿Quién lidera el mercado?",
            "Busca estadísticas recientes de adopción de IA generativa en empresas de LATAM por sector (retail, fintech, salud) en 2026.",
            "¿Qué estrategias de SEO y content marketing están usando las principales plataformas de IA para posicionarse en Google LATAM este año?",
        ],
    },
    {
        "name": "AI Engineer",
        "agent": "sofia",
        "queries": [
            "¿Cuáles son los últimos modelos de lenguaje grandes (LLMs) lanzados en enero-febrero 2026 y sus benchmarks comparativos?",
            "Busca avances recientes en RAG (Retrieval Augmented Generation), vector databases y embeddings multimodales en 2026.",
            "¿Qué novedades hay sobre fine-tuning de modelos open source como Llama 3.3, Mistral o DeepSeek en las últimas semanas?",
        ],
    },
    {
        "name": "Product Manager",
        "agent": "diego",
        "queries": [
            "¿Qué features de IA generativa han lanzado recientemente los principales competidores de plataformas corporativas como Microsoft Copilot, Google Workspace AI o Notion AI?",
            "Busca tendencias de producto en SaaS B2B para 2026: ¿qué funcionalidades de IA están pidiendo los usuarios enterprise?",
            "¿Cuáles son los últimos casos de éxito documentados de implementación de IA generativa en empresas LATAM en 2026?",
        ],
    },
    {
        "name": "Finance Lead",
        "agent": "roberto",
        "queries": [
            "Busca las últimas valoraciones (valuations) de startups de IA generativa B2B en rondas Series A y B en Estados Unidos y LATAM durante Q1 2026.",
            "¿Cuáles son las métricas de SaaS más importantes para inversionistas de VC en 2026? ¿Qué múltiplos de revenue se están pagando?",
            "Busca información sobre subsidios, grants o incentivos fiscales para empresas de IA en Costa Rica, Panamá y Colombia en 2026.",
        ],
    },
]

# ═══════════════════════════════════════════════════════════════════
# SIMULATION ENGINE
# ═══════════════════════════════════════════════════════════════════

def make_request(api_url: str, endpoint: str, payload: dict) -> dict:
    """Make HTTP POST request to the backend."""
    url = f"{api_url}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    
    if HTTP_CLIENT == "httpx":
        import httpx
        with httpx.Client(timeout=180.0, verify=False) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    else:
        req = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=180, context=SSL_CONTEXT) as resp:
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


def simulate_conversation_with_search(api_url: str, persona: dict, query: str, round_num: int):
    """Simulate a single conversation with SEARCH ENABLED."""
    session_id = f"sim-search-{hashlib.md5(f'{persona['name']}:{round_num}:{time.time()}'.encode()).hexdigest()[:12]}"
    
    print(f"\n  🔍 {persona['name']} → Agent: {persona['agent']}")
    print(f"     Query: {query[:70]}...")
    print(f"     [SEARCH ENABLED - Perplexity Sonar active]")
    
    # Step 1: Send chat to /swarm/chat WITH SEARCH ENABLED
    chat_payload = {
        "messages": [{"role": "user", "content": query}],
        "preferred_agent": persona["agent"],
        "model": "Gemini 3.1 Flash Lite",
        "tenant_id": "shift",
        "session_id": session_id,
        "search_enabled": True,  # 🔥 ESTO ES LA CLAVE
        "attachments": [],
    }
    
    start_time = time.time()
    try:
        chat_result = make_request(api_url, "/swarm/chat", chat_payload)
        response_text = chat_result.get("content", "")[:300]
        agent_used = chat_result.get("agent_active", "unknown")
        elapsed = time.time() - start_time
        
        print(f"     ✅ Response from {agent_used} ({elapsed:.1f}s): {response_text[:100]}...")
        
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
        pii_scrubbed = ingest_result.get("pii_scrubbed", False)
        
        pii_indicator = "🔒 PII-scrubbed" if pii_scrubbed else ""
        print(f"     📊 Peaje: {status} | Category: {category} | Confidence: {confidence:.2f} {pii_indicator}")
        
        return {
            "success": True, 
            "agent": agent_used, 
            "category": category, 
            "confidence": confidence,
            "elapsed": elapsed,
            "search_used": True
        }
        
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"     ❌ Error ({elapsed:.1f}s): {e}")
        return {"success": False, "error": str(e), "elapsed": elapsed}


def run_simulation_with_search(api_url: str, rounds: int = 2):
    """Run the full simulation with SEARCH ENABLED."""
    print("═" * 75)
    print("  🌐 FLYWHEEL SIMULATOR v2.0 — SEARCH ENABLED")
    print("  Objetivo: Poblar El Peaje con insights de DATOS EN TIEMPO REAL")
    print(f"  Target: {api_url}")
    print(f"  Rounds: {rounds}")
    print(f"  Personas: {len(SHIFT_PERSONAS_SEARCH)}")
    print(f"  Search Engine: Perplexity Sonar via OpenRouter")
    print("═" * 75)
    
    # Health check
    try:
        health = make_get_request(api_url, "/health")
        print(f"\n  🏥 Backend Health: {health.get('status', 'unknown')}")
        print(f"     Version: {health.get('version', 'N/A')}")
        print(f"     Features: {', '.join(health.get('features', []))}")
    except Exception as e:
        print(f"\n  ❌ Backend unreachable: {e}")
        return
    
    # Check Peaje health before simulation
    try:
        peaje_health = make_get_request(api_url, "/peaje/health")
        print(f"\n  📊 Peaje Health (pre-simulation):")
        print(f"     Insights 24h: {peaje_health.get('insights_24h', 'N/A')}")
        print(f"     Sessions 24h: {peaje_health.get('sessions_24h', 'N/A')}")
    except Exception as e:
        print(f"\n  ⚠️  Could not fetch Peaje health: {e}")
    
    total_success = 0
    total_errors = 0
    categories_seen = {}
    total_elapsed = 0
    
    for round_num in range(1, rounds + 1):
        print(f"\n{'─' * 55}")
        print(f"  🔄 ROUND {round_num}/{rounds} — SEARCH ENABLED")
        print(f"{'─' * 55}")
        
        # Shuffle personas and pick random queries
        personas_this_round = random.sample(SHIFT_PERSONAS_SEARCH, min(len(SHIFT_PERSONAS_SEARCH), 3))
        
        for persona in personas_this_round:
            query = random.choice(persona["queries"])
            result = simulate_conversation_with_search(api_url, persona, query, round_num)
            
            if result["success"]:
                total_success += 1
                cat = result.get("category", "unknown")
                categories_seen[cat] = categories_seen.get(cat, 0) + 1
                total_elapsed += result.get("elapsed", 0)
            else:
                total_errors += 1
            
            time.sleep(2)  # Be nice to the API + allow time for search
    
    # Summary
    print(f"\n{'═' * 75}")
    print(f"  📈 SIMULATION COMPLETE")
    print(f"  ✅ Successful: {total_success}")
    print(f"  ❌ Errors: {total_errors}")
    print(f"  ⏱️  Avg response time: {total_elapsed/max(total_success,1):.1f}s (includes web search)")
    print(f"  📊 Categories populated:")
    for cat, count in sorted(categories_seen.items(), key=lambda x: -x[1]):
        print(f"     • {cat}: {count} insights")
    print(f"{'═' * 75}")
    
    # Check Peaje health after simulation
    print(f"\n  📊 Peaje Health (post-simulation):")
    try:
        peaje_health = make_get_request(api_url, "/peaje/health")
        print(f"     Insights 24h: {peaje_health.get('insights_24h', 'N/A')}")
        print(f"     Sessions 24h: {peaje_health.get('sessions_24h', 'N/A')}")
        print(f"     Avg confidence 7d: {peaje_health.get('avg_confidence_7d', 'N/A')}")
    except Exception as e:
        print(f"     ⚠️  Error: {e}")
    
    # Trigger consolidation
    print(f"\n  🔄 Triggering Punto Medio consolidation...")
    try:
        consolidation = make_request(api_url, "/punto-medio/consolidate", {})
        print(f"     ✅ Consolidation triggered!")
        print(f"     Result: {json.dumps(consolidation, indent=2, default=str)[:400]}")
    except Exception as e:
        print(f"     ⚠️  Consolidation error (may timeout): {e}")
    
    # Check pending reviews
    print(f"\n  📋 Checking pending reviews...")
    try:
        reviews = make_get_request(api_url, "/punto-medio/review")
        pending_c = reviews.get("pending_consolidations_count", 0)
        pending_p = reviews.get("pending_patterns_count", 0)
        print(f"     🔘 Pending consolidations: {pending_c}")
        print(f"     🔘 Pending patterns: {pending_p}")
    except Exception as e:
        print(f"     ⚠️  Review check failed: {e}")


if __name__ == "__main__":
    use_local = "--local" in sys.argv
    api_url = LOCAL_API_URL if use_local else DEFAULT_API_URL
    
    rounds = 2
    for i, arg in enumerate(sys.argv):
        if arg == "--rounds" and i + 1 < len(sys.argv):
            rounds = int(sys.argv[i + 1])
    
    run_simulation_with_search(api_url, rounds)
