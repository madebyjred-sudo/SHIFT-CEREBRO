import os
import json
import hashlib
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
    """Get MySQL database connection"""
    if not MYSQL_AVAILABLE:
        return None
    try:
        return pymysql.connect(
            host=os.getenv("MYSQL_HOST", "localhost"),
            user=os.getenv("MYSQL_USER", "root"),
            password=os.getenv("MYSQL_PASSWORD", ""),
            database=os.getenv("MYSQL_DATABASE", "shift_peaje"),
            port=int(os.getenv("MYSQL_PORT", "3306")),
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor
        )
    except Exception as e:
        print(f"[ERROR] Database connection failed: {e}")
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
    if model_name.startswith("google/") or model_name.startswith("meta-llama/"):
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
    """Factory function para crear nodos de agentes con modelo específico e inyección de RAG/Tenant."""
    def agent_node(state: SwarmState):
        agent_info = AGENTS[agent_id]
        # Asegurar que tid sea siempre string
        tid = str(tenant_id) if tenant_id is not None else "shift"
        tenant_context = TENANT_CONTEXTS.get(tid, TENANT_CONTEXTS["shift"])
        
        # INYECCIÓN DEL RAG (Synthetic Graph Injection)
        system_content = f"""
{SHIFT_LAB_CONTEXT}
{tenant_context}
{PUNTO_MEDIO_GLOBAL_RAG}

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
    """Endpoint especial para orquestar un debate estructurado a través del Debate Dashboard.
    
    NOTA: Este endpoint ahora soporta streaming para evitar timeouts en CPanel/Railway.
    El cliente debe usar NDJSON (Newline Delimited JSON) para recibir actualizaciones en tiempo real.
    """
    
    async def debate_generator():
        """Generador asíncrono que produce eventos de streaming del debate."""
        try:
            agent_a_id = request.agent_a_id
            agent_b_id = request.agent_b_id
            
            # In case the frontend passes the display name like 'Roberto - Finance' instead of 'roberto'
            # we'll map it to the first word/token lowercased avoiding special chars
            def unify_agent_id(aid: str) -> str:
                val = aid.split(" ")[0].lower().strip("-_.")
                # Map special cases if needed (e.g. maria vs maría inside dict)
                val = val.replace("í", "i").replace("á", "a").replace("ó", "o")
                return val

            a_id = unify_agent_id(agent_a_id)
            b_id = unify_agent_id(agent_b_id)
            
            # Enforce PRO model for Debate 
            # Fallback to Opus 4.6 if the model provided is somehow not a PRO model
            pro_models = ["Gemini 3.1 Pro", "Claude Opus 4.6", "Moonshot Kimi K2.5"]
            safe_model = str(request.model) if request.model in pro_models else "Claude Opus 4.6"

            # Validate agents
            if a_id not in AGENTS or b_id not in AGENTS:
                yield json.dumps({"error": f"Agente seleccionado no existe: {a_id} o {b_id}"}) + "\n"
                return
                
            print(f"[DEBATE STREAM] Iniciando Arena: {a_id} vs {b_id} sobre '{request.topic[:30]}...' con modelo PRO: {safe_model}")

            # Helper to extract content safely
            def get_message_content(messages_list: List[Any]) -> str:
                if not messages_list: return ""
                last_msg = messages_list[-1]
                return str(last_msg.content) if hasattr(last_msg, 'content') else str(last_msg)

            # Transcript history
            transcript: List[Dict[str, Any]] = []
            
            # Tema inicial
            current_context = f"TEMA DE DEBATE: {request.topic}\nOBJETIVO ESPERADO: {request.expected_output}"

            # Enviar evento de inicio
            yield json.dumps({
                "type": "start",
                "agent_a": AGENTS[a_id]["name"],
                "agent_b": AGENTS[b_id]["name"],
                "turns": request.turns
            }) + "\n"

            # Loop de debate (X turnos)
            for turn in range(request.turns):
                print(f"[DEBATE STREAM] Ejecutando Turno {turn + 1}/{request.turns}")
                
                # --- TURNO DEL AGENTE A ---
                yield json.dumps({
                    "type": "turn_start",
                    "turn": turn + 1,
                    "agent": AGENTS[a_id]["name"],
                    "side": "A"
                }) + "\n"
                
                # Preparamos el contexto para A
                messages_a = [HumanMessage(content=current_context)]
                if request.soul_a:
                    messages_a.insert(0, SystemMessage(content=f"INYECCIÓN DE ALMA (SOUL) PARA TI:\n{request.soul_a}"))
                
                node_a = create_agent_node_with_model(a_id, safe_model, str(request.tenant_id))
                state_a: SwarmState = {"messages": messages_a, "context": "", "active_agent": a_id, "agent_outputs": {}}
                result_a = node_a(state_a)
                resp_a = get_message_content(result_a["messages"])
                
                transcript.append({
                    "agent": a_id,
                    "role": AGENTS[a_id]["name"],
                    "content": resp_a
                })
                
                # Enviar respuesta de A
                yield json.dumps({
                    "type": "turn_complete",
                    "turn": turn + 1,
                    "agent": AGENTS[a_id]["name"],
                    "side": "A",
                    "content": resp_a
                }) + "\n"
                
                # --- TURNO DEL AGENTE B ---
                yield json.dumps({
                    "type": "turn_start",
                    "turn": turn + 1,
                    "agent": AGENTS[b_id]["name"],
                    "side": "B"
                }) + "\n"
                
                # El Agente B responde a lo que dijo el Agente A sobre el tema central
                turn_b_context = f"{current_context}\n\nARGUMENTO DE TU CONTRAPARTE ({AGENTS[a_id]['name']}):\n{resp_a}\n\nRefuta o construye sobre esto para alcanzar el OBJETIVO."
                messages_b = [HumanMessage(content=turn_b_context)]
                if request.soul_b:
                    messages_b.insert(0, SystemMessage(content=f"INYECCIÓN DE ALMA (SOUL) PARA TI:\n{request.soul_b}"))
                    
                node_b = create_agent_node_with_model(b_id, safe_model, str(request.tenant_id))
                state_b: SwarmState = {"messages": messages_b, "context": "", "active_agent": b_id, "agent_outputs": {}}
                result_b = node_b(state_b)
                resp_b = get_message_content(result_b["messages"])
                
                transcript.append({
                    "agent": b_id,
                    "role": AGENTS[b_id]["name"],
                    "content": resp_b
                })
                
                # Enviar respuesta de B
                yield json.dumps({
                    "type": "turn_complete",
                    "turn": turn + 1,
                    "agent": AGENTS[b_id]["name"],
                    "side": "B",
                    "content": resp_b
                }) + "\n"
                
                # El próximo turno de A se basará en la respuesta de B
                current_context = f"{current_context}\n\nÚLTIMA RESPUESTA DE TU CONTRAPARTE ({AGENTS[b_id]['name']}):\n{resp_b}\n\nTu turno de responder para alcanzar el OBJETIVO."
                
            print("[DEBATE STREAM] Debate finalizado. Iniciando Síntesis del Juez.")
            
            # --- Síntesis Crítica (El Juez) ---
            yield json.dumps({
                "type": "judging",
                "message": "El Juez está sintetizando los argumentos..."
            }) + "\n"
            
            # Formatear el transcript para el juez
            transcript_text = "\n\n".join([f"--- [TURNO: {str(item['role']).upper()}] ---\n{item['content']}" for item in transcript])
            
            synthesis_llm = get_llm(safe_model)
            synthesis_prompt = f"""
{PUNTO_MEDIO_GLOBAL_RAG}

