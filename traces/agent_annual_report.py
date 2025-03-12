import os
import autogen
from textwrap import dedent
from finrobot.utils import register_keys_from_json
from finrobot.agents.workflow import SingleAssistantShadow

# --- Critical Patch BEFORE Instrumentation ---
from autogen.agentchat.conversable_agent import ConversableAgent

# Save original execute_function before instrumentation
_original_execute_function = ConversableAgent.execute_function

# Create a patched version to remove the extra call_id parameter
def _patched_execute_function(self, *args, **kwargs):
    kwargs.pop("call_id", None)
    return _original_execute_function(self, *args, **kwargs)

# Apply the patch immediately
ConversableAgent.execute_function = _patched_execute_function

# --- Tracing Instrumentation Setup ---
from arize.otel import register
from openinference.instrumentation.openai import OpenAIInstrumentor
from openinference.instrumentation.autogen import AutogenInstrumentor

# Configure OpenTelemetry with Arize credentials
tracer_provider = register(
    space_id="U3BhY2U6MTY3MDA6Ni9MTg==",  # replace with your actual space id
    api_key="265815a200c38a6b74f",           # replace with your actual API key
    project_name="agent_annual_report",                 # replace with your project name
    set_global_tracer_provider=True
)

# Instrument OpenAI and Autogen calls
OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
AutogenInstrumentor().instrument()

# --- Span Lifecycle Fix ---
from opentelemetry.trace import Span

# Save the original end method of Span
_original_span_end = Span.end

# Create a safe span end wrapper to only end spans if they are still recording
def _safe_span_end(self):
    if self.is_recording():
        _original_span_end(self)

# Apply the span protection
Span.end = _safe_span_end

# --- Application Configuration ---
llm_config = {
    "config_list": autogen.config_list_from_json(
        "../OAI_CONFIG_LIST",
        filter_dict={
            "model": ["gpt-4-0125-preview"],
        },
    ),
    "timeout": 120,
    "temperature": 0.5,
}

# Register FINNHUB API keys using a relative path
register_keys_from_json("../config_api_keys")

# Create the working directory for intermediate results
work_dir = "../report"
os.makedirs(work_dir, exist_ok=True)

assistant = SingleAssistantShadow(
    "Expert_Investor",
    llm_config,
    max_consecutive_auto_reply=None,
    human_input_mode="TERMINATE",
)

company = "Microsoft"
fyear = "2023"

message = dedent(
    f"""
    With the tools you've been provided, write an annual report based on {company}'s {fyear} 10-k report, format it into a pdf.
    Pay attention to the followings:
    - Explicitly explain your working plan before you kick off.
    - Use tools one by one for clarity, especially when asking for instructions. 
    - All your file operations should be done in "{work_dir}". 
    - Display any image in the chat once generated.
    - All the paragraphs should combine between 400 and 450 words, don't generate the pdf until this is explicitly fulfilled.
    """
)

try:
    assistant.chat(message, use_cache=True, max_turns=50, summary_method="last_msg")
except Exception as e:
    print(f"Operation failed: {str(e)}")
finally:
    if tracer_provider:
        tracer_provider.force_flush()
        tracer_provider.shutdown()

# --- PDF Display Section --- 
import io
import fitz
from PIL import Image

# Open the generated PDF and load the first page
pdf = fitz.open("../report/Microsoft_Annual_Report_2023.pdf")
page = pdf.load_page(0)
pix = page.get_pixmap()

# Convert the Pixmap to a PIL Image and display it
img = Image.open(io.BytesIO(pix.tobytes("png")))
display(img)
