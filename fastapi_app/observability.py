import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

from fastapi import Request
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

request_id_context: ContextVar[str] = ContextVar("request_id", default="-")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", request_id_context.get()),
        }
        for attr in (
            "method",
            "path",
            "status_code",
            "duration_ms",
            "client_ip",
            "route_group",
            "rate_limit",
            "rate_remaining",
            "retry_after",
        ):
            value = getattr(record, attr, None)
            if value is not None:
                payload[attr] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


_logging_configured = False


def setup_logging() -> logging.Logger:
    global _logging_configured
    logger = logging.getLogger("fastapi_app")
    if _logging_configured:
        return logger

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        handler.addFilter(RequestContextFilter())
        root_logger.addHandler(handler)
    else:
        for handler in root_logger.handlers:
            handler.setFormatter(JsonFormatter())
            handler.addFilter(RequestContextFilter())

    logger.setLevel(level)
    _logging_configured = True
    return logger


@dataclass
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, route_group: str) -> RateLimitDecision:
        now = time.time()
        bucket_key = (key, route_group)
        with self._lock:
            bucket = self._requests[bucket_key]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.limit:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0])))
                return RateLimitDecision(False, self.limit, 0, retry_after)
            bucket.append(now)
            remaining = max(0, self.limit - len(bucket))
            return RateLimitDecision(True, self.limit, remaining, 0)


class AppMetrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.requests_total: Dict[Tuple[str, str, int], int] = defaultdict(int)
        self.errors_total: Dict[Tuple[str, str], int] = defaultdict(int)
        self.rate_limit_hits_total: Dict[str, int] = defaultdict(int)
        self.latency_totals: Dict[Tuple[str, str], float] = defaultdict(float)
        self.latency_counts: Dict[Tuple[str, str], int] = defaultdict(int)

    def record_request(self, method: str, route_group: str, status_code: int, duration_ms: float):
        with self._lock:
            self.requests_total[(method, route_group, status_code)] += 1
            self.latency_totals[(method, route_group)] += duration_ms
            self.latency_counts[(method, route_group)] += 1
            if status_code >= 400:
                self.errors_total[(route_group, str(status_code))] += 1

    def record_rate_limit(self, route_group: str):
        with self._lock:
            self.rate_limit_hits_total[route_group] += 1

    def render_prometheus(self) -> str:
        lines = [
            "# HELP app_uptime_seconds Process uptime in seconds.",
            "# TYPE app_uptime_seconds gauge",
            f"app_uptime_seconds {time.time() - self.started_at:.3f}",
            "# HELP http_requests_total Total HTTP requests processed.",
            "# TYPE http_requests_total counter",
        ]
        with self._lock:
            for (method, route_group, status_code), total in sorted(self.requests_total.items()):
                lines.append(
                    f'http_requests_total{{method="{method}",route="{route_group}",status_code="{status_code}"}} {total}'
                )
            lines.extend(
                [
                    "# HELP http_request_duration_ms_avg Average request duration in milliseconds.",
                    "# TYPE http_request_duration_ms_avg gauge",
                ]
            )
            for key, total_duration in sorted(self.latency_totals.items()):
                count = self.latency_counts[key]
                average = total_duration / count if count else 0
                method, route_group = key
                lines.append(
                    f'http_request_duration_ms_avg{{method="{method}",route="{route_group}"}} {average:.3f}'
                )
            lines.extend(
                [
                    "# HELP http_errors_total Total HTTP responses with status >= 400.",
                    "# TYPE http_errors_total counter",
                ]
            )
            for (route_group, status_code), total in sorted(self.errors_total.items()):
                lines.append(f'http_errors_total{{route="{route_group}",status_code="{status_code}"}} {total}')
            lines.extend(
                [
                    "# HELP http_rate_limit_hits_total Total requests rejected by the rate limiter.",
                    "# TYPE http_rate_limit_hits_total counter",
                ]
            )
            for route_group, total in sorted(self.rate_limit_hits_total.items()):
                lines.append(f'http_rate_limit_hits_total{{route="{route_group}"}} {total}')
        return "\n".join(lines) + "\n"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, logger: logging.Logger, metrics: AppMetrics):
        super().__init__(app)
        self.logger = logger
        self.metrics = metrics

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        start = time.perf_counter()
        status_code = 500
        route_group = resolve_route_group(request)

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.metrics.record_request(request.method, route_group, status_code, duration_ms)
            self.logger.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": get_client_ip(request),
                    "route_group": route_group,
                },
            )
            request_id_context.reset(token)
            if 'response' in locals():
                response.headers["X-Request-ID"] = request_id
                response.headers["X-Process-Time-Ms"] = str(duration_ms)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cache-Control", "no-store")
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: InMemoryRateLimiter, metrics: AppMetrics, logger: logging.Logger):
        super().__init__(app)
        self.limiter = limiter
        self.metrics = metrics
        self.logger = logger
        self.exempt_prefixes = ("/docs", "/openapi.json", "/redoc", "/healthz", "/readyz", "/metrics")

    async def dispatch(self, request: Request, call_next):
        route_group = resolve_route_group(request)
        if request.url.path == "/" or request.url.path.startswith(self.exempt_prefixes):
            return await call_next(request)

        identity = get_client_ip(request)
        decision = self.limiter.check(identity, route_group)
        if not decision.allowed:
            self.metrics.record_rate_limit(route_group)
            self.logger.warning(
                "rate limit exceeded",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 429,
                    "client_ip": identity,
                    "route_group": route_group,
                    "rate_limit": decision.limit,
                    "rate_remaining": decision.remaining,
                    "retry_after": decision.retry_after,
                },
            )
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded. Please retry later."},
            )
            response.headers["Retry-After"] = str(decision.retry_after)
            response.headers["X-RateLimit-Limit"] = str(decision.limit)
            response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
            return response

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(decision.limit)
        response.headers["X-RateLimit-Remaining"] = str(decision.remaining)
        return response


async def http_exception_handler(request: Request, exc):
    logging.getLogger("fastapi_app").warning(
        "http exception",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": exc.status_code,
            "client_ip": get_client_ip(request),
            "route_group": resolve_route_group(request),
        },
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def unhandled_exception_handler(request: Request, exc: Exception):
    logging.getLogger("fastapi_app").exception(
        "unhandled exception",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": 500,
            "client_ip": get_client_ip(request),
            "route_group": resolve_route_group(request),
        },
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def resolve_route_group(request: Request) -> str:
    path = request.url.path
    if path.startswith("/admin/"):
        return "/admin/*"
    if path.startswith("/users"):
        return "/users/*"
    if path.startswith("/templates"):
        return "/templates/*"
    if path.startswith("/generations"):
        return "/generations/*"
    if path.startswith("/credit_packs"):
        return "/credit_packs/*"
    if path.startswith("/auth"):
        return "/auth/*"
    return path


def db_ready(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:
        logging.getLogger("fastapi_app").exception("database readiness check failed")
        return False


def metrics_response(metrics: AppMetrics) -> PlainTextResponse:
    return PlainTextResponse(metrics.render_prometheus(), media_type="text/plain; version=0.0.4; charset=utf-8")
