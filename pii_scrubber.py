"""
═══════════════════════════════════════════════════════════════
PII SCRUBBER v1.0 — Shifty Lab 2.0
Capa determinística de sanitización post-LLM.

El LLM extractor es probabilístico. Esta capa es DETERMINÍSTICA.
Funciona como segunda línea de defensa: si el LLM falla en anonimizar,
el scrubber atrapa lo que se escapó antes de que toque la base de datos.

Diseñado para contexto LATAM (ES/PT):
- Nombres comunes hispanos/brasileños
- Formatos fiscales regionales (RUT, CUIL, RFC, CNPJ, CPF)
- Monedas locales (CRC, COP, MXN, BRL, ARS, PEN, CLP)
- Ciudades/países de la región
═══════════════════════════════════════════════════════════════
"""

import re
import json
from typing import Dict, Tuple

# ═══════════════════════════════════════════════════════════════
# REGEX PATTERNS — Organizados por tipo de PII
# ═══════════════════════════════════════════════════════════════

# Email addresses
EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)

# Phone numbers (international + LATAM formats)
PHONE_PATTERN = re.compile(
    r'(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b'
)

# URLs and domains
URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+|www\.[^\s<>"{}|\\^`\[\]]+'
)
DOMAIN_PATTERN = re.compile(
    r'\b[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.(com|net|org|io|co|ai|app|dev|tech|lat|cr|mx|co|ar|br|cl|pe|ec)\b',
    re.IGNORECASE
)

# Exact monetary amounts (USD, EUR, local currencies)
MONEY_PATTERN = re.compile(
    r'(?:USD|EUR|CRC|COP|MXN|BRL|ARS|PEN|CLP|₡|R\$|S/\.?)?\s*\$?\s*\d{1,3}(?:[,.\s]\d{3})*(?:\.\d{1,2})?\s*(?:USD|EUR|CRC|COP|MXN|BRL|ARS|PEN|CLP|millones|millions|mil|k|M|B)?\b',
    re.IGNORECASE
)

# Percentages with specific values (keep generic ones like "un 20%" but scrub "exactamente 47.3%")
SPECIFIC_PERCENTAGE_PATTERN = re.compile(
    r'\b\d{1,2}\.\d+\s*%'
)

# LATAM fiscal IDs
RUT_PATTERN = re.compile(r'\b\d{1,2}\.\d{3}\.\d{3}[-]?[0-9kK]\b')  # Chile
CUIL_PATTERN = re.compile(r'\b\d{2}-\d{8}-\d{1}\b')  # Argentina
RFC_PATTERN = re.compile(r'\b[A-Z&Ñ]{3,4}\d{6}[A-Z0-9]{3}\b')  # México
CPF_PATTERN = re.compile(r'\b\d{3}\.\d{3}\.\d{3}-\d{2}\b')  # Brasil
CNPJ_PATTERN = re.compile(r'\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b')  # Brasil corporate
CEDULA_CR_PATTERN = re.compile(r'\b[1-9]-?\d{4}-?\d{4}\b')  # Costa Rica

# IP addresses
IP_PATTERN = re.compile(
    r'\b(?:\d{1,3}\.){3}\d{1,3}\b'
)

# Credit card patterns (basic)
CC_PATTERN = re.compile(
    r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
)

# Dates with specific format that could identify events
SPECIFIC_DATE_PATTERN = re.compile(
    r'\b\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}\b'
)

# ═══════════════════════════════════════════════════════════════
# NAMED ENTITY PATTERNS — Nombres propios LATAM
# ═══════════════════════════════════════════════════════════════

