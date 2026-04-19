#!/usr/bin/env python3
"""
Start the WCAG Accessibility Remediation Platform backend server.
"""
import uvicorn
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / 'backend'))

if __name__ == "__main__":
    print("Starting WCAG Accessibility Remediation Platform...")
    print("API Documentation: http://localhost:8000/docs")
    print("Health Check: http://localhost:8000/health")
    print("-" * 50)
    
    uvicorn.run(
        "backend.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )





