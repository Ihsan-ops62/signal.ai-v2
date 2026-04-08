import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "ai_news_reporter")
    LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")

    # Search settings
    MAX_SEARCH_RESULTS = 5
    CACHE_TTL_SECONDS = 300  # 5 minutes
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

config = Config()