# Top 200 nombres hispanos/brasileños más comunes (first names)
LATAM_FIRST_NAMES = {
    # Masculinos ES
    "josé", "juan", "carlos", "luis", "miguel", "francisco", "antonio", "pedro",
    "rafael", "alejandro", "fernando", "ricardo", "diego", "andrés", "javier",
    "gabriel", "sergio", "pablo", "daniel", "jorge", "mario", "roberto", "eduardo",
    "enrique", "martín", "álvaro", "raúl", "héctor", "oscar", "arturo", "manuel",
    "alberto", "ramón", "gustavo", "hugo", "iván", "guillermo", "adrián", "felipe",
    "santiago", "sebastián", "mateo", "nicolás", "tomás", "emilio", "ignacio",
    "joaquín", "rodrigo", "gonzalo", "camilo", "esteban", "fabián", "cristian",
    # Femeninos ES
    "maría", "ana", "carmen", "laura", "lucía", "patricia", "sofía", "fernanda",
    "gabriela", "valentina", "daniela", "mariana", "andrea", "paula", "carolina",
    "catalina", "natalia", "isabella", "alejandra", "victoria", "claudia", "elena",
    "silvia", "marta", "rosa", "teresa", "pilar", "lorena", "mónica", "diana",
    "susana", "verónica", "jessica", "paola", "adriana", "marcela", "mercedes",
    "cecilia", "alicia", "beatriz", "cristina", "estela", "gladys", "graciela",
    "inés", "irene", "julia", "leticia", "lilia", "liliana", "marisol", "miriam",
    # Brasileños
    "joão", "pedro", "lucas", "matheus", "gabriel", "rafael", "guilherme",
    "felipe", "brunno", "thiago", "leonardo", "gustavo", "henrique", "vinicius",
    "maria", "ana", "juliana", "fernanda", "camila", "bruna", "larissa",
    "amanda", "letícia", "carolina", "raquel", "tatiana", "priscila",
}

# Apellidos LATAM comunes (para detección de nombre completo)
LATAM_SURNAMES = {
    "garcía", "rodríguez", "martínez", "lópez", "hernández", "gonzález",
    "pérez", "sánchez", "ramírez", "torres", "flores", "rivera", "gómez",
    "díaz", "reyes", "morales", "jiménez", "ruiz", "álvarez", "mendoza",
    "medina", "vargas", "castillo", "romero", "herrera", "guzmán", "muñoz",
    "rojas", "guerrero", "ortiz", "silva", "ramos", "delgado", "ríos",
    "contreras", "fuentes", "espinoza", "valenzuela", "salazar", "aguilar",
    "vega", "sandoval", "campos", "núñez", "domínguez", "navarro", "molina",
    "leon", "mora", "bravo", "figueroa", "acosta", "cabrera", "soto",
    "pereira", "castro", "costa", "santos", "oliveira", "souza", "lima",
    "almeida", "ferreira", "ribeiro", "carvalho", "gomes", "barbosa",
    "araujo", "nascimento", "vieira", "monteiro", "cardoso", "correia",
    # Centroamérica / Costa Rica comunes
    "arias", "calderón", "salas", "chacón", "monge", "villalobos", "barrantes",
    "solano", "araya", "ureña", "segura", "quesada", "zúñiga", "cordero",
}

# Ciudades y ubicaciones específicas LATAM
LATAM_CITIES = {
    # Capitales y ciudades importantes
    "san josé", "ciudad de méxico", "cdmx", "bogotá", "lima", "santiago",
    "buenos aires", "são paulo", "río de janeiro", "montevideo", "quito",
    "guayaquil", "caracas", "panamá", "tegucigalpa", "san salvador",
    "guatemala", "managua", "santo domingo", "la habana", "asunción",
    "medellín", "cali", "barranquilla", "cartagena", "monterrey",
    "guadalajara", "puebla", "cancún", "córdoba", "rosario", "mendoza",
    "valparaíso", "concepción", "arequipa", "cusco", "curitiba",
    "belo horizonte", "porto alegre", "recife", "fortaleza", "salvador",
    "brasilia", "campinas", "manaus", "belém", "goiânia",
    # Zonas/barrios conocidos
    "escazú", "santa ana", "heredia", "alajuela", "cartago", "liberia",
    "polanco", "condesa", "roma", "chapinero", "miraflores", "providencia",
    "palermo", "recoleta", "ipanema", "copacabana", "leblon",
}

# Empresas y marcas conocidas LATAM (para scrubbing adicional)
KNOWN_COMPANIES = {
    "mercado libre", "rappi", "nubank", "kavak", "clip", "bitso",
    "globant", "despegar", "cornershop", "platzi", "loft", "creditas",
    "walmart", "amazon", "google", "microsoft", "apple", "meta", "facebook",
    "coca-cola", "pepsi", "nestlé", "unilever", "procter", "gamble",
    "samsung", "huawei", "tesla", "uber", "didi", "spotify", "netflix",
}

