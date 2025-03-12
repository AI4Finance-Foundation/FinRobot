import os
import cohere
import pandas as pd
from datetime import datetime, timedelta
from crewai import Agent, Task, Crew, Process
from langchain_openai import ChatOpenAI
from arize.exporter import ArizeExportClient
from crewai_tools import tool, BaseTool
from crewai.rag import AgenticRAG  # Import AgenticRAG
import glob

# Set API keys
os.environ['OPENAI_API_KEY'] = 'k-proj-y03sx6teEfNN93ExFQdCHfSPSW5LS62uYPvzwo7pHIPYfxM6Om6TIOLVMStUMui002RdU-KybBT3BlbkFJtR89zJ-IG9sAUp9nf0vHfc8GQH92iQgO_pQe1jSgbERrnIlam3Jj9-5R5L0uAdpb6suqsuShoA'
os.environ['COHERE_API_KEY'] = 'dVZ4jUijlT10sVOSlY06zmvZoaWqbE7C9KUTGpNW'
os.environ['TAVILY_API_KEY'] = 'YOUR_TAVILY_KEY'

# Export Arize traces to CSV
client = ArizeExportClient()
primary_df = client.export_model_to_df(
    space_id='U3BhY2U6MTY3MDA6Ni9MTg==',
    model_id='finrobot',
    environment='TRACING',
    start_time=datetime.now() - timedelta(days=1),
    end_time=datetime.now()
)
primary_df.to_csv('./data_export.csv', index=False)

# --- RAG Implementation ---
# Load all CSV files in current directory
csv_files = glob.glob("*.csv")
csv_data = []
for file in csv_files:
    df = pd.read_csv(file)
    csv_data.extend(df.to_dict('records'))

# Initialize RAG with OpenAI
rag_agent = AgenticRAG(data=csv_data, openai_api_key=os.getenv('OPENAI_API_KEY'))

# Create RAG tool for CrewAI
class RAGTool(BaseTool):
    name = "RAG Query Tool"
    description = "Retrieves and synthesizes information using RAG pipeline"
    
    def _run(self, query: str) -> list:
        # Return retrieved documents for reranking
        return rag_agent.retrieve(query)  # Assuming retrieve() returns documents

rag_tool = RAGTool()

# --- Reranking Setup ---
@tool
def rerank_results(query: str, documents: list) -> list:
    response = co.rerank(
        query=query,
        documents=[doc.get('text', '') for doc in documents],
        top_n=5,
        model='rerank-english-v2.0'
    )
    return [doc.document.text for doc in response.results]

# --- Agents ---
llm = ChatOpenAI(model="gpt-4", temperature=0)

trace_analyst = Agent(
    role="Trace Analyst",
    goal="Identify error patterns in system traces",
    tools=[rag_tool],  # Use RAG tool instead of CSV source
    llm=llm
)

reranker = Agent(
    role="Reranker",
    goal="Optimize relevance of retrieved traces",
    tools=[rerank_results],
    llm=llm
)

diagnostic_agent = Agent(
    role="Diagnostic Engineer",
    goal="Generate actionable error reports",
    llm=llm
)

# --- Task Pipeline ---
analysis_task = Task(
    description="Analyze traces for {error_type} errors between {start_time} and {end_time}",
    agent=trace_analyst
)

rerank_task = Task(
    description="Rerank trace segments for query: {query}",
    agent=reranker,
    context=[analysis_task]
)

diagnostic_task = Task(
    description="Generate diagnostic report for: {query}",
    agent=diagnostic_agent,
    context=[rerank_task]
)

# --- Execution ---
crew = Crew(
    agents=[trace_analyst, reranker, diagnostic_agent],
    tasks=[analysis_task, rerank_task, diagnostic_task],
    process=Process.hierarchical
)

result = crew.kickoff({
    "error_type": "data_ingestion",
    "start_time": str(datetime.now() - timedelta(days=1)),
    "end_time": str(datetime.now()),
    "query": "Identify root causes of timeout errors during peak loads"
})

print("🔍 Diagnostic Report:")
print(result)