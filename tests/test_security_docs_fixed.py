"""
Fixed security tests for documentation serving
Properly handles httpx.InvalidURL exceptions for null bytes
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
        try:
            response = client.get(f"/docs-site/{path}")
            
            # Should return 403 Forbidden or 404 Not Found
            assert response.status_code in [403, 404], \
                f"Path traversal not blocked for: {path}"
            
            # Should NOT contain system file contents
            assert "/bin/bash" not in response.text, \
                f"System file exposed for path: {path}"
            assert "root:" not in response.text, \
                f"Password file exposed for path: {path}"
        except httpx.InvalidURL:
            # This is also acceptable - the client blocks invalid URLs
            pass

def test_null_byte_injection_comprehensive():
    """Comprehensive test for null byte injection attacks"""
    from app.main import app
    
    client = TestClient(app)
    
    # Different null byte attack patterns
    test_cases = [
        # URL encoded null bytes
        ("../../../../etc/passwd%00.html", "url_encoded", False),
        ("../../../etc/passwd%00", "url_encoded", False),
        ("/etc/passwd%00.jpg", "url_encoded", False),
        
        # Raw null bytes (will trigger InvalidURL)
        ("../../../../etc/passwd\x00.html", "raw_null", True),
        ("/etc/passwd\x00", "raw_null", True),
        ("file.html\x00.jpg", "raw_null", True),
    ]
    
    for path, attack_type, expect_exception in test_cases:
        if expect_exception:
            # These should raise InvalidURL before reaching the app
            with pytest.raises(httpx.InvalidURL):
                client.get(f"/docs-site/{path}")
        else:
            # These should be handled by the app
            response = client.get(f"/docs-site/{path}")
            
            # Should be blocked
            assert response.status_code in [403, 404], \
                f"Null byte attack not blocked: {attack_type} - {repr(path)}"
            
            # Should not expose system files
            assert "root:" not in response.text
            assert "/bin/bash" not in response.text

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
        "faq",
        "faq.html",
    ]
    
    # Only test if docs are built
    if Path("site/index.html").exists():
        for path in valid_paths:
            response = client.get(f"/docs-site/{path}")
            # Should return 200 or 404 (if specific file doesn't exist)
            # but never 403
            assert response.status_code != 403, \
                f"Valid path blocked: {path}"

def test_special_characters_in_paths():
    """Test handling of various special characters"""
    from app.main import app
    
    client = TestClient(app)
    
    special_paths = [
        "../etc/passwd",  # Basic traversal
        "..%2F..%2Fetc%2Fpasswd",  # URL encoded slashes
        "..%252F..%252Fetc%252Fpasswd",  # Double encoded
        "..%c0%af..%c0%afetc%c0%afpasswd",  # UTF-8 encoding
        "..%25c0%25af..%25c0%25afetc",  # Mixed encoding
    ]
    
    for path in special_paths:
        response = client.get(f"/docs-site/{path}")
        assert response.status_code in [403, 404], \
            f"Special character attack not blocked: {path}"
        assert "root:" not in response.text

if __name__ == "__main__":
    # Run all tests
    print("🧪 Running security tests...")
    
    test_directory_traversal_protection()
    print("✅ Directory traversal tests passed")
    
    test_null_byte_injection_comprehensive()
    print("✅ Null byte injection tests passed")
    
    test_valid_documentation_paths()
    print("✅ Valid path tests passed")
    
    test_special_characters_in_paths()
    print("✅ Special character tests passed")
    
    print("\n🎉 All security tests passed!")