# Regiones macro para reemplazo
REGION_MAP = {
    # Costa Rica
    "san josé": "centroamérica", "escazú": "centroamérica", "heredia": "centroamérica",
    "alajuela": "centroamérica", "cartago": "centroamérica",
    # México  
    "ciudad de méxico": "norteamérica latina", "cdmx": "norteamérica latina",
    "monterrey": "norteamérica latina", "guadalajara": "norteamérica latina",
    # Colombia
    "bogotá": "andina", "medellín": "andina", "cali": "andina",
    "barranquilla": "caribe", "cartagena": "caribe",
    # Brasil
    "são paulo": "brasil", "río de janeiro": "brasil", "brasilia": "brasil",
    # Cono Sur
    "buenos aires": "cono sur", "santiago": "cono sur", "montevideo": "cono sur",
    # Perú/Ecuador
    "lima": "andina", "quito": "andina", "guayaquil": "andina",
}


# ═══════════════════════════════════════════════════════════════
# CATEGORY VALIDATION — Mapeo de categorías del LLM a taxonomy keys
# ═══════════════════════════════════════════════════════════════

# Las 4 categorías canónicas del taxonomy
VALID_CATEGORIES = {
    "riesgos_ciegos",
    "patrones_sectoriales",
    "gaps_productividad",
    "vectores_aceleracion",
}

# Sub-categorías válidas
VALID_SUB_CATEGORIES = {
    "riesgo_talento", "riesgo_tecnologico", "riesgo_regulatorio", "riesgo_mercado",
    "patron_retail", "patron_fintech", "patron_salud", "patron_tech", "patron_media",
    "gap_comunicacion", "gap_contexto", "gap_herramientas", "gap_datos",
    "vector_automatizacion", "vector_expansion", "vector_alianzas", "vector_conocimiento",
}

# Mapeo fuzzy: lo que el LLM puede decir → lo que nosotros necesitamos
CATEGORY_FUZZY_MAP = {
    # Riesgos Ciegos
    "riesgos ciegos detectados": "riesgos_ciegos",
    "riesgos ciegos": "riesgos_ciegos",
    "riesgo ciego": "riesgos_ciegos",
    "blind risk": "riesgos_ciegos",
    "blind risks": "riesgos_ciegos",
    "riesgo": "riesgos_ciegos",
    "riesgos": "riesgos_ciegos",
    "amenaza": "riesgos_ciegos",
    "vulnerabilidad": "riesgos_ciegos",
    
    # Patrones Sectoriales
    "patrones de decisión sectorial": "patrones_sectoriales",
    "patrones sectoriales": "patrones_sectoriales",
    "patrón sectorial": "patrones_sectoriales",
    "sector pattern": "patrones_sectoriales",
    "sector patterns": "patrones_sectoriales",
    "patrón": "patrones_sectoriales",
    "patrones": "patrones_sectoriales",
    "tendencia": "patrones_sectoriales",
    "tendencia sectorial": "patrones_sectoriales",
    
    # Gaps de Productividad
    "gaps de productividad institucional": "gaps_productividad",
    "gaps de productividad": "gaps_productividad",
    "gap de productividad": "gaps_productividad",
    "productivity gap": "gaps_productividad",
    "productivity gaps": "gaps_productividad",
    "gap": "gaps_productividad",
    "gaps": "gaps_productividad",
    "ineficiencia": "gaps_productividad",
    "fricción": "gaps_productividad",
    "fragmentación": "gaps_productividad",
    
    # Vectores de Aceleración
    "vectores de aceleración ocultos": "vectores_aceleracion",
    "vectores de aceleración": "vectores_aceleracion",
    "vector de aceleración": "vectores_aceleracion",
    "acceleration vector": "vectores_aceleracion",
    "acceleration vectors": "vectores_aceleracion",
    "vector": "vectores_aceleracion",
    "vectores": "vectores_aceleracion",
    "oportunidad": "vectores_aceleracion",
    "aceleración": "vectores_aceleracion",
    "palanca": "vectores_aceleracion",
}

# Industry vertical detection keywords
INDUSTRY_KEYWORDS = {
    "retail_consumo": ["retail", "tienda", "consumo", "fmcg", "supermercado", "e-commerce", "ecommerce", "punto de venta"],
    "media_comunicacion": ["agencia", "publicidad", "media", "comunicación", "marketing", "pauta", "creativo", "campaña"],
    "fintech_banca": ["banco", "fintech", "crédito", "préstamo", "seguro", "financier", "inversión", "banca"],
    "tech_saas": ["software", "saas", "plataforma", "app", "tecnología", "startup", "api", "cloud"],
    "salud_pharma": ["salud", "hospital", "farmacéutic", "médic", "clínic", "pharma", "dispositivo médico"],
    "manufactura": ["fábrica", "manufactura", "producción", "cadena de suministro", "logística", "supply chain"],
    "educacion": ["educación", "universidad", "escuela", "edtech", "formación", "capacitación"],
    "inmobiliario": ["inmobiliari", "proptech", "construcción", "bienes raíces", "real estate"],
}


