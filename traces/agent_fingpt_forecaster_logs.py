import os
import sys
import autogen
import logging
from finrobot.utils import get_current_date, register_keys_from_json
from finrobot.agents.workflow import SingleAssistant
from opentelemetry import trace
from autogen_core import TRACE_LOGGER_NAME

# --- Critical Patch BEFORE Instrumentation ---
from autogen.agentchat.conversable_agent import ConversableAgent

# Save original execute_function and patch it to handle 'call_id'
_original_execute_function = ConversableAgent.execute_function

def _patched_execute_function(self, *args, **kwargs):
    kwargs.pop("call_id", None)
    return _original_execute_function(self, *args, **kwargs)

ConversableAgent.execute_function = _patched_execute_function

# ============================
# Terminal Redirection Class
# ============================
class StreamToLogger:
    def __init__(self, logger, log_level=logging.INFO):
        self.logger = logger
        self.log_level = log_level
        self.linebuf = ''

    def write(self, buf):
        for line in buf.rstrip().splitlines():
            self.logger.log(self.log_level, line.rstrip())

    def flush(self):
        pass

# ============================
# Enhanced Logging Setup
# ============================

import logging

from autogen_core import EVENT_LOGGER_NAME

def setup_logging():
    # Create log directory if not exists
    os.makedirs("logs", exist_ok=True)
    
    # Root logger configuration
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # File handler for all logs
    file_handler = logging.FileHandler('app.log', mode='w')
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s:%(lineno)d]'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(logging.DEBUG)
    
    # Console handler for visibility
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(logging.INFO)
    
    # Add handlers to root logger
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Specialized loggers configuration
    loggers = [
        logging.getLogger(name) 
        for name in [
            TRACE_LOGGER_NAME,
            'openai',
            'opentelemetry',
            'arize',
            'urllib3',
            'httpcore',
            'httpx'
        ]
    ]
    
    for logger in loggers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)
        logger.propagate = False  # Prevent duplicate logs
    
    # Redirect stdout and stderr
    sys.stdout = StreamToLogger(logging.getLogger('STDOUT'), logging.INFO)
    sys.stderr = StreamToLogger(logging.getLogger('STDERR'), logging.ERROR)
    
    return logging.getLogger(__name__)

# ============================
# Tracing Instrumentation
# ============================
def setup_instrumentation():
    from arize.otel import register
    from openinference.instrumentation.openai import OpenAIInstrumentor
    from openinference.instrumentation.autogen import AutogenInstrumentor

    logger = logging.getLogger(TRACE_LOGGER_NAME)
    logger.debug("Initializing Arize tracer provider")

    tracer_provider = register(
        space_id="U3BhY2U6MTY3MDA6Ni9MTg==",  # Replace with actual values
        api_key="265815a200c38a6b74f",
        project_name="agent_fingpt_forecaster.py",
        set_global_tracer_provider=True
    )

    logger.debug("Instrumenting OpenAI and Autogen")
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    logger.debug("OpenAI_Instrumentor")
    AutogenInstrumentor().instrument()
    logger.debug("AutogenInstrumentor")

    return tracer_provider

# ============================
# Span Lifecycle Fix
# ============================
def patch_span_end():
    from opentelemetry.trace import Span
    _original_span_end = Span.end

    def _safe_span_end(self):
        if self.is_recording():
            _original_span_end(self)

    Span.end = _safe_span_end

# ============================
# Trace-Aware Logging
# ============================
def log_with_trace(message, level=logging.DEBUG):
    current_span = trace.get_current_span()
    trace_context = current_span.get_span_context()
    trace_id = trace_context.trace_id
    trace_id_hex = trace.trace_id_to_hex(trace_id) if hasattr(trace, 'trace_id_to_hex') else f"{trace_id:032x}"
    
    logger = logging.getLogger(TRACE_LOGGER_NAME)
    logger.log(level, f"[Trace ID: {trace_id_hex}] {message}")

# ============================
# Main Application
# ============================
def main():
    logger = setup_logging()
    patch_span_end()
    tracer_provider = setup_instrumentation()

    try:
        # --- Configuration ---
        logger.debug("Loading LLM configuration")
        llm_config = {
            "config_list": autogen.config_list_from_json(
                "../OAI_CONFIG_LIST",
                filter_dict={"model": ["gpt-4-0125-preview"]},
            ),
            "timeout": 120,
            "temperature": 0,
        }

        register_keys_from_json("../config_api_keys")
        company = "APPLE"
        
        assistant = SingleAssistant(
            "Market_Analyst",
            llm_config,
            human_input_mode="NEVER",
        )

        # --- Execution ---
        log_with_trace("Starting first analysis request")
        assistant.chat(
            f"Use all tools to retrieve {company} data as of {get_current_date()}. "
            "Analyze 2-4 key positive/negative factors from news. "
            "Predict next week's stock price movement with reasoning."
        )

        log_with_trace("Starting forecast analysis request")
        assistant.chat(
            f"Forecast {company}'s next week performance using all tools. "
            "Include 2-4 key factors from news analysis. "
            "Provide concise prediction and reasoning."
        )
        
    except Exception as e:
        logger.exception("Fatal error occurred")
        print(f"Operation failed: {str(e)}")  # Will be logged via StreamToLogger
    finally:
        if tracer_provider:
            tracer_provider.force_flush()
            tracer_provider.shutdown()
        logging.shutdown()

if __name__ == "__main__":
    main()