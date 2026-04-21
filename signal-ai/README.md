# Signal AI - Production-Grade AI News Reporter System

A scalable, multi-agent architecture for intelligent news discovery, summarization, and social media publishing. Built with FastAPI, LangGraph, and production-ready infrastructure.

## Features

- **Multi-Agent Architecture**: Specialized agents for intent detection, news search, summarization, formatting, and social posting
- **Dual LLM Support**: Ollama (local) with OpenAI fallback for reliability
- **Smart News Aggregation**: Real-time news discovery with quality filtering and deduplication
- **Social Media Integration**: LinkedIn, Twitter (X), and Facebook posting with OAuth
- **Conversational Interface**: Chat API for natural language interactions
- **Async Processing**: Celery workers for background tasks
- **Event-Driven**: Kafka for real-time event streaming
- **Comprehensive Monitoring**: Prometheus metrics, structured logging, health checks
- **Rate Limiting & Caching**: Redis-based caching with automatic fallback to in-memory
- **Fully Containerized**: Docker and Docker Compose for production deployment

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    FastAPI Application                       │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Routes: /chat, /social, /admin, /webhooks, /auth    │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        │              │              │
    ┌─────────┐   ┌─────────┐   ┌─────────┐
    │ Agents  │   │Services │   │  Infra  │
    ├─────────┤   ├─────────┤   ├─────────┤
    │ Intent  │   │LLM      │   │PostgreSQL
    │ Search  │   │Social   │   │MongoDB
    │ Filter  │   │Search   │   │Redis
    │ Summary │   │Cache    │   │Kafka
    │ Format  │   │OAuth    │   │
    │ Social  │   │Queue    │   │
    └─────────┘   └─────────┘   └─────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- NewsAPI key (free tier available)
- LinkedIn/Twitter/Facebook OAuth credentials (optional)

### Development Setup

1. **Clone and setup**
```bash
git clone https://github.com/yourusername/signal-ai.git
cd signal-ai
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

2. **Configure environment**
```bash
cp .env.example .env
# Edit .env with your API keys
```

3. **Start services (Docker recommended)**
```bash
docker-compose up -d
```

4. **Run application**
```bash
# Terminal 1: API
uvicorn api.main:app --reload

# Terminal 2: Celery Worker
celery -A services.queue.celery_app worker --loglevel=info

# Terminal 3: Celery Beat (scheduler)
celery -A services.queue.celery_app beat --loglevel=info
```

5. **Access API**
```
API: http://localhost:8000
Docs: http://localhost:8000/docs
Metrics: http://localhost:8000/metrics
```

## Production Deployment

### Using Docker Compose

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop services
docker-compose down
```

### Using Kubernetes

```bash
# Deploy (requires k8s resources in deployments/k8s/)
kubectl apply -f deployments/k8s/
```

### Cloud Deployment (AWS/GCP/Azure)

See `deployments/terraform/` for infrastructure-as-code templates.

## API Endpoints

### Authentication
- `POST /api/auth/register` - Register new user
- `POST /api/auth/login` - Login user
- `POST /api/auth/refresh` - Refresh token
- `GET /api/auth/me` - Get current user

### Chat & News
- `POST /api/chat/search-news` - Search news articles
- `GET /api/chat/trending-news` - Get trending news
- `POST /api/chat/chat` - Chat with AI

### Social Media
- `POST /api/social/post` - Post to social platforms
- `GET /api/social/auth/linkedin` - LinkedIn OAuth
- `GET /api/social/auth/facebook` - Facebook OAuth
- `POST /api/social/auth/callback` - OAuth callback

### Admin
- `GET /api/admin/health` - System health
- `GET /api/admin/stats` - System statistics
- `POST /api/admin/cache/clear` - Clear cache
- `GET /api/admin/config` - Get configuration

## Configuration

All configuration via environment variables. See `.env.example` for complete list:

```bash
# Core
ENVIRONMENT=production
DEBUG=false

# LLM
LLM_PRIMARY_PROVIDER=ollama
LLM_OLLAMA_BASE_URL=http://ollama:11434

# Social Media APIs
SOCIAL_LINKEDIN_CLIENT_ID=...
SOCIAL_TWITTER_API_KEY=...
SOCIAL_FACEBOOK_APP_ID=...

# NewsAPI
NEWS_NEWSAPI_KEY=...
```