# ═══════════════════════════════════════════════════════════════
# CORE SCRUBBER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def scrub_pii(text: str) -> Tuple[str, Dict[str, int]]:
    """
    Scrub PII from text using deterministic regex patterns.
    Returns (scrubbed_text, pii_counts_by_type).
    
    This is the SECOND line of defense after the LLM extractor.
    It catches anything the LLM missed.
    """
    if not text:
        return text, {}
    
    pii_counts: Dict[str, int] = {}
    scrubbed = text
    
    # 1. Emails → [EMAIL_REDACTED]
    emails_found = EMAIL_PATTERN.findall(scrubbed)
    if emails_found:
        pii_counts["emails"] = len(emails_found)
        scrubbed = EMAIL_PATTERN.sub("[EMAIL_REDACTED]", scrubbed)
    
    # 2. URLs → [URL_REDACTED]
    urls_found = URL_PATTERN.findall(scrubbed)
    if urls_found:
        pii_counts["urls"] = len(urls_found)
        scrubbed = URL_PATTERN.sub("[URL_REDACTED]", scrubbed)
    
    # 3. Domains → [DOMAIN_REDACTED]
    domains_found = DOMAIN_PATTERN.findall(scrubbed)
    if domains_found:
        pii_counts["domains"] = len(domains_found)
        scrubbed = DOMAIN_PATTERN.sub("[DOMAIN_REDACTED]", scrubbed)
    
    # 4. Credit cards → [CC_REDACTED]
    cc_found = CC_PATTERN.findall(scrubbed)
    if cc_found:
        pii_counts["credit_cards"] = len(cc_found)
        scrubbed = CC_PATTERN.sub("[CC_REDACTED]", scrubbed)
    
    # 5. Fiscal IDs (LATAM)
    for name, pattern in [
        ("rut", RUT_PATTERN), ("cuil", CUIL_PATTERN), ("rfc", RFC_PATTERN),
        ("cpf", CPF_PATTERN), ("cnpj", CNPJ_PATTERN), ("cedula_cr", CEDULA_CR_PATTERN),
    ]:
        found = pattern.findall(scrubbed)
        if found:
            pii_counts[name] = len(found)
            scrubbed = pattern.sub("[FISCAL_ID_REDACTED]", scrubbed)
    
    # 6. IP addresses → [IP_REDACTED]
    ips_found = IP_PATTERN.findall(scrubbed)
    if ips_found:
        pii_counts["ips"] = len(ips_found)
        scrubbed = IP_PATTERN.sub("[IP_REDACTED]", scrubbed)
    
    # 7. Phone numbers → [PHONE_REDACTED]
    phones_found = PHONE_PATTERN.findall(scrubbed)
    if phones_found:
        pii_counts["phones"] = len(phones_found)
        scrubbed = PHONE_PATTERN.sub("[PHONE_REDACTED]", scrubbed)
    
    # 8. Monetary amounts → [MONTO_REDACTED] (replace with strategic generalization)
    money_found = MONEY_PATTERN.findall(scrubbed)
    if money_found:
        pii_counts["monetary_amounts"] = len(money_found)
        scrubbed = MONEY_PATTERN.sub("[MAGNITUD_FINANCIERA]", scrubbed)
    
    # 9. Specific dates → [FECHA_REDACTED]
    dates_found = SPECIFIC_DATE_PATTERN.findall(scrubbed)
    if dates_found:
        pii_counts["dates"] = len(dates_found)
        scrubbed = SPECIFIC_DATE_PATTERN.sub("[PERIODO_TEMPORAL]", scrubbed)
    
    # 10. Named entities — LATAM names (case-sensitive check)
    names_count = 0
    scrubbed = _scrub_named_entities(scrubbed, names_count_holder := {"count": 0})
    if names_count_holder["count"] > 0:
        pii_counts["names"] = names_count_holder["count"]
    
    # 11. Known companies
    companies_count = 0
    for company in KNOWN_COMPANIES:
        pattern = re.compile(re.escape(company), re.IGNORECASE)
        found = pattern.findall(scrubbed)
        if found:
            companies_count += len(found)
            scrubbed = pattern.sub("[EMPRESA_SECTOR]", scrubbed)
    if companies_count > 0:
        pii_counts["companies"] = companies_count
    
    # 12. City/location names → macro regions
    locations_count = 0
    for city, region in REGION_MAP.items():
        pattern = re.compile(re.escape(city), re.IGNORECASE)
        found = pattern.findall(scrubbed)
        if found:
            locations_count += len(found)
            scrubbed = pattern.sub(f"[{region.upper()}]", scrubbed)
    
    # Also scrub remaining LATAM cities not in REGION_MAP
    for city in LATAM_CITIES:
        if city not in REGION_MAP:
            pattern = re.compile(re.escape(city), re.IGNORECASE)
            found = pattern.findall(scrubbed)
            if found:
                locations_count += len(found)
                scrubbed = pattern.sub("[REGIÓN_LATAM]", scrubbed)
    
    if locations_count > 0:
        pii_counts["locations"] = locations_count
    
    return scrubbed, pii_counts


