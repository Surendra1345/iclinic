"""Prometheus metrics for HTTP, voice, provider, and appointment operations."""
from prometheus_client import Counter, Gauge, Histogram

http_requests_total = Counter(
    "iclinic_http_requests_total",
    "Total HTTP requests.",
    ["method", "path", "status"],
)
http_request_duration_seconds = Histogram(
    "iclinic_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ["method", "path"],
)
voice_turn_duration_seconds = Histogram(
    "iclinic_voice_turn_duration_seconds",
    "End-to-end voice turn duration in seconds.",
)
voice_turn_total = Counter(
    "iclinic_voice_turn_total",
    "Completed voice turns.",
    ["outcome"],
)
provider_request_duration_seconds = Histogram(
    "iclinic_provider_request_duration_seconds",
    "External provider request duration in seconds.",
    ["provider", "operation"],
)
database_operation_duration_seconds = Histogram(
    "iclinic_database_operation_duration_seconds",
    "Database operation duration in seconds.",
    ["operation"],
)
booking_outcomes_total = Counter(
    "iclinic_booking_outcomes_total",
    "Appointment booking lifecycle outcomes.",
    ["action", "outcome"],
)
scheduler_last_run_timestamp = Gauge(
    "iclinic_scheduler_last_run_timestamp",
    "Unix timestamp of the last scheduler cleanup attempt.",
)
scheduler_released_slots_total = Counter(
    "iclinic_scheduler_released_slots_total",
    "Expired slot reservations released by the scheduler.",
)

intent_classification_duration_seconds = Histogram(
    "iclinic_intent_classification_duration_seconds",
    "Duration of intent classification in seconds.",
    ["model", "source"],
    buckets=[0.05, 0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0],
)
intent_classification_fallback_total = Counter(
    "iclinic_intent_classification_fallback_total",
    "Total fallback intent classifications triggered.",
    ["reason"],
)
intent_classification_total = Counter(
    "iclinic_intent_classification_total",
    "Total intent classifications requested.",
    ["model", "outcome"],
)
conversation_turn_duration_seconds = Histogram(
    "iclinic_conversation_turn_duration_seconds",
    "Full conversation turn duration in seconds.",
    ["channel"],
    buckets=[0.1, 0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0],
)