## Project Structure

```
signal-ai/
├── api/                      # FastAPI routes & schemas
│   ├── routes/              # Endpoint handlers
│   ├── schemas/             # Request/response models
│   ├── dependencies/        # Auth, DB, rate limiting
│   └── main.py             # Application factory
├── agents/                   # Multi-agent modules
│   ├── intent/             # Intent detection
│   ├── search/             # News search
│   ├── summarizer/         # Content summarization
│   ├── formatter/          # Platform formatting
│   └── social/             # Social posting
├── services/                 # Business logic
│   ├── llm/               # LLM abstraction (Ollama, OpenAI)
│   ├── social/            # Social media platforms
│   ├── cache/             # Redis & in-memory
│   ├── search/            # News search service
│   ├── oauth/             # OAuth flows
│   └── queue/             # Celery tasks
├── infrastructure/           # Infrastructure
│   ├── database/          # PostgreSQL & MongoDB
│   ├── messaging/         # Kafka events
│   └── monitoring/        # Logging & metrics
├── core/                     # Core utilities
│   ├── config.py          # Configuration
│   ├── security.py        # JWT, encryption
│   └── exceptions.py      # Custom exceptions
├── tests/                    # Test suites
├── scripts/                  # Utilities
├── deployments/              # Docker, K8s, Terraform
├── requirements.txt          # Python dependencies
├── docker-compose.yml        # Full stack
├── Dockerfile               # Container image
└── README.md                # This file
```

## Key Production Improvements

### Reliability
- ✅ Automatic LLM failover (Ollama → OpenAI)
- ✅ Exponential backoff retry logic
- ✅ Circuit breaker for external APIs
- ✅ Health checks on all services
- ✅ MongoDB + PostgreSQL hybrid storage

### Scalability
- ✅ Async FastAPI with connection pooling
- ✅ Celery worker scaling
- ✅ Kafka event streaming
- ✅ Redis distributed caching
- ✅ Horizontal API scaling (load balanced)

### Security
- ✅ JWT token management
- ✅ OAuth 2.0 social media
- ✅ Encrypted token storage
- ✅ Rate limiting per user/IP
- ✅ CORS configuration
- ✅ API key authentication

### Observability
- ✅ Prometheus metrics (/metrics endpoint)
- ✅ Structured JSON logging
- ✅ Request tracing
- ✅ Error tracking
- ✅ Performance monitoring

### Code Quality
- ✅ Type hints (MyPy)
- ✅ Comprehensive error handling
- ✅ Modular architecture
- ✅ Unit & integration tests
- ✅ Black formatting
- ✅ Docstrings

## Testing

```bash
# Run all tests
pytest

# With coverage
pytest --cov=api --cov=services --cov=agents

# Unit tests only
pytest tests/unit/

# Integration tests
pytest tests/integration/

# E2E tests
pytest tests/e2e/
```

## Monitoring

### Health Checks
```bash
curl http://localhost:8000/health
```

### Metrics
```bash
curl http://localhost:8000/metrics
```

### Logs
```bash
# Docker
docker-compose logs -f api

# Structured JSON logs include:
# - timestamp, level, logger, message
# - module, function, line
# - user_id, request_id (when available)
```

## Troubleshooting

### LLM Service Down
- Falls back to OpenAI automatically
- Check: `docker-compose logs ollama`
- Restart: `docker-compose restart ollama`

### Database Connection Error
- Verify PostgreSQL running: `docker-compose ps postgres`
- Check credentials in `.env`
- Migrations run automatically on startup

### Social Media API Errors
- Rate limits: Check platform API limits
- OAuth tokens: Re-authenticate via `/api/social/auth/*`
- Signature failures: Verify webhook secrets

### Performance Issues
- Check Redis: `redis-cli info stats`
- Monitor CPU/Memory: `docker stats`
- Scale workers: Update `docker-compose.yml`

## Contributing

1. Fork repository
2. Create feature branch
3. Make changes with tests
4. Submit pull request

## License

MIT License - see LICENSE file for details

## Support

- Documentation: https://docs.signal-ai.dev
- Issues: GitHub Issues
- Discussions: GitHub Discussions

---

**Built with** ❤️ for production-grade AI applications
