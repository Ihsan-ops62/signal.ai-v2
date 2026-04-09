import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the directory where config.py is located
config_dir = Path(__file__).parent
env_path = config_dir / ".env"
print(f"DEBUG: Loading .env from: {env_path}")
print(f"DEBUG: .env exists: {env_path.exists()}")
load_dotenv(env_path)
print(f"DEBUG: .env loaded. Environment NOW has NEWS_API_KEY: {os.getenv('NEWS_API_KEY', 'NOT_FOUND')[:20]}..." if os.getenv('NEWS_API_KEY') else "DEBUG: NEWS_API_KEY NOT in environment after load")

class Config:
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "ai_news_reporter")
    LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    
    # Facebook settings
    FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")

    # Search settings
    MAX_SEARCH_RESULTS = 5
    CACHE_TTL_SECONDS = 300  # 5 minutes
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

config = Config()