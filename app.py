#!/usr/bin/env python3
"""
CrossLinked Entry Point
Launches the backend server and connects the frontend dashboard.
"""
import sys
from backend.server import run_backend

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8000
    run_backend(port=port)
