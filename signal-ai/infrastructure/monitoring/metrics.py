
from prometheus_client import Counter, Histogram, Gauge

# Metrics
request_count = Counter("signal_requests_total", "Total HTTP requests", ["method", "endpoint", "status"])
request_duration = Histogram("signal_request_duration_seconds", "Request duration", ["method", "endpoint"])
llm_call_duration = Histogram("signal_llm_call_duration_seconds", "LLM call duration", ["model"])
post_count = Counter("signal_posts_total", "Total social media posts", ["platform", "status"])
active_sessions = Gauge("signal_active_sessions", "Number of active WebSocket sessions")


class MetricsCollector:
    @staticmethod
    def record_error(error_type: str, context: str = ""):
        pass

    @staticmethod
    def record_social_post(platform: str, status: str, latency: float = 0):
        post_count.labels(platform=platform, status=status).inc()

    @staticmethod
    def record_news_processing(source: str):
        pass

    @staticmethod
    def record_api_request(method: str, endpoint: str, status: int, duration: float):
        request_count.labels(method=method, endpoint=endpoint, status=str(status)).inc()
        request_duration.labels(method=method, endpoint=endpoint).observe(duration)


class MetricsContext:
    def __init__(self, name: str, **labels):
        self.name = name
        self.labels = labels

    def __enter__(self):
        pass

    def __exit__(self, *args):
        pass