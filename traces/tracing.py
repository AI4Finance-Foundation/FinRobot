import os
import autogen
from finrobot.utils import get_current_date, register_keys_from_json
from finrobot.agents.workflow import SingleAssistant

# --- Critical Patch BEFORE Instrumentation ---
from autogen.agentchat.conversable_agent import ConversableAgent

# 1. Save original execute_function BEFORE instrumentation
_original_execute_function = ConversableAgent.execute_function

# 2. Create patched version that handles call_id
def _patched_execute_function(self, *args, **kwargs):
    kwargs.pop("call_id", None)
    return _original_execute_function(self, *args, **kwargs)

# 3. Apply patch immediately
ConversableAgent.execute_function = _patched_execute_function

# --- Tracing Instrumentation Setup ---
from arize.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.instrumentation.autogen import AutogenInstrumentor

# Configure OpenTelemetry
tracer_provider = register(
    space_id="U3BhY2U6MTY3MDA6Ni9MTg==",
    api_key="265815a200c38a6b74f",
    project_name="project1",
    set_global_tracer_provider=True
)

# Instrument with proper order
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
AutogenInstrumentor().instrument()

# --- Span Lifecycle Fix ---
from opentelemetry.trace import Span

# Save original end method
_original_span_end = Span.end

# Create safe end wrapper
def _safe_span_end(self):
    if self.is_recording():
        _original_span_end(self)

# Apply span protection
Span.end = _safe_span_end

# --- Application Configuration ---
# Verify OpenAI config format in OAI_CONFIG_LIST
llm_config = {
    "config_list": autogen.config_list_from_json(
        "./OAI_CONFIG_LIST",
        filter_dict={"model": ["gpt-4-0125-preview"]},
    ),
    "timeout": 120,
    "temperature": 0,
}

# Register FINNHUB API keys
register_keys_from_json("./config_api_keys")
company = "APPLE"

# Initialize assistant
assistant = SingleAssistant(
    "Market_Analyst",
    llm_config,
    human_input_mode="NEVER",
)

# Execute with error handling
try:
    assistant.chat(
        f"Analyze {company} as of {get_current_date()}. "
        "Identify key factors from news and predict stock movement."
    )
    assistant.chat(
        f"Re-analyze {company} with latest data and update prediction."
    )
except Exception as e:
    print(f"Operation failed: {str(e)}")
finally:
    if tracer_provider:
        tracer_provider.force_flush()
        tracer_provider.shutdown()