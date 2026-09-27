#!/usr/bin/env python3
"""
Database connection diagnostic script.
Run: python test_db_connection.py
"""

import os
import sys
import asyncio
from urllib.parse import urlparse

print("\n" + "="*60)
print("DATABASE CONNECTION DIAGNOSTIC")
print("="*60)

# Load environment
from app.core.config import settings

print(f"\n1. Database URL loaded:")
print(f"   {settings.DATABASE_URL}")

# Parse the URL
try:
    parsed = urlparse(settings.DATABASE_URL)
    print(f"\n2. Connection Details:")
    print(f"   Scheme: {parsed.scheme}")
    print(f"   Host: {parsed.hostname}")
    print(f"   Port: {parsed.port}")
    print(f"   Database: {parsed.path.lstrip('/')}")
except Exception as e:
    print(f"   ❌ Failed to parse URL: {e}")
    sys.exit(1)

# Test DNS resolution
print(f"\n3. Testing DNS resolution for {parsed.hostname}...")
try:
    import socket
    ip = socket.gethostbyname(parsed.hostname)
    print(f"   ✅ Resolved to: {ip}")
except socket.gaierror as e:
    print(f"   ❌ DNS Resolution Failed: {e}")
    print(f"   Possible solutions:")
    print(f"   - Check your internet connection")
    print(f"   - Try pinging the host: ping {parsed.hostname}")
    print(f"   - Check if Supabase is accessible: https://status.supabase.com")
    print(f"   - Verify DATABASE_URL is correct in .env")
    sys.exit(1)

# Test TCP connection
print(f"\n4. Testing TCP connection to {parsed.hostname}:{parsed.port}...")
try:
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    result = sock.connect_ex((parsed.hostname, parsed.port))
    sock.close()
    
    if result == 0:
        print(f"   ✅ TCP connection successful")
    else:
        print(f"   ❌ TCP connection failed (port {parsed.port} unreachable)")
        sys.exit(1)
except Exception as e:
    print(f"   ❌ Connection test failed: {e}")
    sys.exit(1)

# Test SQLAlchemy connection
print(f"\n5. Testing SQLAlchemy async connection...")
try:
    from app.db.database import async_session_maker
    
    async def test_connection():
        try:
            async with async_session_maker() as session:
                result = await session.execute(
                    "SELECT 1 as connection_test"
                )
                row = result.fetchone()
                if row:
                    print(f"   ✅ SQLAlchemy connection successful")
                    return True
        except Exception as e:
            print(f"   ❌ SQLAlchemy connection failed: {e}")
            return False
    
    success = asyncio.run(test_connection())
    if not success:
        sys.exit(1)
        
except Exception as e:
    print(f"   ❌ Error: {e}")
    sys.exit(1)

print(f"\n6. All tests passed! ✅")
print("="*60 + "\n")
