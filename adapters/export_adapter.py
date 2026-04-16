"""Export Adapter — Document generation and serving endpoints."""
import os
from typing import List, Dict, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

# Storage configuration for generated documents
DOCUMENTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "generated_documents")
os.makedirs(DOCUMENTS_DIR, exist_ok=True)

export_router = APIRouter(tags=["export"])


class DocumentExportRequest(BaseModel):
    format: str = "DOCX"
    title: str
    content: str
    subtitle: Optional[str] = None
    author: str = "Shift AI"
    sections: Optional[List[Dict[str, str]]] = None


@export_router.post("/export/document")
async def export_document(req: DocumentExportRequest):
    fmt = req.format.upper()
    try:
        print(f"[EXPORT] Generating document ({fmt}): {req.title}")
        
        if fmt == "DOCX":
            from tools.document_tools import create_word_document
            result = create_word_document.func(
                title=req.title,
                content=req.content,
                subtitle=req.subtitle,
                author=req.author,
                sections=req.sections
            )
            return {"url": result}
            
        elif fmt == "PDF":
            from tools.extended_tools import generate_pdf_report
            result = generate_pdf_report.func(
                title=req.title,
                content=req.content,
                report_type="nodes_export",
                sections=req.sections,
                include_toc=True
            )
            return {"url": result}
            
        elif fmt == "PPTX":
            from tools.extended_tools import create_presentation
            slides_content = []
            if req.content and len(req.content) > 0:
                slides_content.append({"title": "Resumen Ejecutivo", "content": req.content})
            if req.sections:
                for sec in req.sections:
                    slides_content.append({
                        "title": sec.get("heading", ""),
                        "content": sec.get("content", "")
                    })
            result = create_presentation.func(
                title=req.title,
                subtitle=req.subtitle,
                slides_content=slides_content,
                template="corporate"
            )
            return {"url": result}
            
        elif fmt == "XLSX":
            import pandas as pd
            from tools.document_tools import DOCUMENTS_DIR as TOOLS_DOCS_DIR
            
            data = []
            if req.sections:
                for sec in req.sections:
                    data.append({
                        "Nodo/Especialista": sec.get("heading", ""),
                        "Análisis/Output": sec.get("content", "")
                    })
            else:
                data.append({"Resumen": req.content})
                
            df = pd.DataFrame(data)
            
            filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            file_path = os.path.join(DOCUMENTS_DIR, filename)
            
            df.to_excel(file_path, index=False)
            return {"url": f"/documents/{filename}"}
            
        else:
            raise HTTPException(status_code=400, detail=f"Format {fmt} not supported yet")

    except Exception as e:
        print(f"[EXPORT ERROR] {e}")
        raise HTTPException(status_code=500, detail=str(e))


@export_router.get("/documents/{filename}")
async def serve_document(filename: str):
    """
    Serve a generated document for download.
    Documents are stored in the generated_documents directory.
    Supports: DOCX, PDF, PPTX, PNG, TXT
    """
    # Security: Prevent directory traversal
    if ".." in filename or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    
    file_path = os.path.join(DOCUMENTS_DIR, filename)
    
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Determine content type based on extension
    content_type_map = {
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".pdf": "application/pdf",
        ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".png": "image/png",
        ".txt": "text/plain",
    }
    
    ext = os.path.splitext(filename)[1].lower()
    content_type = content_type_map.get(ext, "application/octet-stream")
    
    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=filename
    )