def _scrub_named_entities(text: str, count_holder: dict) -> str:
    """
    Scrub proper names from text.
    Uses a combination of known LATAM names + capitalization heuristics.
    """
    words = text.split()
    scrubbed_words = []
    i = 0
    
    while i < len(words):
        word = words[i]
        word_lower = word.lower().strip(".,;:!?\"'()[]{}—–-")
        
        # Check if word is a known first name (case-insensitive)
        if word_lower in LATAM_FIRST_NAMES:
            # Check if next word is a known surname (full name detection)
            if i + 1 < len(words):
                next_lower = words[i + 1].lower().strip(".,;:!?\"'()[]{}—–-")
                if next_lower in LATAM_SURNAMES:
                    # Full name detected — scrub both words
                    scrubbed_words.append("[EJECUTIVO]")
                    count_holder["count"] += 1
                    i += 2
                    continue
            
            # Standalone first name that's capitalized (likely a proper name reference)
            if word[0].isupper():
                scrubbed_words.append("[PERSONA]")
                count_holder["count"] += 1
                i += 1
                continue
        
        # Check capitalized word that's a known surname
        if word_lower in LATAM_SURNAMES and word[0].isupper():
            scrubbed_words.append("[PERSONA]")
            count_holder["count"] += 1
            i += 1
            continue
        
        scrubbed_words.append(word)
        i += 1
    
    return " ".join(scrubbed_words)


def validate_category(raw_category: str) -> Tuple[str, str, bool]:
    """
    Validate and normalize a category from the LLM extractor.
    Returns (validated_category_key, original_category, was_valid).
    """
    if not raw_category:
        return "vectores_aceleracion", "", False
    
    normalized = raw_category.strip().lower()
    
    # Direct match against valid keys
    if normalized in VALID_CATEGORIES:
        return normalized, raw_category, True
    
    # Check sub-categories and return parent
    if normalized in VALID_SUB_CATEGORIES:
        return normalized, raw_category, True
    
    # Fuzzy match
    if normalized in CATEGORY_FUZZY_MAP:
        return CATEGORY_FUZZY_MAP[normalized], raw_category, True
    
    # Partial match — check if any fuzzy key is contained in the raw category
    for fuzzy_key, valid_key in CATEGORY_FUZZY_MAP.items():
        if fuzzy_key in normalized or normalized in fuzzy_key:
            return valid_key, raw_category, True
    
    # Keyword-based fallback
    if any(kw in normalized for kw in ["riesgo", "ciego", "amenaza", "blind"]):
        return "riesgos_ciegos", raw_category, False
    if any(kw in normalized for kw in ["patrón", "patron", "sector", "tendencia"]):
        return "patrones_sectoriales", raw_category, False
    if any(kw in normalized for kw in ["gap", "productiv", "ineficien", "fricción", "fragment"]):
        return "gaps_productividad", raw_category, False
    if any(kw in normalized for kw in ["vector", "aceler", "oportunidad", "palanca"]):
        return "vectores_aceleracion", raw_category, False
    
    # Ultimate fallback
    return "vectores_aceleracion", raw_category, False


def detect_industry_vertical(text: str, tenant_industry: str = None) -> str:
    """
    Detect industry vertical from text content.
    Falls back to tenant's registered industry if no strong signal.
    """
    if not text:
        return tenant_industry or "general"
    
    text_lower = text.lower()
    scores: Dict[str, int] = {}
    
    for vertical, keywords in INDUSTRY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > 0:
            scores[vertical] = score
    
    if scores:
        best = max(scores, key=scores.get)
        return best
    
    return tenant_industry or "general"


