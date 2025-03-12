import os
import autogen
from finrobot.utils import get_current_date, register_keys_from_json
from finrobot.agents.workflow import SingleAssistant
import logging 
from opentelemetry import trace

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


# --- Enhanced Logging Configuration ---
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(TRACE_LOGGER_NAME)
logger.setLevel(logging.DEBUG)


# --- Tracing Instrumentation Setup ---
from arize.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.instrumentation.autogen import AutogenInstrumentor

from autogen_core import TRACE_LOGGER_NAME

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(TRACE_LOGGER_NAME)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)

logger.debug("Initializing Arize tracer provider")


# Configure OpenTelemetry with Arize credentials
tracer_provider = register(
    space_id="U3BhY2U6MTY3MDA6Ni9MTg==",  # replace with your actual space id
    api_key="265815a200c38a6b74f",           # replace with your actual API key
    project_name="agent_fingpt_forecaster.py",                 # replace with your project name
    set_global_tracer_provider=True
)

logger.debug("Instrumenting OpenAI and Autogen")
# Instrument OpenAI calls using the tracer_provider
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
# Instrument Autogen calls (no tracer_provider supported)
AutogenInstrumentor().instrument()

# --- Span Lifecycle Fix ---
from opentelemetry.trace import Span

# Save original end method of Span
_original_span_end = Span.end

def _safe_span_end(self):
    # Only end the span if it's still recording
    if self.is_recording():
        _original_span_end(self)

# Patch Span.end to protect against modifications after ending
Span.end = _safe_span_end

def log_with_trace(message, level=logging.DEBUG):
    current_span = trace.get_current_span()
    trace_id = current_span.get_span_context().trace_id
    logger.log(level, f"[Trace ID: {trace.trace_id_to_hex(trace_id)}] {message}")

# --- Application Configuration ---
logger.debug("Loading LLM")
# Read OpenAI API keys from a JSON file using a relative path
llm_config = {
    "config_list": autogen.config_list_from_json(
        "../OAI_CONFIG_LIST",
        filter_dict={"model": ["gpt-4-0125-preview"]},
    ),
    "timeout": 120,
    "temperature": 0,
}

# Register FINNHUB API keys (using a relative path)
register_keys_from_json("../config_api_keys")
company = "APPLE"

# Initialize the assistant (note: using 'assistant' for clarity)
assistant = SingleAssistant(
    "Market_Analyst",
    llm_config,
    human_input_mode="NEVER",
)
from autogen_core import TRACE_LOGGER_NAME
# Execute the assistant's chat calls with error handling
try:
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(TRACE_LOGGER_NAME)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)
    assistant.chat(
        f"Use all the tools provided to retrieve information available for {company} upon {get_current_date()}. "
        "Analyze the positive developments and potential concerns of {company} with 2-4 most important factors respectively "
        "and keep them concise. Most factors should be inferred from company related news. "
        f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. "
        "Provide a summary analysis to support your prediction."
    )
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(TRACE_LOGGER_NAME)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)
    assistant.chat(
        f"ForeCast Next few points and Use all the tools provided to retrieve information available for {company} upon {get_current_date()}. "
        "Analyze the positive developments and potential concerns of {company} with 2-4 most important factors respectively "
        "and keep them concise. Most factors should be inferred from company related news. "
        f"Then make a rough prediction (e.g. up/down by 2-3%) of the {company} stock price movement for next week. "
        "Provide a summary analysis to support your prediction."
    )
    logging.basicConfig(level=logging.WARNING)
    logger = logging.getLogger(TRACE_LOGGER_NAME)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)
    with 
except Exception as e:
    print(f"Operation failed: {str(e)}")
finally:
    if tracer_provider:
        tracer_provider.force_flush()
        tracer_provider.shutdown()
