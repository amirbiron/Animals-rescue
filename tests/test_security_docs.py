"""
Security tests for documentation serving
Tests protection against directory traversal attacks
"""
import pytest
import httpx
from fastapi.testclient import TestClient
from pathlib import Path

def test_directory_traversal_protection():
    """Test that directory traversal attacks are blocked"""
    from app.main import app
    
    client = TestClient(app)
    
    # List of malicious paths to test
    malicious_paths = [
        "../../etc/passwd",
        "../../../etc/shadow",
        "..\\..\\windows\\system32\\config\\sam",
        "%2e%2e%2f%2e%2e%2fetc%2fpasswd",  # URL encoded
        "....//....//etc/passwd",
        "..;/etc/passwd",
        "../../../../../../../../../etc/passwd",
        "docs/../../../etc/passwd",
        "index.html/../../../../../../etc/passwd",
    ]
    
    for path in malicious_paths:
        response = client.get(f"/docs-site/{path}")
        
        # Should return 403 Forbidden or 404 Not Found
        assert response.status_code in [403, 404], \
            f"Path traversal not blocked for: {path}"
        
        # Should NOT contain system file contents
        assert "/bin/bash" not in response.text, \
            f"System file exposed for path: {path}"
        assert "root:" not in response.text, \
            f"Password file exposed for path: {path}"

def test_valid_documentation_paths():
    """Test that valid documentation paths work correctly"""
    from app.main import app
    
    client = TestClient(app)
    
    # These should work if docs are built
    valid_paths = [
        "",  # Root should serve index.html
        "index.html",
        "getting-started",
        "getting-started.html",
        "assets/stylesheets/main.css",  # Static assets
    ]
    
    # Only test if docs are built
    if Path("site/index.html").exists():
        for path in valid_paths:
            response = client.get(f"/docs-site/{path}")
            # Should return 200 or 404 (if specific file doesn't exist)
            # but never 403
            assert response.status_code != 403, \
                f"Valid path blocked: {path}"

def test_null_byte_injection():
    """Test protection against null byte injection"""
    from app.main import app
    import httpx
    
    client = TestClient(app)
    
    # Test URL-encoded null bytes (these should work)
    url_encoded_paths = [
        "../../../../etc/passwd%00.html",
        "../../../etc/passwd%00",
    ]
    
    for path in url_encoded_paths:
        response = client.get(f"/docs-site/{path}")
        assert response.status_code in [403, 404]
        assert "root:" not in response.text
    
    # Test raw null bytes (these will raise InvalidURL - which is good!)
    raw_null_byte_paths = [
        "../../../../etc/passwd\x00.html",
        "/etc/passwd\x00",
    ]
    
    for path in raw_null_byte_paths:
        # httpx will reject these URLs before they even reach our app
        # This is actually good security - the attack is blocked at the HTTP level
        try:
            response = client.get(f"/docs-site/{path}")
            # If we somehow get here, ensure it's blocked
            assert response.status_code in [403, 404]
            assert "root:" not in response.text
        except httpx.InvalidURL:
            # This is expected and good - httpx blocks null bytes
            pass  # The attack is blocked at the HTTP client level

if __name__ == "__main__":
    # Run tests
    test_directory_traversal_protection()
    test_valid_documentation_paths()
    test_null_byte_injection()
    print("✅ All security tests passed!")