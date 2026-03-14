import os
import json
import hashlib
import time
import asyncio
from datetime import datetime
from typing import List, Optional, Annotated, TypedDict, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, BaseMessage
from langchain_core.tools import tool

# Punto Medio & PII Scrubber — Membrana Neuronal v2.0
from pii_scrubber import full_scrub_pipeline, check_deduplication
from punto_medio import (
    get_dynamic_rag, 
    consolidate_punto_medio, 
    get_peaje_stats,
    get_tenant_insights_summary,
    log_prompt_refinement,
    SEED_GLOBAL_RAG,
    SEED_TENANT_CONTEXTS,
)

# MySQL Connection
try:
    import pymysql
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    print("[WARNING] pymysql not installed. El Peaje will run in mock mode.")

load_dotenv()

# Database connection function
def get_db_connection():
    """Get MySQL database connection.
    Supports both Railway auto-injected vars (MYSQLHOST) and custom vars (MYSQL_HOST)."""
    if not MYSQL_AVAILABLE:
        return None
    
    # Railway injects MYSQLHOST, MYSQLUSER, etc. (no underscore)
    # Our custom vars use MYSQL_HOST, MYSQL_USER, etc.
    db_host = os.getenv("MYSQL_HOST") or os.getenv("MYSQLHOST", "localhost")
    db_user = os.getenv("MYSQL_USER") or os.getenv("MYSQLUSER", "root")
    db_pass = os.getenv("MYSQL_PASSWORD") or os.getenv("MYSQLPASSWORD", "")
    db_name = os.getenv("MYSQL_DATABASE") or os.getenv("MYSQLDATABASE", "railway")
    db_port = int(os.getenv("MYSQL_PORT") or os.getenv("MYSQLPORT", "3306"))
    
    try:
        conn = pymysql.connect(
            host=db_host,
            user=db_user,
            password=db_pass,
            database=db_name,
            port=db_port,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=10,
        )
        return conn
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e} (host={db_host}, port={db_port}, db={db_name})")
        return None

app = FastAPI(title="Shift Lab Swarm Cerebro v3 - Legio Digitalis Latina")

# Habilitar CORS - Configurable via environment variable
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001,http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OpenRouter Config - Model mapping (Matches frontend strings EXACTLY)
MODEL_MAP = {
    "Shifty 2.0 by Shift AI": "anthropic/claude-sonnet-4.6",
    "Claude Sonnet 4.6": "anthropic/claude-sonnet-4.6",
    "Gemini 3.1 Flash Lite": "google/gemini-3.1-flash-lite-preview",
    "DeepSeek V3.2": "deepseek/deepseek-v3.2",
    "Gemini 3.1 Pro": "google/gemini-3.1-pro-preview",
    "Claude Opus 4.6": "anthropic/claude-opus-4.6",
    "Moonshot Kimi K2.5": "moonshotai/kimi-k2.5",
}

def get_llm(model_name: str = "Claude 3.5 Sonnet"):
    """Get LLM instance for specific model"""
    # Si es una llamada interna del extractor (backend-only), usamos el string directo
    if "/" in model_name and not model_name.startswith("http"):
        openrouter_model = model_name
    else:
        openrouter_model = MODEL_MAP.get(model_name, "anthropic/claude-sonnet-4.6")
    
    # Obtener API key de OpenRouter (puede ser OPENROUTER_API_KEY u OPENAI_API_KEY)
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY or OPENAI_API_KEY must be set")
        
    return ChatOpenAI(
        model=openrouter_model,
        openai_api_key=api_key,
        openai_api_base=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        default_headers={
            "HTTP-Referer": "https://shiftpn.com",
            "X-Title": "Shift Lab Legio Digitalis",
        }
    )

# Default LLM for orchestrator
llm = get_llm("Claude Sonnet 4.6")

# ═══════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════

@tool
def write_file_tool(path: str, content: str):
    """Escribe contenido directamente en un archivo del repositorio."""
    return f"SOLICITUD_ESCRITURA: {path}"

@tool
def read_file_tool(path: str):
    """Lee el contenido de un archivo del repositorio."""
    return f"SOLICITUD_LECTURA: {path}"

@tool
def execute_command_tool(command: str):
    """Ejecuta un comando en el sistema."""
    return f"SOLICITUD_COMANDO: {command}"

@tool
def search_code_tool(query: str, file_pattern: str = "*"):
    """Busca código en el repositorio usando regex."""
    return f"SOLICITUD_BUSQUEDA: {query} en archivos {file_pattern}"

tools = [write_file_tool, read_file_tool, execute_command_tool, search_code_tool]

# ═══════════════════════════════════════════════════════════════
# SKILLS INJECTION - 15 AGENTES LATINOS
# ═══════════════════════════════════════════════════════════════

SHIFT_LAB_CONTEXT = """
Shift Lab es una membrana neuronal corporativa que evita la Amnesia Organizacional.
Arquitectura Dual: Standalone (Gateway) y Embebido (Invisible Companion).
El 'Punto Medio' captura conocimiento táctil.
"""

# ═══════════════════════════════════════════════════════════════
# SIMULATED RAG - PUNTO MEDIO (TAXONOMÍA EJECUTIVA)
# Simula el estado futuro de Pinecone + Neo4j extrayendo el histórico 
# ofuscado y blindado del 'Punto Medio' e inyectándolo al Swarm
# ═══════════════════════════════════════════════════════════════

PUNTO_MEDIO_GLOBAL_RAG = """
[INTELIGENCIA COLECTIVA LATAM - PATRONES MACRO]:
- Riesgo Ciego Común: Subestimación de fricción logística en última milla.
- Patrón de Decisión Sectorial (Retail): Preferencia por mitigación de riesgo financiero sobre innovación disruptiva en Q1.
- Gap de Productividad Frecuente: Desconexión asimétrica entre equipos creativos y analistas de pauta digital.
"""

TENANT_CONTEXTS = {
    "shift": """
[CONTEXTO CORPORATIVO AISLADO - SHIFT]:
- Identidad: Consultora de innovación y estrategia digital.
- Foco Operativo: IA Generativa aplicada a procesos corporativos B2B.
- Valores Base: Velocidad, Rigor Técnico, Diseño Impecable.
""",
    "garnier": """
[CONTEXTO CORPORATIVO AISLADO - GRUPO GARNIER]:
- Identidad: Red de agencias de comunicación y marketing líder en LatAm.
- Cuentas Core: Consumo masivo (FMCG), retail corporativo, servicios financieros.
- Vectores de Aceleración 2026: Automatización profunda de insights creativos y eficiencia transaccional en media planning.
- Tono Requerido: Estratégico, asertivo, innovador con respaldo C-Level.
"""
}

