"""
Prometheus metrics for Pulse.

Defines the metric objects and provides a helper to expose them on a
dedicated endpoint. Metrics are updated by handler code as requests flow
through the app.
"""

import time
from functools import wraps
from prometheus_client import Counter, Gauge, Histogram, generate_latest, CONTENT_TYPE_LATEST


# --- Metric definitions ---

# Total HTTP requests, broken down by endpoint and status code.
# Counter: only goes up. We compute "requests per second" by taking rate() over time.
request_count = Counter(
    "pulse_http_requests_total",
    "Total number of HTTP requests handled",
    ["endpoint", "status_code"],
)

# Request duration in seconds, bucketed for percentile calculations.
# Histogram: lets us ask "what's the p95 latency for /api/dora?"
request_duration = Histogram(
    "pulse_http_request_duration_seconds",
    "Time spent processing each HTTP request",
    ["endpoint"],
)

# Current count of services Pulse is monitoring.
# Gauge: goes up when added, down when deleted.
monitored_services_count = Gauge(
    "pulse_monitored_services",
    "Number of services currently being monitored",
)

# CPU/memory/disk as gauges.
cpu_percent = Gauge("pulse_cpu_percent", "Current CPU usage percentage")
memory_percent = Gauge("pulse_memory_percent", "Current memory usage percentage")
disk_percent = Gauge("pulse_disk_percent", "Current disk usage percentage")


# --- Decorator to instrument Flask routes ---

def track_request(endpoint_name):
    """
    Decorator that increments request_count and observes duration
    for a Flask route. Use it like:

        @app.route('/health')
        @track_request('health')
        def health(): ...
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.time()
            status_code = "500"  # default if exception bubbles up
            try:
                response = func(*args, **kwargs)
                # Flask handlers can return a tuple (body, status) or just a body
                if isinstance(response, tuple) and len(response) >= 2:
                    status_code = str(response[1])
                else:
                    status_code = "200"
                return response
            finally:
                duration = time.time() - start
                request_count.labels(endpoint=endpoint_name, status_code=status_code).inc()
                request_duration.labels(endpoint=endpoint_name).observe(duration)
        return wrapper
    return decorator


# --- The endpoint Prometheus scrapes ---

def metrics_response():
    """
    Generate the Prometheus exposition format response.
    Returns (body, content_type) — caller wraps in Flask Response.
    """
    return generate_latest(), CONTENT_TYPE_LATEST