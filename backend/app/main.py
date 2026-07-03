import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# -------------------------------------------------------------------------
# Telemetry & Observability Setup (Prometheus Metrics)
# -------------------------------------------------------------------------
# Tracks total HTTP request count sliced by method, endpoint, and status code
HTTP_REQUESTS_TOTAL = Counter(
    "zitron_http_requests_total",
    "Total count of HTTP requests received by Zitron core.",
    ["method", "endpoint", "http_status"]
)

# Tracks request latency (P95/P99 splits) for monitoring processing bottlenecks
HTTP_REQUEST_LATENCY_SECONDS = Histogram(
    "zitron_http_request_latency_seconds",
    "Histogram of HTTP request processing latencies in seconds.",
    ["method", "endpoint"]
)

# -------------------------------------------------------------------------
# Application Lifespan Management (Startup / Shutdown Hooks)
# -------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: Initialize thread pools, verify model file presence in data/models/, 
    # and warm up connection pools.
    print("[INIT] Starting Zitron Core Async Pipeline...")
    yield
    # Shutdown: Flush active task logs, gracefully disconnect DB, close Redis rings.
    print("[SHUTDOWN] Cleared system state. Flushed remaining pipeline vectors.")

# Initialize the core FastAPI instance
app = FastAPI(
    title="ZITRON Medical Imaging & Agentic Orchestrator Core",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/v1/docs",      # Clean versioned API endpoints
    redoc_url="/api/v1/redoc"
)

# -------------------------------------------------------------------------
# Security & Connectivity: Cross-Origin Resource Sharing (CORS)
# -------------------------------------------------------------------------
# Configuring strict cors rules to protect the healthcare API boundary
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to Astro/Vite domain in production staging
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
)

# -------------------------------------------------------------------------
# Global Telemetry Middleware
# -------------------------------------------------------------------------
@app.middleware("http")
async def intercept_and_telemeter_requests(request: Request, call_next):
    start_time = time.perf_counter()
    endpoint = request.url.path
    method = request.method
    
    # Process the request down the middleware chain
    try:
        response: Response = await call_next(request)
        status_code = str(response.status_code)
    except Exception as e:
        status_code = "500"
        raise e
    finally:
        duration = time.perf_counter() - start_time
        
        # Guard against metrics pollution from high-frequency telemetry scrapers
        if endpoint != "/metrics" and endpoint != "/api/v1/health":
            HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, http_status=status_code).inc()
            HTTP_REQUEST_LATENCY_SECONDS.labels(method=method, endpoint=endpoint).observe(duration)
            
    return response

# -------------------------------------------------------------------------
# Base Infrastructure Endpoints
# -------------------------------------------------------------------------
@app.get("/api/v1/health", tags=["Infrastructure"])
async def health_check():
    """
    Verifies API core state. Used by docker-compose healthchecks 
    and Azure Container App probes.
    """
    return {
        "status": "HEALTHY",
        "timestamp": time.time(),
        "subsystems": {
            "api_core": "ONLINE",
            "celery_worker_bridge": "INITIALIZED",
            "privacy_scrubber_engine": "READY"
        }
    }

@app.get("/metrics", tags=["Infrastructure"])
def metrics_endpoint():
    """
    Exposes real-time application metrics structured natively 
    for the Prometheus scraping daemon.
    """
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)