# 1. PEDRO - Frontend Senior
PEDRO_SKILL = """
Eres Pedro, Frontend Architect Senior.
Skills: React 19, Next.js 15+, Tailwind CSS v4, Framer Motion, Compound Components, 
Custom Hooks, Server Components, ARIA/accessibility, Performance Optimization (Lighthouse 95+),
Micro-interactions, Design Systems, Storybook, TypeScript strict mode.
Patrones: Atomic Design, BEM, CSS-in-JS, Headless UI.
"""

# 2. SUSANA - Backend Engineer
SUSANA_SKILL = """
Eres Susana, Backend Engineer especialista en APIs escalables.
Skills: FastAPI, Node.js/Express, PostgreSQL, MongoDB, Redis, GraphQL (Apollo/Strawberry),
REST API Design (OpenAPI/Swagger), WebSockets, JWT/OAuth2, Rate Limiting, 
Celery/RQ, SQLAlchemy, Prisma, Database Indexing, Query Optimization.
"""

# 3. CARLOS - DevOps/Infra
CARLOS_SKILL = """
Eres Carlos, DevOps Engineer e Infraestructura.
Skills: Docker, Kubernetes, AWS (EC2, S3, RDS, Lambda), GCP, Azure, 
CI/CD (GitHub Actions, GitLab CI), Terraform, Ansible, Nginx, Traefik,
Load Balancing, Monitoring (Prometheus, Grafana, Datadog), Logging (ELK),
Auto-scaling, Cost Optimization, Disaster Recovery.
"""

# 4. MARIA - UX/UI Designer
MARIA_SKILL = """
Eres María, UX/UI Designer enfocada en experiencia humana.
Skills: Figma, Adobe Creative Suite, Design Systems, User Research, 
Wireframing, Prototyping (alta fidelidad), Usability Testing, A/B Testing UX,
Color Theory, Typography, Design Tokens, Accessibility (WCAG 2.1),
Microcopy, User Journey Mapping, Personas.
"""

# 5. JORGE - Copywriter/Content
JORGE_SKILL = """
Eres Jorge, Copywriter y Content Strategist.
Skills: Brand Voice Development, Storytelling, SEO Copywriting, 
Microcopy (UX writing), Email Marketing Sequences, Content Strategy,
Tone & Voice Adaptation, Translation ES/EN/PT, Cultural Localization LATAM,
Social Media Content, Blog Writing, Scriptwriting, Brand Narrative.
"""

# 6. LUCIA - SEO/Growth
LUCIA_SKILL = """
Eres Lucía, Growth & SEO Specialist.
Skills: Technical SEO, On-page SEO, SEM (Google Ads), Analytics (GA4, Mixpanel),
A/B Testing (Optimizely, VWO), Conversion Rate Optimization (CRO),
Funnel Analysis, Keyword Research, Backlink Strategy, Content Marketing,
Growth Hacking, Viral Loops, Retention Strategies.
"""

# 7. ANDRES - Data/Analytics
ANDRES_SKILL = """
Eres Andrés, Data Scientist & Analytics Engineer.
Skills: Python, Pandas, NumPy, SQL avanzado, Data Visualization (Matplotlib, Plotly, D3),
Predictive Modeling, ETL Pipelines, BigQuery, Snowflake, Tableau, Looker,
Machine Learning (scikit-learn), ARIMA/Time Series Forecasting, 
Statistical Analysis, A/B Testing Statistics.
"""

# 8. PATRICIA - Legal/Compliance
PATRICIA_SKILL = """
Eres Patricia, Legal Counsel & Compliance Officer.
Skills: GDPR, LGPD (Brasil), CCPA, Terms of Service drafting, 
Privacy Policies, Copyright & IP Protection, Contract Review,
Compliance Audits, Risk Assessment, Data Processing Agreements,
Cookie Consent, ePrivacy Regulation, Industry-specific compliance (fintech, health).
"""

# 9. ROBERTO - Finance/Business
ROBERTO_SKILL = """
Eres Roberto, Financial Analyst & Business Strategist.
Skills: Financial Modeling, Cash Flow Analysis, Pricing Strategy,
Unit Economics (CAC, LTV, Churn), ROI Analysis, Budgeting & Forecasting,
Investor Decks, Valuation (DCF, Comparables), Cap Table Management,
SaaS Metrics, Burn Rate Analysis, Runway Calculation.
"""

# 10. CARMEN - CEO/Strategy
CARMEN_SKILL = """
Eres Carmen, CEO & Strategic Advisor.
Skills: Business Model Canvas, OKRs, Market Analysis, Competitive Intelligence,
Fundraising (Seed, Series A/B), Partnerships & Alliances, Pivot Strategy,
Board Decks, Executive Communication, Stakeholder Management,
Vision & Mission crafting, Company Culture, Change Management.
"""

# 11. DIEGO - Product Manager
DIEGO_SKILL = """
Eres Diego, Product Manager orientado a resultados.
Skills: Agile/Scrum, Kanban, Roadmapping (Now/Next/Later), User Stories,
Prioritization Frameworks (RICE, MoSCoW), Stakeholder Management,
Product Analytics, Feature Flags, Release Management, Beta Testing,
Customer Discovery, Product-Market Fit, OKRs for Product.
"""

# 12. FERNANDA - QA/Testing
FERNANDA_SKILL = """
Eres Fernanda, QA Engineer & Testing Specialist.
Skills: Automated Testing (Jest, Pytest), E2E Testing (Cypress, Playwright, Selenium),
Unit Testing, Integration Testing, TDD/BDD, Load Testing (k6, JMeter),
Security Testing, Regression Testing, Bug Tracking (Jira), Test Plans,
API Testing (Postman, Insomnia), Visual Regression Testing.
"""

# 13. MARTIN - Mobile Developer
MARTIN_SKILL = """
Eres Martín, Mobile Developer cross-platform.
Skills: React Native, Flutter, Swift (iOS), Kotlin (Android),
iOS Human Interface Guidelines, Android Material Design,
Push Notifications, App Store Optimization (ASO), Offline-first architecture,
Mobile Performance Optimization, Deep Linking, In-App Purchases,
Mobile Analytics (Firebase, Mixpanel).
"""

