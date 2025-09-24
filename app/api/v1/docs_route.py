"""
Serve documentation as part of the main API
"""
from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path
import os

router = APIRouter(prefix="/docs-site", tags=["documentation"])

# Path to built documentation
DOCS_PATH = Path("site")

@router.get("/")
async def serve_docs_home():
    """Serve documentation homepage"""
    index_file = DOCS_PATH / "index.html"
    if index_file.exists():
        return FileResponse(index_file, media_type="text/html")
    else:
        return HTMLResponse("""
        <html>
            <head>
                <title>Documentation</title>
                <style>
                    body { 
                        font-family: Arial, sans-serif; 
                        text-align: center; 
                        padding: 50px;
                    }
                    .container {
                        max-width: 600px;
                        margin: 0 auto;
                    }
                    code {
                        background: #f4f4f4;
                        padding: 10px;
                        border-radius: 5px;
                        display: block;
                        margin: 20px 0;
                    }
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>📚 תיעוד המערכת</h1>
                    <p>התיעוד עדיין לא נבנה. להפעלה:</p>
                    <code>mkdocs build</code>
                    <p>או בקר ב-<a href="/docs">API Documentation</a></p>
                </div>
            </body>
        </html>
        """)

@router.get("/{file_path:path}")
async def serve_docs_file(file_path: str):
    """Serve documentation static files"""
    # Sanitize and validate the path to prevent directory traversal
    try:
        # Resolve the full path
        requested_file = (DOCS_PATH / file_path).resolve()
        
        # CRITICAL: Check that the resolved path is within DOCS_PATH
        # This prevents directory traversal attacks like ../../etc/passwd
        if not str(requested_file).startswith(str(DOCS_PATH.resolve())):
            return HTMLResponse("Access denied", status_code=403)
        
        # Serve the file if it exists
        if requested_file.exists() and requested_file.is_file():
            return FileResponse(requested_file)
        
        # Try with .html extension
        html_file = (DOCS_PATH / f"{file_path}.html").resolve()
        if str(html_file).startswith(str(DOCS_PATH.resolve())) and html_file.exists():
            return FileResponse(html_file, media_type="text/html")
            
    except Exception:
        # Any path resolution errors = 404
        pass
    
    # Return 404 for anything else
    return HTMLResponse("File not found", status_code=404)