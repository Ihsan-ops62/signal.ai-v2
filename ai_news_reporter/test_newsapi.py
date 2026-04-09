#!/usr/bin/env python3
"""Quick test script to validate NewsAPI key"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
import httpx

# Load .env
config_dir = Path(__file__).parent
env_path = config_dir / ".env"
load_dotenv(env_path)

api_key = os.getenv("NEWS_API_KEY", "")

print(f"Testing NewsAPI with key: {api_key[:10]}..." if api_key else "No API key found!")
print("-" * 50)

if not api_key:
    print("ERROR: NEWS_API_KEY not set in .env")
    sys.exit(1)

# Test the API
url = "https://newsapi.org/v2/everything"
params = {
    "q": "AI",
    "apiKey": api_key,
    "pageSize": 1,
    "sortBy": "publishedAt",
}

try:
    response = httpx.get(url, params=params, timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Response:\n{response.text}\n")
    
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "ok":
            print("✅ API Key is VALID!")
            print(f"Found {len(data.get('articles', []))} articles")
        else:
            print(f"❌ API Error: {data.get('message')}")
    else:
        print(f"❌ HTTP Error {response.status_code}")
        
except Exception as e:
    print(f"❌ Request failed: {e}")