# 14. SOFIA - AI/ML Engineer
SOFIA_SKILL = """
Eres Sofía, AI/ML Engineer especialista en LLMs.
Skills: PyTorch, TensorFlow, Transformers (Hugging Face), LLMs (GPT, Claude, Llama),
RAG (Retrieval Augmented Generation), Vector Databases (Pinecone, Weaviate, Chroma),
Fine-tuning, Prompt Engineering, LangChain, LangGraph, OpenAI API,
Embeddings, Semantic Search, Computer Vision (OpenCV, YOLO), MLOps.
"""

# 15. GABRIEL - Security Engineer
GABRIEL_SKILL = """
Eres Gabriel, Security Engineer & Ethical Hacker.
Skills: Penetration Testing, OWASP Top 10, Vulnerability Assessment,
WAF (Web Application Firewall), Encryption (AES, RSA), Zero Trust Architecture,
SIEM (Security Information and Event Management), Incident Response,
SOC2 Compliance, ISO 27001, Security Audits, Threat Modeling,
Secure Code Review, Secrets Management (Vault).
"""

# ═══════════════════════════════════════════════════════════════
# SWARM STATE & AGENT DEFINITIONS
# ═══════════════════════════════════════════════════════════════

class SwarmState(TypedDict):
    messages: Annotated[List[BaseMessage], "The messages in the conversation"]
    active_agent: str
    context: str
    agent_outputs: Dict[str, Any]

# Definición de agentes disponibles
AGENTS = {
    "pedro": {"name": "Pedro", "skill": PEDRO_SKILL, "keywords": ["frontend", "react", "ui", "componente", "tsx", "css", "tailwind", "diseño web"]},
    "susana": {"name": "Susana", "skill": SUSANA_SKILL, "keywords": ["backend", "api", "database", "sql", "servidor", "endpoint", "graphql"]},
    "carlos": {"name": "Carlos", "skill": CARLOS_SKILL, "keywords": ["devops", "infra", "docker", "kubernetes", "aws", "deploy", "ci/cd"]},
    "maria": {"name": "María", "skill": MARIA_SKILL, "keywords": ["ux", "ui", "diseño", "figma", "usuario", "experiencia", "mockup"]},
    "jorge": {"name": "Jorge", "skill": JORGE_SKILL, "keywords": ["copy", "texto", "contenido", "blog", "email", "marketing", "storytelling"]},
    "lucia": {"name": "Lucía", "skill": LUCIA_SKILL, "keywords": ["seo", "growth", "analytics", "conversion", "funnel", "trafico", "google"]},
    "andres": {"name": "Andrés", "skill": ANDRES_SKILL, "keywords": ["data", "analytics", "python", "dashboard", "metricas", "prediccion", "sql"]},
    "patricia": {"name": "Patricia", "skill": PATRICIA_SKILL, "keywords": ["legal", "compliance", "gdpr", "contrato", "privacidad", "terminos"]},
    "roberto": {"name": "Roberto", "skill": ROBERTO_SKILL, "keywords": ["finance", "negocio", "precio", "economico", "roi", "inversion", "saas"]},
    "carmen": {"name": "Carmen", "skill": CARMEN_SKILL, "keywords": ["ceo", "estrategia", "vision", "pitch", "board", "fundrais", "mercado"]},
    "diego": {"name": "Diego", "skill": DIEGO_SKILL, "keywords": ["producto", "pm", "roadmap", "feature", "user story", "agile", "scrum"]},
    "fernanda": {"name": "Fernanda", "skill": FERNANDA_SKILL, "keywords": ["qa", "test", "bug", "cypress", "testing", "calidad", "automation"]},
    "martin": {"name": "Martín", "skill": MARTIN_SKILL, "keywords": ["mobile", "app", "ios", "android", "react native", "flutter", "movil"]},
    "sofia": {"name": "Sofía", "skill": SOFIA_SKILL, "keywords": ["ai", "ml", "llm", "gpt", "langchain", "embedding", "vector", "prompt"]},
    "gabriel": {"name": "Gabriel", "skill": GABRIEL_SKILL, "keywords": ["security", "seguridad", "hack", "owasp", "vulnerability", "encrypt"]},
}

# ═══════════════════════════════════════════════════════════════
# NODE FUNCTIONS
# ═══════════════════════════════════════════════════════════════

# NOTE: The API endpoints below call agents directly via create_agent_node_with_model()
# and determine_agent_from_message(). No LangGraph compiled graph is needed.



class ChatMessage(BaseModel):
    role: str
    content: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("user", "assistant", "system"):
            raise ValueError("role must be 'user', 'assistant', or 'system'")
        return v

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if len(v) > 10_000:
            raise ValueError("message content must be under 10,000 characters")
        return v

class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    context: Optional[str] = None
    preferred_agent: Optional[str] = None
    model: Optional[str] = "Claude 3.5 Sonnet"
    tenant_id: str = "shift"
    session_id: Optional[str] = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, v: list) -> list:
        if len(v) > 50:
            raise ValueError("maximum 50 messages per request")
        if len(v) == 0:
            raise ValueError("at least one message is required")
        return v

class DebateDashboardRequest(BaseModel):
    topic: str
    expected_output: str
    agent_a_id: str
    agent_b_id: str
    soul_a: Optional[str] = ""
    soul_b: Optional[str] = ""
    turns: int = 1
    model: Optional[str] = "Claude Opus 4.6"
    tenant_id: str = "shift"
    session_id: Optional[str] = None

def create_agent_node_with_model(agent_id: str, model_name: str, tenant_id: str = "shift"):
    """Factory function para crear nodos de agentes con modelo específico e inyección de RAG/Tenant DINÁMICO."""
    def agent_node(state: SwarmState):
        agent_info = AGENTS[agent_id]
        # Asegurar que tid sea siempre string
        tid = str(tenant_id) if tenant_id is not None else "shift"
        
        # ═══════════════════════════════════════════════════════════
        # DYNAMIC RAG INJECTION — Punto Medio v2.0
        # Replaces hardcoded PUNTO_MEDIO_GLOBAL_RAG with REAL data
        # from the consolidated institutional memory.
        # Falls back to seed data if DB is unavailable.
        # ═══════════════════════════════════════════════════════════
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            punto_medio_injection = dynamic_rag["combined_rag"]
            if rag_conn:
                rag_conn.close()
        except Exception as rag_err:
            print(f"[DYNAMIC RAG] Falling back to seed: {rag_err}")
            punto_medio_injection = PUNTO_MEDIO_GLOBAL_RAG
        
        # Tenant context: try dynamic first, then hardcoded seed
        tenant_context = TENANT_CONTEXTS.get(tid, SEED_TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS.get("shift", "")))
        
        # INYECCIÓN DEL RAG (Dynamic Graph Injection)
        system_content = f"""
{SHIFT_LAB_CONTEXT}
{tenant_context}
{punto_medio_injection}

TU ROL ACTUAL (ESPECIALISTA):
{agent_info['skill']}

INSTRUCCIONES:
- Tienes acceso a herramientas: write_file_tool, read_file_tool, execute_command_tool, search_code_tool.
- IMPORTANTE: Eres {agent_info['name']}, un especialista. Responde directamente al usuario de manera natural y profesional.
- NO menciones el "swarm", "orquestador" ni que eres una IA multi-agente.
- El usuario debe sentir que está hablando directamente con un consultor senior de {tid.upper()}.
        """
        
        # Use the selected model
        agent_llm = get_llm(model_name)
        bound_llm = agent_llm.bind_tools(tools)
        messages = [SystemMessage(content=system_content)] + state["messages"]
        response = bound_llm.invoke(messages)
        
        return {
            "messages": state["messages"] + [response],  # ✅ ACUMULAR historial completo
            "active_agent": agent_id,
            "agent_outputs": {**state.get("agent_outputs", {}), agent_id: response.content}
        }
    return agent_node


