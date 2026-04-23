import os
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

# Metrics
REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "endpoint"]
)
ACTIVE_REQUESTS = Gauge(
    "http_requests_active",
    "Active HTTP requests"
)
LLM_REQUEST_COUNT = Counter(
    "llm_requests_total",
    "Total LLM requests",
    ["model", "status"]
)
SOCIAL_POST_COUNT = Counter(
    "social_posts_total",
    "Total social media posts",
    ["platform", "status"]
)

class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        ACTIVE_REQUESTS.inc()
        method = request.method
        path = request.url.path
        with REQUEST_LATENCY.labels(method, path).time():
            response = await call_next(request)
        REQUEST_COUNT.labels(method, path, response.status_code).inc()
        ACTIVE_REQUESTS.dec()
        return response

async def metrics_endpoint():
    return Response(content=generate_latest(REGISTRY), media_type="text/plain")