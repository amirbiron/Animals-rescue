"""
Secure static file serving for documentation
This is the recommended approach using FastAPI's StaticFiles
"""
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import os

def mount_documentation(app: FastAPI):
    """
    Mount documentation as static files - SECURE VERSION
    
    This uses FastAPI's StaticFiles which has built-in security:
    - Prevents directory traversal attacks
    - Validates all paths
    - Handles caching headers properly
    """
    DOCS_PATH = Path("site")
    
    if DOCS_PATH.exists() and DOCS_PATH.is_dir():
        # Mount the documentation with proper security
        app.mount(
            "/docs-site",
            StaticFiles(
                directory=str(DOCS_PATH),
                html=True,  # Serve index.html for directories
                check_dir=True  # IMPORTANT: Validate directory access
            ),
            name="documentation"
        )
        print("📚 Documentation mounted securely at /docs-site")
        return True
    else:
        print("⚠️  Documentation not found. Run 'mkdocs build' first.")
        return False

# Example usage in main.py:
# from app.api.v1.docs_static import mount_documentation
# mount_documentation(app)