def create_async_agent_node(agent_id: str, model_name: str, tenant_id: str = "shift"):
    """Async factory for debate agents — avoids blocking the event loop during LLM calls."""
    async def agent_node_async(state: SwarmState):
        agent_info = AGENTS[agent_id]
        tid = str(tenant_id) if tenant_id is not None else "shift"
        
        # Dynamic RAG injection
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            punto_medio_injection = dynamic_rag["combined_rag"]
            if rag_conn:
                rag_conn.close()
        except Exception as rag_err:
            print(f"[DYNAMIC RAG] Falling back to seed: {rag_err}")
            punto_medio_injection = PUNTO_MEDIO_GLOBAL_RAG
        
        tenant_context = TENANT_CONTEXTS.get(tid, SEED_TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS.get("shift", "")))
        
        system_content = f"""
{SHIFT_LAB_CONTEXT}
{tenant_context}
{punto_medio_injection}

TU ROL ACTUAL (ESPECIALISTA):
{agent_info['skill']}

INSTRUCCIONES:
- Tienes acceso a herramientas: write_file_tool, read_file_tool, execute_command_tool, search_code_tool.
- IMPORTANTE: Eres {agent_info['name']}, un especialista. Responde directamente al usuario de manera natural y profesional.
- NO menciones el "swarm", "orquestador" ni que eres una IA multi-agente.
- El usuario debe sentir que está hablando directamente con un consultor senior de {tid.upper()}.
        """
        
        agent_llm = get_llm(model_name)
        bound_llm = agent_llm.bind_tools(tools)
        messages = [SystemMessage(content=system_content)] + state["messages"]
        
        # ✅ ASYNC invoke — does NOT block the event loop
        response = await bound_llm.ainvoke(messages)
        
        return {
            "messages": state["messages"] + [response],
            "active_agent": agent_id,
            "agent_outputs": {**state.get("agent_outputs", {}), agent_id: response.content}
        }
    return agent_node_async

def determine_agent_from_message(message_content: str) -> str:
    """Orquestador simple que decide qué agente usar basado en el mensaje."""
    message_lower = message_content.lower()
    
    # Buscar coincidencias de keywords
    agent_scores: Dict[str, int] = {}
    for agent_id, agent_info in AGENTS.items():
        score = sum(1 for keyword in agent_info["keywords"] if keyword in message_lower)
        if score > 0:
            agent_scores[agent_id] = score
    
    # Si hay coincidencias, elegir la mejor resolviendo el linter error
    if agent_scores:
        best_agent = ""
        max_score = 0
        for agent, score in agent_scores.items():
            if score > max_score:
                max_score = score
                best_agent = agent
        return best_agent if best_agent else "shiftai"
    
    # Si no hay coincidencias claras, retornar shiftai (agente general)
    return "shiftai"