def detect_sub_category(text: str, parent_category: str) -> str:
    """
    Attempt to detect a sub-category based on text content and parent category.
    Returns None if no strong sub-category signal.
    """
    if not text:
        return None
    
    text_lower = text.lower()
    
    sub_category_keywords = {
        "riesgos_ciegos": {
            "riesgo_talento": ["talento", "rotación", "fuga", "retención", "sucesión", "key person"],
            "riesgo_tecnologico": ["deuda técnica", "legacy", "vendor lock", "obsolescen"],
            "riesgo_regulatorio": ["regulación", "regulatorio", "normativa", "compliance", "ley"],
            "riesgo_mercado": ["competencia", "disrupción", "market", "consumidor"],
        },
        "patrones_sectoriales": {
            "patron_retail": ["retail", "tienda", "consumo", "e-commerce"],
            "patron_fintech": ["fintech", "banco", "financier"],
            "patron_salud": ["salud", "pharma", "médic"],
            "patron_tech": ["saas", "software", "tech", "startup"],
            "patron_media": ["agencia", "media", "publicidad", "comunicación"],
        },
        "gaps_productividad": {
            "gap_comunicacion": ["comunicación", "silo", "inter-área", "desconex"],
            "gap_contexto": ["contexto", "reset", "onboarding", "rotación"],
            "gap_herramientas": ["herramienta", "proceso", "manual", "tooling"],
            "gap_datos": ["dato", "métrica", "analytics", "dashboard"],
        },
        "vectores_aceleracion": {
            "vector_automatizacion": ["automatiz", "automat", "eficiencia", "proceso manual"],
            "vector_expansion": ["expansión", "mercado", "segmento", "canal"],
            "vector_alianzas": ["alianza", "partnership", "partner", "joint venture"],
            "vector_conocimiento": ["conocimiento", "expertise", "capacitación", "documentación"],
        },
    }
    
    if parent_category not in sub_category_keywords:
        return None
    
    best_sub = None
    best_score = 0
    
    for sub_key, keywords in sub_category_keywords[parent_category].items():
        score = sum(1 for kw in keywords if kw in text_lower)
        if score > best_score:
            best_score = score
            best_sub = sub_key
    
    return best_sub if best_score > 0 else None


def full_scrub_pipeline(
    insight_text: str,
    raw_category: str,
    tenant_industry: str = None,
    conversation_text: str = None,
) -> Dict:
    """
    Full PII scrubbing + category validation + industry detection pipeline.
    
    This is the main entry point for the PII scrubber.
    Called AFTER the LLM extractor, BEFORE database insertion.
    
    Returns:
        {
            "scrubbed_text": str,
            "validated_category": str,
            "original_category": str,
            "category_was_valid": bool,
            "sub_category": str | None,
            "industry_vertical": str,
            "pii_counts": dict,
            "total_pii_scrubbed": int,
            "pii_scrubbed": bool
        }
    """
    # Step 1: Scrub PII from insight text
    scrubbed_text, pii_counts = scrub_pii(insight_text)
    
    # Step 2: Validate category
    validated_category, original_category, category_was_valid = validate_category(raw_category)
    
    # Step 3: Detect industry vertical
    source_text = conversation_text or insight_text
    industry = detect_industry_vertical(source_text, tenant_industry)
    
    # Step 4: Detect sub-category
    sub_category = detect_sub_category(insight_text, validated_category)
    
    total_scrubbed = sum(pii_counts.values())
    
    return {
        "scrubbed_text": scrubbed_text,
        "validated_category": validated_category,
        "original_category": original_category,
        "category_was_valid": category_was_valid,
        "sub_category": sub_category,
        "industry_vertical": industry,
        "pii_counts": pii_counts,
        "total_pii_scrubbed": total_scrubbed,
        "pii_scrubbed": total_scrubbed > 0,
    }


def check_deduplication(conversation_hash: str, conn) -> bool:
    """
    Check if this conversation has already been processed.
    Returns True if it's a duplicate.
    """
    if not conn:
        return False
    
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) as cnt FROM peaje_extraction_log WHERE conversation_hash = %s AND created_at >= DATE_SUB(NOW(), INTERVAL 1 HOUR)",
                (conversation_hash,)
            )
            result = cursor.fetchone()
            return result and result.get("cnt", 0) > 0
    except Exception:
        return False