Eres el 'Juez Supremo de Arena' de Shifty Studio. Se acaba de llevar a cabo un encarnizado debate entre {AGENTS[a_id]['name']} y {AGENTS[b_id]['name']}.

TEMA DEL DEBATE: {request.topic}
OUTPUT ESPERADO POR EL USUARIO: {request.expected_output}

TRANSCRIPCIÓN COMPLETA DEL DEBATE:
{transcript_text}

Tu tarea es evaluar los argumentos presentados y generar EL OUTPUT FINAL directamente, cumpliendo exactamente con las expectativas del usuario.
1. Analiza con agudeza los puntos fuertes que cada especialista aportó.
2. Si hubo contradicciones, toma una postura firme justificando por qué.
3. El formato de tu respuesta DEBE ser el 'OUTPUT ESPERADO' que pidió el ejecutivo.
4. Redacta de forma magistral, consultora nivel McKinsey/BCG, entregando un plan, solución o respuesta accionable, lista para ejecutarse.
            """
            final_resp = synthesis_llm.invoke([SystemMessage(content=synthesis_prompt)])
            
            # Enviar resultado final
            yield json.dumps({
                "type": "complete",
                "content": final_resp.content,
                "transcript": transcript,
                "agent_active": "debate_judge",
                "debate_participants": [a_id, b_id]
            }) + "\n"
            
        except Exception as e:
            import traceback
            traceback.print_exc()
            yield json.dumps({
                "type": "error",
                "error": str(e)
            }) + "\n"

    # Retornar respuesta streaming con NDJSON
    return StreamingResponse(
        debate_generator(),
        media_type="application/x-ndjson",
        headers={
            "X-Accel-Buffering": "no",  # Deshabilitar buffering de nginx
            "Cache-Control": "no-cache",
        }
    )

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
    """Ingesta asíncrona hacia el Flywheel (El Peaje)"""
    try:
        print(f"[EL PEAJE] Processing: Tenant={request.tenantId}, Agent={request.agentId}")
        
        # Extracción Agéntica
        insight_data = await extract_insight_data_async(request.messages, request.response, request.tenantId)
        
        # Generate hashes for anonymization
        conversation_text = json.dumps([{"role": m.role, "content": m.content} for m in request.messages])
        anonymized_hash = hashlib.sha256(f"{request.tenantId}:{request.sessionId}:{datetime.now().isoformat()}".encode()).hexdigest()
        conversation_hash = hashlib.sha256(conversation_text.encode()).hexdigest()
        
        # Get database connection
        conn = get_db_connection()
        
        if conn:
            try:
                with conn.cursor() as cursor:
                    # Insert insight into peaje_insights
                    sql = """
                        INSERT INTO peaje_insights 
                        (tenant_id, session_id, agent_id, insight_text, category, sentiment, 
                         confidence_score, anonymized_hash, raw_conversation_hash)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """
                    cursor.execute(sql, (
                        request.tenantId,
                        request.sessionId,
                        request.agentId,
                        insight_data["insight_text"],
                        insight_data["category"],
                        insight_data["sentiment"],
                        0.75,  # confidence score placeholder
                        anonymized_hash,
                        conversation_hash
                    ))
                    
                    # Update or insert session tracking
                    session_sql = """
                        INSERT INTO peaje_sessions 
                        (tenant_id, session_id, message_count, agents_used, source)
                        VALUES (%s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                        message_count = message_count + %s,
                        agents_used = JSON_MERGE_PATCH(agents_used, %s)
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
                    
                    conn.commit()
                    insight_id = cursor.lastrowid
                    
                print(f"[EL PEAJE] ✓ Insight saved to database, ID: {insight_id}")
                
                return {
                    "status": "ingested",
                    "tenant": request.tenantId,
                    "insight_id": insight_id,
                    "category": insight_data["category"],
                    "sentiment": insight_data["sentiment"],
                    "timestamp": datetime.now().isoformat()
                }
                
            except Exception as db_error:
                conn.rollback()
                print(f"[EL PEAJE DB ERROR] {db_error}")
                # Return success anyway - don't break the chat flow
                return {
                    "status": "logged_only",
                    "tenant": request.tenantId,
                    "error": str(db_error),
                    "category": insight_data["category"],
                    "sentiment": insight_data["sentiment"]
                }
            finally:
                conn.close()
        else:
            # Database not available, just log
            print(f"[EL PEAJE] Database not available, logged only")
            return {
                "status": "logged_only",
                "tenant": request.tenantId,
                "category": insight_data["category"],
                "sentiment": insight_data["sentiment"],
                "note": "Database connection not available"
            }
            
    except Exception as e:
        # Don't fail the chat if Peaje ingestion fails
        print(f"[EL PEAJE ERROR] {e}")
        return {"status": "error", "message": str(e)}

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
        "agents_count": len(AGENTS),
        "agents": [info["name"] for info in AGENTS.values()]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
