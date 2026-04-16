import os
from langchain_openai import ChatOpenAI

# OpenRouter Config - Model mapping (Matches frontend strings EXACTLY)
MODEL_MAP = {
    "Shifty 2.0 by Shift AI": "anthropic/claude-sonnet-4.6",
    "Claude Sonnet 4.6": "anthropic/claude-sonnet-4.6",
    "Gemini 3.1 Flash Lite": "google/gemini-3.1-flash-lite-preview",
    "DeepSeek V3.2": "deepseek/deepseek-v3.2",
    "Gemini 3.1 Pro": "google/gemini-3.1-pro-preview",
    "Claude Opus 4.6": "anthropic/claude-opus-4.6",
    "Moonshot Kimi K2.5": "moonshotai/kimi-k2.5",
    # Perplexity Sonar for web search
    "Perplexity Sonar": "perplexity/sonar",
    "Perplexity Sonar Pro": "perplexity/sonar-pro",
    "Perplexity Sonar Reasoning": "perplexity/sonar-reasoning",
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
