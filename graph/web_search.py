"""Graph Web Search & Attachments — Perplexity search and file processing."""
from typing import List
from langchain_core.messages import HumanMessage
from config.models import get_llm
from graph.state import Attachment


async def perform_web_search(query: str) -> str:
    """
    Realiza una búsqueda web usando Perplexity Sonar via OpenRouter.
    Retorna los resultados de la búsqueda formateados como texto.
    """
    try:
        print(f"[WEB SEARCH] Query: {query[:100]}...")
        
        # Usar Perplexity Sonar para la búsqueda
        search_llm = get_llm("perplexity/sonar")
        
        search_prompt = f"""Busca información actualizada y precisa sobre: {query}

Proporciona una respuesta completa basada en fuentes confiables de internet.
Incluye datos relevantes, estadísticas recientes si aplica, y fuentes cuando sea posible.
Responde en el mismo idioma de la pregunta."""
        
        response = await search_llm.ainvoke([HumanMessage(content=search_prompt)])
        search_result = response.content if hasattr(response, 'content') else str(response)
        
        print(f"[WEB SEARCH] ✓ Results received: {len(search_result)} chars")
        return search_result
        
    except Exception as e:
        print(f"[WEB SEARCH ERROR] {e}")
        return f"[Error en búsqueda web: {str(e)}]"


def process_attachments(attachments: List[Attachment]) -> dict:
    """
    Process attached files and extract their content for the AI context.
    Supports: PDF, DOCX, TXT, CSV, JSON, MD files + images (JPEG, PNG, WebP, GIF).
    
    Returns:
        dict with:
          - "text_context": str  (extracted text from documents, injected into system prompt)
          - "images": list       (image data for multimodal LLM messages)
    """
    result = {"text_context": "", "images": []}
    
    if not attachments:
        return result
    
    import base64
    from io import BytesIO
    
    IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/jpg"}
    
    text_parts = []
    
    for att in attachments:
        try:
            # ── IMAGE ATTACHMENTS → multimodal ──
            if att.type in IMAGE_TYPES:
                result["images"].append({
                    "mime_type": att.type,
                    "base64": att.content,  # already base64 from frontend
                    "name": att.name,
                })
                print(f"[ATTACHMENT] Image queued for vision: {att.name} ({att.type})")
                continue
            
            # ── DOCUMENT ATTACHMENTS → text extraction ──
            file_content = base64.b64decode(att.content)
            file_text = ""
            
            if att.type == "application/pdf":
                try:
                    import pypdf
                    pdf_reader = pypdf.PdfReader(BytesIO(file_content))
                    for page in pdf_reader.pages:
                        file_text += page.extract_text() + "\n"
                except ImportError:
                    file_text = "[Error: pypdf not installed, cannot extract PDF content]"
                except Exception as e:
                    file_text = f"[Error extracting PDF: {str(e)}]"
                    
            elif att.type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                try:
                    import docx
                    doc = docx.Document(BytesIO(file_content))
                    for para in doc.paragraphs:
                        file_text += para.text + "\n"
                except ImportError:
                    file_text = "[Error: python-docx not installed, cannot extract DOCX content]"
                except Exception as e:
                    file_text = f"[Error extracting DOCX: {str(e)}]"
                    
            elif att.type in ["text/plain", "text/csv", "text/markdown", "application/json"]:
                file_text = file_content.decode('utf-8', errors='replace')
                
            else:
                file_text = "[Tipo de archivo no soportado para extracción de texto]"
            
            # Truncate if too long (max ~4000 chars per file)
            if len(file_text) > 4000:
                file_text = file_text[:4000] + "\n...[Contenido truncado por longitud]"
            
            text_parts.append(f"\n## {att.name}\n```\n{file_text}\n```\n")
            print(f"[ATTACHMENT] Processed {att.name}: {len(file_text)} chars")
            
        except Exception as e:
            print(f"[ATTACHMENT ERROR] Failed to process {att.name}: {e}")
            text_parts.append(f"\n## {att.name}\n[Error al procesar archivo: {str(e)}]\n")
    
    if text_parts:
        result["text_context"] = "\n\n[DOCUMENTOS ADJUNTOS]:\n" + "".join(text_parts)
        result["text_context"] += "\nINSTRUCCIÓN: Analiza los documentos adjuntos anteriores y úsalos como contexto para tu respuesta."
    
    if result["images"]:
        print(f"[ATTACHMENT] {len(result['images'])} image(s) ready for multimodal vision")
    
    return result
