# --- Step 1: Data Preparation ---
from crewai.knowledge.source.csv_knowledge_source import CSVKnowledgeSource

# Load Arize trace data
knowledge_source = CSVKnowledgeSource(
    file_paths=['./data_export.csv'],  # Your trace data
    chunk_size=4000,
    chunk_overlap=200
)

# --- Step 2: Reranking Setup ---
import cohere
from crewai_tools import tool
import os

# Initialize Cohere client (for reranking only)
co = cohere.Client(os.getenv("COHERE_API_KEY"))

@tool
def rerank_results(query: str, documents: list) -> list:
    """Rerank documents using Cohere's semantic reranking"""
    response = co.rerank(
        query=query,
        documents=documents,
        top_n=5,
        model='rerank-english-v2.0'
    )
    return [doc.document['text'] for doc in response.results]

# --- Step 3: Core Agents with OpenAI Reasoning ---
from crewai import Agent
from langchain_openai import ChatOpenAI

# Initialize OpenAI LLM for reasoning
llm = ChatOpenAI(
    openai_api_key=os.getenv("OPENAI_API_KEY"),  # Explicit API key handling
    model="gpt-4",
    temperature=0.5,
    max_tokens=1000
)

# Trace Analyst - Finds relevant traces using OpenAI reasoning
trace_analyst = Agent(
    role="Trace Analyst",
    goal="Identify error patterns in Arize traces",
    tools=[knowledge_source.as_tool()],
    llm=llm,  # Uses OpenAI for reasoning
    verbose=True
)

# Reranker - Uses Cohere for ranking but OpenAI for task coordination
reranker = Agent(
    role="Reranker",
    goal="Reorder trace segments by semantic relevance",
    tools=[rerank_results],
    llm=llm,  # Uses OpenAI for reasoning
    verbose=True
)

# Diagnostic Agent - Generates final report using OpenAI
diagnostic_agent = Agent(
    role="Diagnostic Engineer",
    goal="Produce clear error analysis",
    llm=llm,  # Uses OpenAI for reasoning
    verbose=True
)

# --- Step 4: Task Pipeline ---
from crewai import Task

analysis_task = Task(
    description="Analyze traces for {error_type} errors between {start_date} and {end_date}",
    expected_output="List of relevant trace segments",
    agent=trace_analyst
)

rerank_task = Task(
    description="Rerank trace segments for query: {query}",
    expected_output="Top 5 most relevant trace segments",
    agent=reranker,
    context=[analysis_task]
)

diagnostic_task = Task(
    description="Generate diagnostic report for: {query}",
    expected_output="Clear root cause analysis with examples",
    agent=diagnostic_agent,
    context=[rerank_task]
)

# --- Step 5: Execution ---
from crewai import Crew
from datetime import datetime, timedelta

crew = Crew(
    agents=[trace_analyst, reranker, diagnostic_agent],
    tasks=[analysis_task, rerank_task, diagnostic_task],
    process="hierarchical"
)

# Run with your parameters
result = crew.kickoff({
    "error_type": "data_ingestion",
    "start_date": "2025-03-05",
    "end_date": "2025-03-10",
    "query": "Identify root causes of timeout errors during peak loads"
})

print("\n🔍 Reranked Analysis Results:")
print(result)