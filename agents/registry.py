"""Agent Registry — Loads agent skills from YAML files and builds the AGENTS dictionary."""
import os
import yaml

SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")


def _load_skills() -> dict:
    """Load all agent skill YAML files from agents/skills/ directory."""
    agents = {}
    
    if not os.path.isdir(SKILLS_DIR):
        print(f"[REGISTRY] Warning: Skills directory not found: {SKILLS_DIR}")
        return agents
    
    for filename in sorted(os.listdir(SKILLS_DIR)):
        if not filename.endswith(".yaml"):
            continue
        
        filepath = os.path.join(SKILLS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            
            agent_id = filename.replace(".yaml", "")
            agents[agent_id] = {
                "name": data.get("name", agent_id.capitalize()),
                "skill": data.get("skill_prompt", ""),
                "keywords": data.get("keywords", []),
                "role": data.get("role", "Specialist"),
                "version": data.get("version", "2.1.0"),
                "pod": data.get("pod", 0),
                "pod_name": data.get("pod_name", ""),
            }
        except Exception as e:
            print(f"[REGISTRY] Error loading {filepath}: {e}")
    
    print(f"[REGISTRY] Loaded {len(agents)} agents from YAML skills")
    return agents


# Build AGENTS dict at import time (same as original behavior)
AGENTS = _load_skills()


def get_agent_info(agent_id: str) -> dict:
    """Get agent info by ID. Returns None if not found."""
    return AGENTS.get(agent_id)
