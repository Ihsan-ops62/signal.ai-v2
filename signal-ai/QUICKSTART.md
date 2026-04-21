# Signal AI - Quick Start Guide

## 🚀 5-Minute Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose
- NewsAPI key (get free at https://newsapi.org)

### Step 1: Clone & Setup Python
```bash
cd d:/reporter agent/signal-ai
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Step 2: Configure Environment
```bash
cp .env.example .env
```

Edit `.env` with your keys:
```
NEWS_NEWSAPI_KEY=your_key_here
SOCIAL_LINKEDIN_CLIENT_ID=optional
SOCIAL_TWITTER_API_KEY=optional
SOCIAL_FACEBOOK_APP_ID=optional
```

### Step 3: Start Services
```bash
# Start all services (PostgreSQL, MongoDB, Redis, Kafka, Ollama, etc)
docker-compose up -d

# Wait for services to be ready (~30 seconds)
docker-compose ps
```

### Step 4: Initialize Database
```bash
python scripts/migrate_db.py
python scripts/seed_data.py
```

### Step 5: Run Application
```bash
# Terminal 1: API Server
uvicorn api.main:app --reload --port 8000

# Terminal 2: Celery Worker
celery -A services.queue.celery_app worker --loglevel=info

# Terminal 3: Celery Beat (scheduler)
celery -A services.queue.celery_app beat --loglevel=info
```

### Step 6: Access Application
- **API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Metrics**: http://localhost:8000/metrics
- **Health**: http://localhost:8000/health

---

## 📋 Testing the API

### Register User
```bash
curl -X POST http://localhost:8000/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123",
    "name": "Test User"
  }'
```

### Login
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "password": "password123"
  }'
```

### Search News
```bash
curl -X POST http://localhost:8000/api/chat/search-news \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "query": "artificial intelligence",
    "limit": 5
  }'
```

### Chat
```bash
curl -X POST http://localhost:8000/api/chat/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "message": "What are the latest tech news?"
  }'
```

### Post to Social Media
```bash
curl -X POST http://localhost:8000/api/social/post \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -d '{
    "content": "Breaking news: Major AI breakthrough announced today!",
    "platforms": ["twitter", "linkedin"],
    "media_urls": []
  }'
```

---

## 🐳 Docker Commands

### View Running Services
```bash
docker-compose ps
```

### View Logs
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f api
docker-compose logs -f mongodb
docker-compose logs -f postgres
```

### Stop Services
```bash
docker-compose down
```

### Rebuild Images
```bash
docker-compose build --no-cache
```

---

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:8000/health
```

### View Metrics
```bash
curl http://localhost:8000/metrics
```

### Admin Stats
```bash
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  http://localhost:8000/api/admin/stats
```

### View Logs
```bash
# Stream logs from MongoDB
docker exec signal-ai-mongodb mongosh \
  -u signal_user -p secure_password \
  --authenticationDatabase admin \
  -e "db.logs.find().limit(10)"
```

---

## 🔧 Common Troubleshooting

### Port Already In Use
```bash
# Change port in docker-compose.yml
# or kill process using port
lsof -i :8000  # Find process
kill -9 <PID>  # Kill it
```

### Services Not Healthy
```bash
# Check individual service health
docker-compose logs postgres
docker-compose logs mongodb
docker-compose logs redis

# Restart problematic service
docker-compose restart postgres
```

### LLM Service (Ollama) Not Running
```bash
# Ollama takes time to start - wait 30 seconds
docker-compose logs ollama

# If stuck, download a model
docker exec signal-ai-ollama ollama pull mistral
```

### Database Connection Error
```bash
# Check credentials in .env match docker-compose.yml
# Default: signal_user / secure_password
# Reset database
docker-compose down -v
docker-compose up -d
```

### High Memory Usage
```bash
# Ollama is memory-intensive with LLM loaded
# Use smaller model: docker exec signal-ai-ollama ollama pull orca-mini
# Or increase Docker memory allocation
```

---

## 📚 API Documentation

### Interactive Docs (Swagger UI)
Visit: http://localhost:8000/docs

Click "Try it out" to test endpoints directly!

### Alternative Docs (ReDoc)
Visit: http://localhost:8000/redoc

---

## 🧪 Run Tests

### All Tests
```bash
pytest tests/ -v
```

### Unit Tests Only
```bash
pytest tests/unit/ -v
```

### With Coverage
```bash
pytest tests/ --cov=api --cov=services --cov=agents
```

---

## 📦 Project Structure

```
signal-ai/
├── api/              # FastAPI routes and schemas
├── agents/           # Multi-agent system (LangGraph)
├── services/         # Business logic services
├── infrastructure/   # Database, messaging, monitoring
├── core/             # Configuration, security, exceptions
├── tests/            # Unit and integration tests
├── scripts/          # Utilities (migrate, seed)
├── deployments/      # Docker, Kubernetes configs
├── requirements.txt  # Python dependencies
├── docker-compose.yml # Full stack
└── README.md         # Full documentation
```

---

## 🚀 Next Steps

1. **Add More News Sources**: Edit config to add RSS feeds
2. **Configure Social Media**: Get OAuth credentials from each platform
3. **Customize Agents**: Modify agents/ files for custom behavior
4. **Add Tests**: Create tests/unit/test_*.py files
5. **Deploy**: Use docker-compose or Kubernetes

---

## 💡 Tips & Tricks

### Use Interactive API Docs
The Swagger UI at `/docs` is amazing - you can:
- Test all endpoints without curl
- See request/response examples
- Download OpenAPI JSON

### Monitor in Real-Time
```bash
# Watch metrics
watch -n 1 'curl -s http://localhost:8000/metrics | grep api_requests'

# Follow logs
docker-compose logs -f api | grep "INFO\|ERROR"
```

### Scale for Load Testing
```bash
# Run multiple workers
docker-compose up -d --scale celery-worker=3
```

### Enable Debug Logging
```bash
# In .env
LOG_LEVEL=DEBUG
DEBUG=true

# Restart
docker-compose restart api
```

---

## 🆘 Support

- **Docs**: [README.md](README.md)
- **API Docs**: http://localhost:8000/docs
- **Issues**: Check GitHub Issues
- **Logs**: `docker-compose logs` + `/api/admin/health`

---

**Happy coding! 🎉**