@app.post("/swarm/debate")
async def swarm_debate(request: DebateDashboardRequest):
    """v3.0 — Simple JSON debate. No streaming. 3 agents, 1 response.
    
    Architecture: Agent A → Agent B → Judge → Single JSON response.
    Same pattern as /swarm/chat which is proven to work.
    """
    try:
        # ═══ NORMALIZE AGENT IDS ═══
        def norm(aid: str) -> str:
            return aid.split(" ")[0].lower().strip("-_.").replace("í","i").replace("á","a").replace("ó","o").replace("ú","u")
        
        a_id = norm(request.agent_a_id)
        b_id = norm(request.agent_b_id)
        
        # Pick model — allow any model in MODEL_MAP, default to Opus
        safe_model = str(request.model) if request.model in MODEL_MAP else "Claude Opus 4.6"
        tid = str(request.tenant_id or "shift")
        
        # Validate agents exist
        if a_id not in AGENTS:
            raise HTTPException(status_code=400, detail=f"Agente '{a_id}' no existe. Disponibles: {list(AGENTS.keys())}")
        if b_id not in AGENTS:
            raise HTTPException(status_code=400, detail=f"Agente '{b_id}' no existe. Disponibles: {list(AGENTS.keys())}")
        
        print(f"[DEBATE v3] {AGENTS[a_id]['name']} vs {AGENTS[b_id]['name']} | Topic: {request.topic[:50]}... | Model: {safe_model} | Turns: {request.turns}")
        
        # ═══ BUILD LLM ═══
        debate_llm = get_llm(safe_model)
        
        # ═══ RAG CONTEXT ═══
        try:
            rag_conn = get_db_connection()
            dynamic_rag = get_dynamic_rag(rag_conn, tid)
            rag_text = dynamic_rag["combined_rag"]
            if rag_conn: rag_conn.close()
        except Exception:
            rag_text = PUNTO_MEDIO_GLOBAL_RAG
        
        tenant_ctx = TENANT_CONTEXTS.get(tid, SEED_TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS.get("shift", "")))
        
        # ═══ AGENT SYSTEM PROMPTS ═══
        def build_system(agent_id: str, soul: str = "") -> str:
            info = AGENTS[agent_id]
            base = f"""{SHIFT_LAB_CONTEXT}\n{tenant_ctx}\n{rag_text}\n\nTU ROL: {info['skill']}\n\nINSTRUCCIONES:\n- Eres {info['name']}, consultor senior de {tid.upper()}.\n- Argumenta con datos, frameworks y ejemplos concretos.\n- Sé directo, estratégico y accionable."""
            if soul:
                base += f"\n\nDIRECTIVA ESPECIAL DEL USUARIO PARA TI:\n{soul}"
            return base
        
        sys_a = build_system(a_id, request.soul_a or "")
        sys_b = build_system(b_id, request.soul_b or "")
        
        # ═══ DEBATE LOOP ═══
        transcript = []
        context_thread = f"TEMA: {request.topic}\nOBJETIVO/OUTPUT ESPERADO: {request.expected_output}"
        
        for turn in range(1, request.turns + 1):
            print(f"[DEBATE v3] Turn {turn}/{request.turns} — Agent A: {a_id}")
            
            # Agent A argues
            prompt_a = f"{context_thread}\n\n{'Responde al argumento anterior de tu contraparte y avanza hacia el OBJETIVO.' if turn > 1 else 'Presenta tu argumento inicial hacia el OBJETIVO.'}"
            resp_a = await debate_llm.ainvoke([SystemMessage(content=sys_a), HumanMessage(content=prompt_a)])
            text_a = resp_a.content if hasattr(resp_a, 'content') else str(resp_a)
            transcript.append({"turn": turn, "agent": a_id, "agent_name": AGENTS[a_id]["name"], "side": "A", "content": text_a})
            
            print(f"[DEBATE v3] Turn {turn}/{request.turns} — Agent B: {b_id}")
            
            # Agent B responds to A
            prompt_b = f"{context_thread}\n\nARGUMENTO DE {AGENTS[a_id]['name']}:\n{text_a}\n\nRefuta, complementa o construye sobre esto para alcanzar el OBJETIVO."
            resp_b = await debate_llm.ainvoke([SystemMessage(content=sys_b), HumanMessage(content=prompt_b)])
            text_b = resp_b.content if hasattr(resp_b, 'content') else str(resp_b)
            transcript.append({"turn": turn, "agent": b_id, "agent_name": AGENTS[b_id]["name"], "side": "B", "content": text_b})
            
            # Update context thread for next round
            context_thread += f"\n\n[TURNO {turn} - {AGENTS[a_id]['name']}]: {text_a}\n[TURNO {turn} - {AGENTS[b_id]['name']}]: {text_b}"
        
        # ═══ JUDGE SYNTHESIS ═══
        print(f"[DEBATE v3] Judge synthesizing...")
        
        transcript_md = "\n\n".join([f"### Turno {t['turn']} — {t['agent_name']} (Lado {t['side']})\n{t['content']}" for t in transcript])
        
        judge_prompt = f"""{rag_text}

Eres el Juez Estratégico de Shifty Studio Arena. Acabas de presenciar un debate entre **{AGENTS[a_id]['name']}** y **{AGENTS[b_id]['name']}**.

**TEMA:** {request.topic}
**OUTPUT ESPERADO:** {request.expected_output}

**TRANSCRIPCIÓN:**
{transcript_md}

**TU MISIÓN:**
1. Evalúa los argumentos con rigor — identifica los puntos más fuertes de cada lado.
2. Donde haya contradicciones, toma postura firme con justificación.
3. Genera DIRECTAMENTE el output que pidió el usuario en el formato esperado.
4. Nivel consultoría estratégica (McKinsey/BCG) — accionable, listo para ejecutar.
5. Si aplica, incluye: recomendaciones priorizadas, riesgos identificados, próximos pasos concretos."""
        
        judge_resp = await debate_llm.ainvoke([SystemMessage(content=judge_prompt)])
        synthesis = judge_resp.content if hasattr(judge_resp, 'content') else str(judge_resp)
        
        print(f"[DEBATE v3] ✓ Complete. Transcript: {len(transcript)} entries, Synthesis: {len(synthesis)} chars")
        
        return {
            "content": synthesis,
            "transcript": transcript,
            "agent_active": "debate_judge",
            "debate_participants": [a_id, b_id],
            "model_used": safe_model,
            "turns_completed": request.turns
        }
        
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error en debate: {str(e)}")

