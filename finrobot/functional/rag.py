from autogen.agentchat.contrib.retrieve_user_proxy_agent import RetrieveUserProxyAgent
from typing import Annotated
import agentops

# Initialize AgentOps
agentops.init('<INSERT YOUR API KEY HERE>')

PROMPT_RAG_FUNC = """Below is the context retrieved from the required file based on your query.
If you can't answer the question with or without the current context, you should try using a more refined search query according to your requirements, or ask for more contexts.

Your current query is: {input_question}

Retrieved context is: {input_context}
"""

@agentops.record_function('get_rag_function')
def get_rag_function(retrieve_config, description=""):

    def termination_msg(x):
        return (
            isinstance(x, dict)
            and "TERMINATE" == str(x.get("content", ""))[-9:].upper()
        )

    if "customized_prompt" not in retrieve_config:
        retrieve_config["customized_prompt"] = PROMPT_RAG_FUNC

    rag_assistant = RetrieveUserProxyAgent(
        name="RAG_Assistant",
        is_termination_msg=termination_msg,
        human_input_mode="NEVER",
        default_auto_reply="Reply `TERMINATE` if the task is done.",
        max_consecutive_auto_reply=3,
        retrieve_config=retrieve_config,
        code_execution_config=False,  # we don't want to execute code in this case.
        description="Assistant who has extra content retrieval power for solving difficult problems.",
    )

    @agentops.record_function('retrieve_content')
    def retrieve_content(
        message: Annotated[
            str,
            "Refined query message which keeps the original meaning and can be used to retrieve content for code generation or question answering from the provided files."
            "For example, 'YoY comparisons of profit margin', 'risk factors of NVIDIA in Q4', 'retrieve historical stock price data using YFinance'",
        ],
        n_results: Annotated[int, "Number of results to retrieve, default to 3"] = 3,
    ) -> str:

        rag_assistant.n_results = n_results  # Set the number of results to be retrieved.
        # Check if we need to update the context.
        update_context_case1, update_context_case2 = rag_assistant._check_update_context(
            message
        )
        if (
            update_context_case1 or update_context_case2
        ) and rag_assistant.update_context:
            rag_assistant.problem = (
                message
                if not hasattr(rag_assistant, "problem")
                else rag_assistant.problem
            )
            _, ret_msg = rag_assistant._generate_retrieve_user_reply(message)
        else:
            _context = {"problem": message, "n_results": n_results}
            ret_msg = rag_assistant.message_generator(rag_assistant, None, _context)
        return ret_msg if ret_msg else message

    if description:
        retrieve_content.__doc__ = description
    else:
        retrieve_content.__doc__ = "retrieve content from documents to assist question answering or code generation."
        docs = retrieve_config.get("docs_path", [])
        if docs:
            docs_str = "\n".join(docs if isinstance(docs, list) else [docs])
            retrieve_content.__doc__ += f"Available Documents:\n{docs_str}"

    return retrieve_content, rag_assistant  # for debug use

# Add this at the end of your script or in your main execution point
agentops.end_session('Success')