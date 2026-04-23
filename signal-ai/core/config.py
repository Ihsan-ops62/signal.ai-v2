import os
from pathlib import Path
from dotenv import load_dotenv
from cryptography.fernet import Fernet

config_dir = Path(__file__).parent

env_path = config_dir.parent / ".env"
load_dotenv(env_path)

class Config:
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    TOKEN_ENCRYPTION_KEY: str = os.getenv("TOKEN_ENCRYPTION_KEY")

    def __init__(self):
        
        if not self.SECRET_KEY:
            raise ValueError("CRITICAL: SECRET_KEY environment variable is required for server startup. Make sure it is in your .env file.")
        if not self.TOKEN_ENCRYPTION_KEY:
            raise ValueError("CRITICAL: TOKEN_ENCRYPTION_KEY environment variable is required for server startup.")
        try:
            Fernet(self.TOKEN_ENCRYPTION_KEY.encode())
        except Exception as e:
            raise ValueError(f"CRITICAL: TOKEN_ENCRYPTION_KEY is not a valid Fernet key format: {e}")
    
    # Ollama
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral:latest")
    OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", 12000.0))
    
    # MongoDB
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
    MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "signal_db")

    # LinkedIn
    LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
    LINKEDIN_ORGANIZATION_ID = os.getenv("LINKEDIN_ORGANIZATION_ID", "")
    LINKEDIN_CLIENT_ID = os.getenv("LINKEDIN_CLIENT_ID", "")
    LINKEDIN_CLIENT_SECRET = os.getenv("LINKEDIN_CLIENT_SECRET", "")
    LINKEDIN_REDIRECT_URI = os.getenv("LINKEDIN_REDIRECT_URI", "http://localhost:8000/auth/linkedin/callback")

    # Facebook
    FACEBOOK_PAGE_ACCESS_TOKEN = os.getenv("FACEBOOK_PAGE_ACCESS_TOKEN", "")
    FACEBOOK_PAGE_ID = os.getenv("FACEBOOK_PAGE_ID", "")
    FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
    FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
    FACEBOOK_REDIRECT_URI = os.getenv("FACEBOOK_REDIRECT_URI", "http://localhost:8000/auth/facebook/callback")

    # Twitter
    TWITTER_CLIENT_ID = os.getenv("TWITTER_CLIENT_ID", "")
    TWITTER_CLIENT_SECRET = os.getenv("TWITTER_CLIENT_SECRET", "")
    TWITTER_REDIRECT_URI = os.getenv("TWITTER_REDIRECT_URI", "http://localhost:8000/auth/twitter/callback")

    # News API
    NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")

    # Redis / Celery
    CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/3")
    CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/4")
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
    REDIS_DB = int(os.getenv("REDIS_DB", 0))

    MAX_SEARCH_RESULTS = 5
    CACHE_TTL_SECONDS = 3000

config = Config()
settings = config