@app.post("/swarm/chat")
async def swarm_chat(request: ChatRequest):
    try:
        # Transform messages to LangChain format
        lc_messages = [
            HumanMessage(content=m.content) if m.role == "user" else AIMessage(content=m.content)
            for m in request.messages
        ]
        
        # Determine which agent to use
        target_agent = request.preferred_agent
        if not target_agent or target_agent not in AGENTS:
            # Use orchestrator to determine agent
            last_message = request.messages[-1].content if request.messages else ""
            target_agent = determine_agent_from_message(last_message)
            print(f"[SWARM] Orquestador seleccionó: {target_agent}")
        
        print(f"[SWARM] Agent: {target_agent}, Model: {request.model}")
        
        # Prepare state for agent
        inputs = {
            "messages": lc_messages,
            "context": request.context or "",
            "active_agent": target_agent,
            "agent_outputs": {}
        }
        
        # Helper seguro para extraer texto
        def get_message_content(messages_list):
            if not messages_list: return ""
            last_msg = messages_list[-1]
            return last_msg.content if hasattr(last_msg, 'content') else str(last_msg)

        # Create agent node with selected model and invoke directly
        safe_tenant_id = str(request.tenant_id or "shift")
        tenant_context = TENANT_CONTEXTS.get(safe_tenant_id, TENANT_CONTEXTS["shift"])

        if target_agent == "shiftai":
            # Use general agent (shiftai) with selected model and tenant context
            agent_llm = get_llm(str(request.model or "Claude 3.5 Sonnet"))
            system_content = f"""
{SHIFT_LAB_CONTEXT}
{tenant_context}

Eres un asistente de IA profesional y directo de {safe_tenant_id.upper()}. Responde de manera natural y útil.
IMPORTANTE: NO menciones que eres un "orquestador" o parte de un sistema multi-agente.
El usuario debe sentir que está hablando directamente contigo.
            """
            messages = [SystemMessage(content=system_content)] + lc_messages
            response = agent_llm.invoke(messages)
            final_msg = response.content if hasattr(response, 'content') else str(response)
        else:
            # Use specialized agent with selected model and tenant isolation
            agent_node = create_agent_node_with_model(
                target_agent, 
                str(request.model or "Claude 3.5 Sonnet"), 
                safe_tenant_id
            )
            # Pasando a dict compatible con SwarmState
            valid_state: SwarmState = {"messages": lc_messages, "context": request.context or "", "active_agent": target_agent, "agent_outputs": {}}
            result_state = agent_node(valid_state)
            final_msg = get_message_content(result_state.get("messages", []))
        
        print(f"[SWARM] Response from {target_agent} using {request.model}")
        
        return {
            "content": final_msg,
            "agent_active": target_agent,
            "agent_outputs": {}
        }
    
    except Exception as e:
        print(f"[SWARM ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))

# El Peaje - Insight ingestion endpoint
class PeajeIngestRequest(BaseModel):
    tenantId: str
    sessionId: str
    agentId: str
    messages: List[ChatMessage]
    response: str

async def extract_insight_data_async(messages: List[ChatMessage], response: str, tenant_id: str) -> dict:
    """Extractor Agéntico para 'El Peaje': Destila Insights, Gaps y Patrones con Anonimización NER."""
    
    # Preparamos la conversación para el LLM
    conversation_text = "\n".join([f"{m.role.upper()}: {m.content}" for m in messages])
    conversation_text += f"\nASSISTANT: {response}"
    
    extractor_prompt = f"""
Eres el 'Pattern Extractor & NER Anonymizer' de Shifty Studio (Punto Medio).
Tu misión es procesar la siguiente conversación de un ejecutivo y extraer la inteligencia estructural.

REGLAS DE ANONIMIZACIÓN (NER):
- Elimina NOMBRES de personas, empresas, proyectos específicos o clientes.
- Elimina MÉTRICAS financieras exactas o KPIs crudos (ej: de '$5M' a 'capital intensivo').
- Sustituye localizaciones por regiones macro (ej: de 'Santiago' a 'cono sur').

TAXONOMÍA REQUERIDA (Elige la más relevante):
- "Riesgos Ciegos Detectados"
- "Patrones de Decisión Sectorial"
- "Gaps de Productividad Institucional"
- "Vectores de Aceleración Ocultos"

CONVERSACIÓN:
{conversation_text}

Debes responder ÚNICAMENTE con un JSON válido con esta estructura exacta:
{{
    "insight_text": "El resumen ejecutivo anonimizado (Entidad-Contexto-Valor).",
    "category": "Una de las 4 taxonomías requeridas",
    "sentiment": "positive, negative, o neutral",
    "confidence_score": 0.95
}}
    """
    
    try:
        # Usamos el modelo GRATUITO de MiniMax en OpenRouter para no consumir saldo del Peaje
        # Esto permite que el backend extraiga miles de insights sin costo operativo.
        extraction_llm = get_llm("minimax/minimax-m2.5") 
        result = await extraction_llm.ainvoke([SystemMessage(content=extractor_prompt)])
        
        # Limpiar posible markdown block
        json_str = result.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(json_str)
        
        return {
            "insight_text": data.get("insight_text", "Extracción genérica de interacción"),
            "category": data.get("category", "Vectores de Aceleración Ocultos"),
            "sentiment": data.get("sentiment", "neutral"),
            "confidence_score": data.get("confidence_score", 0.50)
        }
    except Exception as e:
        print(f"[EXTRACTOR ERROR] {e} - Cayendo a heurística básica")
        return {
            "insight_text": "Interacción registrada sin extracción profunda",
            "category": "Patrones de Decisión Sectorial",
            "sentiment": "neutral",
            "confidence_score": 0.10
        }

@app.post("/peaje/ingest")
async def peaje_ingest(request: PeajeIngestRequest):
    """Ingesta asíncrona hacia el Flywheel (El Peaje) — v2.0 con PII Scrubber + Taxonomy Validation"""
    extraction_start = time.time()
    try:
        print(f"[EL PEAJE v2] Processing: Tenant={request.tenantId}, Agent={request.agentId}")
        
        # Generate hashes for anonymization & deduplication
        conversation_text = json.dumps([{"role": m.role, "content": m.content} for m in request.messages])
        anonymized_hash = hashlib.sha256(f"{request.tenantId}:{request.sessionId}:{datetime.now().isoformat()}".encode()).hexdigest()
        conversation_hash = hashlib.sha256(conversation_text.encode()).hexdigest()

        # Get database connection
        conn = get_db_connection()
        
        # ═══ DEDUPLICATION CHECK ═══
        if conn and check_deduplication(conversation_hash, conn):
            print(f"[EL PEAJE v2] Duplicate detected, skipping: {conversation_hash[:16]}...")
            if conn:
                conn.close()
            return {"status": "deduplicated", "tenant": request.tenantId, "conversation_hash": conversation_hash[:16]}
        
        # ═══ STEP 1: LLM Extraction (Layer 1 — Probabilistic) ═══
        insight_data = await extract_insight_data_async(request.messages, request.response, request.tenantId)
        
        # ═══ STEP 2: PII Scrubber (Layer 2 — Deterministic) ═══
        # Get tenant industry for context
        tenant_industry = None
        if conn:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("SELECT industry_vertical FROM peaje_tenants WHERE tenant_id = %s", (request.tenantId,))
                    tenant_row = cursor.fetchone()
                    if tenant_row:
                        tenant_industry = tenant_row.get("industry_vertical")
            except Exception:
                pass
        
        scrub_result = full_scrub_pipeline(
            insight_text=insight_data["insight_text"],
            raw_category=insight_data["category"],
            tenant_industry=tenant_industry,
            conversation_text=conversation_text,
        )
        
        extraction_duration_ms = int((time.time() - extraction_start) * 1000)
        extraction_model = "minimax/minimax-m2.5"
        
        print(f"[EL PEAJE v2] PII Scrubbed: {scrub_result['total_pii_scrubbed']} items | "
              f"Category: {scrub_result['original_category']} → {scrub_result['validated_category']} "
              f"(valid={scrub_result['category_was_valid']}) | "
              f"Industry: {scrub_result['industry_vertical']}")
        
        if conn:
            try:
                with conn.cursor() as cursor:
                    # ═══ STEP 3: Insert insight with v2.0 schema ═══
                    sql = """
                        INSERT INTO peaje_insights 
                        (tenant_id, session_id, agent_id, insight_text, 
                         category, sub_category, industry_vertical,
                         sentiment, confidence_score, extraction_model, pii_scrubbed,
                         source_type, anonymized_hash, raw_conversation_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        request.tenantId,
                        request.sessionId,
                        request.agentId,
                        scrub_result["scrubbed_text"],           # PII-scrubbed text
                        scrub_result["validated_category"],       # Taxonomy-validated category
                        scrub_result["sub_category"],             # Sub-category (may be None)
                        scrub_result["industry_vertical"],        # Detected industry
                        insight_data["sentiment"],
                        insight_data["confidence_score"],         # REAL confidence from LLM
                        extraction_model,
                        scrub_result["pii_scrubbed"],             # TRUE if PII was found & scrubbed
                        "chat",                                   # source_type
                        anonymized_hash,
                        conversation_hash
                    ))
                    insight_id = cursor.lastrowid
                    
                    # ═══ STEP 4: Update session tracking ═══
                    session_sql = """
                        INSERT INTO peaje_sessions 
                        (tenant_id, session_id, message_count, insight_count, agents_used, source, debate_mode)
                        VALUES (%s, %s, %s, 1, %s, %s, FALSE)
                        ON DUPLICATE KEY UPDATE
                        message_count = message_count + %s,
                        insight_count = insight_count + 1,
                        agents_used = JSON_MERGE_PATCH(COALESCE(agents_used, '[]'), %s)
                    """
                    agents_json = json.dumps([request.agentId])
                    cursor.execute(session_sql, (
                        request.tenantId,
                        request.sessionId,
                        len(request.messages),
                        agents_json,
                        "embed" if "embed" in request.sessionId else "standalone",
                        len(request.messages),
                        agents_json
                    ))
                    
                    # ═══ STEP 5: Log extraction audit trail ═══
                    log_sql = """
                        INSERT INTO peaje_extraction_log
                        (insight_id, tenant_id, session_id, extraction_model, extraction_duration_ms,
                         pii_items_scrubbed, pii_types_found, extraction_status, category_validated,
                         original_category, input_message_count, input_char_count, conversation_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(log_sql, (
                        insight_id,
                        request.tenantId,
                        request.sessionId,
                        extraction_model,
                        extraction_duration_ms,
                        scrub_result["total_pii_scrubbed"],
                        json.dumps(scrub_result["pii_counts"]),
                        "success",
                        scrub_result["category_was_valid"],
                        scrub_result["original_category"],
                        len(request.messages),
                        len(conversation_text),
                        conversation_hash
                    ))
                    
                    conn.commit()
                    
                print(f"[EL PEAJE v2] ✓ Insight saved ID:{insight_id} | "
                      f"PII:{scrub_result['total_pii_scrubbed']} | "
                      f"Cat:{scrub_result['validated_category']} | "
                      f"{extraction_duration_ms}ms")
                
                return {
                    "status": "ingested",
                    "version": "v2.0",
                    "tenant": request.tenantId,
                    "insight_id": insight_id,
                    "category": scrub_result["validated_category"],
                    "sub_category": scrub_result["sub_category"],
                    "industry_vertical": scrub_result["industry_vertical"],
                    "sentiment": insight_data["sentiment"],
                    "confidence_score": insight_data["confidence_score"],
                    "pii_scrubbed": scrub_result["pii_scrubbed"],
                    "pii_items_removed": scrub_result["total_pii_scrubbed"],
                    "category_validated": scrub_result["category_was_valid"],
                    "extraction_ms": extraction_duration_ms,
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as db_error:
                conn.rollback()
                print(f"[EL PEAJE v2 DB ERROR] {db_error}")
                return {
                    "status": "logged_only",
                    "tenant": request.tenantId,
                    "error": str(db_error),
                    "category": scrub_result["validated_category"],
                    "sentiment": insight_data["sentiment"]
                }
            finally:
                conn.close()
        else:
            print(f"[EL PEAJE v2] Database not available, logged only")
            return {
                "status": "logged_only",
                "tenant": request.tenantId,
                "category": scrub_result["validated_category"],
                "sentiment": insight_data["sentiment"],
                "note": "Database connection not available"
            }
            
    except Exception as e:
        print(f"[EL PEAJE v2 ERROR] {e}")
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# DEBATE INGESTION — v2.0
# Debates are the richest source of strategic intelligence.
# This endpoint processes debate transcripts into the Peaje.
# ═══════════════════════════════════════════════════════════════

class PeajeDebateIngestRequest(BaseModel):
    tenantId: str
    sessionId: str
    agentA: str
    agentB: str
    topic: str
    transcript: List[Dict[str, Any]]
    synthesis: str

@app.post("/peaje/ingest-debate")
async def peaje_ingest_debate(request: PeajeDebateIngestRequest):
    """Ingest a debate transcript into the Peaje — extracts multiple insights from the rich strategic content."""
    try:
        print(f"[EL PEAJE v2 DEBATE] Processing debate: {request.agentA} vs {request.agentB} on '{request.topic[:40]}...'")
        
        insights_saved = 0
        errors = []
        
        # Process each turn of the debate as a separate insight
        for i, turn in enumerate(request.transcript):
            try:
                turn_content = turn.get("content", "")
                turn_agent = turn.get("agent", "debate_judge")
                
                if not turn_content or len(turn_content) < 20:
                    continue
                
                # Build a synthetic message list for the extractor
                synthetic_messages = [
                    ChatMessage(role="user", content=f"DEBATE TOPIC: {request.topic}"),
                    ChatMessage(role="assistant", content=turn_content),
                ]
                
                # Extract insight from this turn
                insight_data = await extract_insight_data_async(synthetic_messages, turn_content, request.tenantId)
                
                # PII Scrub
                scrub_result = full_scrub_pipeline(
                    insight_text=insight_data["insight_text"],
                    raw_category=insight_data["category"],
                    conversation_text=turn_content,
                )
                
                # Save to database
                conn = get_db_connection()
                if conn:
                    try:
                        conversation_hash = hashlib.sha256(f"{request.sessionId}:turn{i}:{turn_content[:100]}".encode()).hexdigest()
                        anonymized_hash = hashlib.sha256(f"{request.tenantId}:{request.sessionId}:debate:{i}".encode()).hexdigest()
                        
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO peaje_insights 
                                (tenant_id, session_id, agent_id, insight_text, 
                                 category, sub_category, industry_vertical,
                                 sentiment, confidence_score, extraction_model, pii_scrubbed,
                                 source_type, debate_turn, anonymized_hash, raw_conversation_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.tenantId,
                                request.sessionId,
                                turn_agent,
                                scrub_result["scrubbed_text"],
                                scrub_result["validated_category"],
                                scrub_result["sub_category"],
                                scrub_result["industry_vertical"],
                                insight_data["sentiment"],
                                insight_data["confidence_score"],
                                "minimax/minimax-m2.5",
                                scrub_result["pii_scrubbed"],
                                "debate",
                                i + 1,
                                anonymized_hash,
                                conversation_hash
                            ))
                            
                            # Update session as debate
                            cursor.execute("""
                                INSERT INTO peaje_sessions 
                                (tenant_id, session_id, message_count, insight_count, agents_used, source, debate_mode)
                                VALUES (%s, %s, 1, 1, %s, 'standalone', TRUE)
                                ON DUPLICATE KEY UPDATE
                                    message_count = message_count + 1,
                                    insight_count = insight_count + 1,
                                    debate_mode = TRUE
                            """, (
                                request.tenantId,
                                request.sessionId,
                                json.dumps([request.agentA, request.agentB]),
                            ))
                        
                        conn.commit()
                        insights_saved += 1
                    except Exception as db_err:
                        errors.append(f"Turn {i}: {str(db_err)}")
                    finally:
                        conn.close()
                        
            except Exception as turn_err:
                errors.append(f"Turn {i}: {str(turn_err)}")
        
        # Also extract an insight from the judge's synthesis
        if request.synthesis and len(request.synthesis) > 20:
            try:
                synth_messages = [
                    ChatMessage(role="user", content=f"DEBATE SYNTHESIS: {request.topic}"),
                    ChatMessage(role="assistant", content=request.synthesis),
                ]
                synth_data = await extract_insight_data_async(synth_messages, request.synthesis, request.tenantId)
                synth_scrub = full_scrub_pipeline(
                    insight_text=synth_data["insight_text"],
                    raw_category=synth_data["category"],
                    conversation_text=request.synthesis,
                )
                
                conn = get_db_connection()
                if conn:
                    try:
                        with conn.cursor() as cursor:
                            cursor.execute("""
                                INSERT INTO peaje_insights 
                                (tenant_id, session_id, agent_id, insight_text, 
                                 category, sub_category, industry_vertical,
                                 sentiment, confidence_score, extraction_model, pii_scrubbed,
                                 source_type, anonymized_hash, raw_conversation_hash)
                                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """, (
                                request.tenantId,
                                request.sessionId,
                                "debate_judge",
                                synth_scrub["scrubbed_text"],
                                synth_scrub["validated_category"],
                                synth_scrub["sub_category"],
                                synth_scrub["industry_vertical"],
                                synth_data["sentiment"],
                                min(synth_data["confidence_score"] + 0.10, 0.99),  # Synthesis gets confidence boost
                                "minimax/minimax-m2.5",
                                synth_scrub["pii_scrubbed"],
                                "debate",
                                hashlib.sha256(f"{request.tenantId}:{request.sessionId}:synthesis".encode()).hexdigest(),
                                hashlib.sha256(request.synthesis[:200].encode()).hexdigest(),
                            ))
                        conn.commit()
                        insights_saved += 1
                    except Exception as synth_db_err:
                        errors.append(f"Synthesis: {str(synth_db_err)}")
                    finally:
                        conn.close()
            except Exception as synth_err:
                errors.append(f"Synthesis: {str(synth_err)}")
        
        print(f"[EL PEAJE v2 DEBATE] ✓ {insights_saved} insights saved from debate | Errors: {len(errors)}")
        
        return {
            "status": "ingested",
            "version": "v2.0",
            "source": "debate",
            "tenant": request.tenantId,
            "insights_saved": insights_saved,
            "turns_processed": len(request.transcript),
            "errors": errors[:5] if errors else [],
            "timestamp": datetime.now().isoformat()
        }
        
    except Exception as e:
        print(f"[EL PEAJE v2 DEBATE ERROR] {e}")
        return {"status": "error", "message": str(e)}


# ═══════════════════════════════════════════════════════════════
# PUNTO MEDIO ENDPOINTS — v2.0
# ═══════════════════════════════════════════════════════════════

@app.post("/punto-medio/consolidate")
async def consolidate_endpoint():
    """Trigger Punto Medio consolidation job.
    In production, this should be called by a cron job every 6 hours.
    Can also be triggered manually for immediate refresh."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        result = await consolidate_punto_medio(conn)
        return result
    finally:
        conn.close()

@app.get("/punto-medio/rag/{tenant_id}")
async def get_rag_for_tenant(tenant_id: str):
    """Get the dynamic RAG injection text for a specific tenant.
    Shows what would be injected into system prompts.
    Useful for debugging and transparency."""
    conn = get_db_connection()
    try:
        rag = get_dynamic_rag(conn, tenant_id)
        return {
            "tenant_id": tenant_id,
            "global_rag_length": len(rag["global_rag"]),
            "tenant_rag_length": len(rag["tenant_rag"]),
            "patterns_rag_length": len(rag["patterns_rag"]),
            "combined_rag_length": len(rag["combined_rag"]),
            "global_rag": rag["global_rag"],
            "tenant_rag": rag["tenant_rag"],
            "patterns_rag": rag["patterns_rag"],
        }
    finally:
        if conn:
            conn.close()


# ═══════════════════════════════════════════════════════════════
# PEAJE HEALTH & INSIGHTS ENDPOINTS — v2.0
# ═══════════════════════════════════════════════════════════════

@app.get("/peaje/health")
async def peaje_health():
    """Get health and statistics from the Peaje/Punto Medio system."""
    conn = get_db_connection()
    try:
        stats = get_peaje_stats(conn)
        return stats
    finally:
        if conn:
            conn.close()

@app.get("/peaje/insights/{tenant_id}")
async def peaje_insights_for_tenant(tenant_id: str):
    """Get insights summary for a specific tenant.
    STRICT MULTI-TENANT ISOLATION: Only returns data for the specified tenant."""
    conn = get_db_connection()
    if not conn:
        raise HTTPException(status_code=503, detail="Database not available")
    
    try:
        summary = get_tenant_insights_summary(conn, tenant_id)
        return summary
    finally:
        conn.close()


# Legacy function - kept for compatibility
async def extract_insight(messages: List[ChatMessage], response: str) -> Optional[dict]:
    """Extract actionable insight from conversation (El Peaje v0.1)"""
    return await extract_insight_data_async(messages, response, "shift")

@app.get("/swarm/agents")
async def list_agents():
    """Lista todos los agentes disponibles con sus skills."""
    return {
        "agents": [
            {
                "id": agent_id,
                "name": info["name"],
                "keywords": info["keywords"]
            }
            for agent_id, info in AGENTS.items()
        ]
    }

@app.get("/health")
async def health():
    return {
        "status": "healthy", 
        "service": "shift-cerebro-swarm-v3-legio-digitalis",
        "version": "v2.0-punto-medio",
        "agents_count": len(AGENTS),
        "agents": [info["name"] for info in AGENTS.values()],
        "features": ["dynamic_rag", "pii_scrubber", "taxonomy_validation", "debate_ingestion", "punto_medio"]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
