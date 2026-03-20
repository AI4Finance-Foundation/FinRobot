from pydantic import BaseModel
from agents import Agent  # This now imports from openai-agents package

TAGLINE_PROMPT = (
    "You are an equity research analyst specializing in creating compelling executive taglines. "
    "Given financial data for a company, create a 3-sentence professional tagline that summarizes "
    "the company's financial position and outlook. Focus on strong fundamentals and valuation. "
    "Do not mention company ticker, use only the company name. Do not include projections or forecasts. "
    "Do not mention other companies. Be concise and professional."
)

class TaglineResponse(BaseModel):
    tagline: str

tagline_agent = Agent(
    name="TaglineAnalystAgent",
    instructions=TAGLINE_PROMPT,
    output_type=TaglineResponse,
)