from openinference.instrumentation.openai import OpenAIInstrumentor
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from ai_service.core.settings import Settings


def setup_tracing(settings: Settings) -> None:
    """Export spans to Phoenix over OTLP/gRPC (D21); LLM calls get OpenInference spans."""
    if not settings.otel_exporter_otlp_endpoint:
        return
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: settings.otel_service_name}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    OpenAIInstrumentor().instrument(tracer_provider=provider)
