from autogen.agentchat.contrib.retrieve_user_proxy_agent import RetrieveUserProxyAgent
from typing import Annotated


PROMPT_RAG_FUNC = """Below is the context retrieved from the required file based on your query.
If you can't answer the question with or without the current context, you should try using a more refined search query according to your requirements, or ask for more contexts.

Your current query is: {input_question}

Retrieved context is: {input_context}
"""


def get_rag_function(retrieve_config, description=""):

    def termination_msg(x):
        return (
            isinstance(x, dict)
            and "TERMINATE" == str(x.get("content", ""))[-9:].upper()
        )

    if "customized_prompt" not in retrieve_config:
        retrieve_config["customized_prompt"] = PROMPT_RAG_FUNC

    rag_assitant = RetrieveUserProxyAgent(
        name="RAG_Assistant",
        is_termination_msg=termination_msg,
        human_input_mode="NEVER",
        default_auto_reply="Reply `TERMINATE` if the task is done.",
        max_consecutive_auto_reply=3,
        retrieve_config=retrieve_config,
        code_execution_config=False,  # we don't want to execute code in this case.
        description="Assistant who has extra content retrieval power for solving difficult problems.",
    )

    def retrieve_content(
        message: Annotated[
            str,
            "Refined query message which keeps the original meaning and can be used to retrieve content for code generation or question answering from the provided files."
            "For example, 'YoY comparisons of profit margin', 'risk factors of NVIDIA in Q4', 'retrieve historical stock price data using YFinance'",
        ],
        n_results: Annotated[int, "Number of results to retrieve, default to 3"] = 3,
    ) -> str:

        rag_assitant.n_results = n_results  # Set the number of results to be retrieved.
        # Check if we need to update the context.
        update_context_case1, update_context_case2 = rag_assitant._check_update_context(
            message
        )
        if (
            update_context_case1 or update_context_case2
        ) and rag_assitant.update_context:
            rag_assitant.problem = (
                message
                if not hasattr(rag_assitant, "problem")
                else rag_assitant.problem
            )
            _, ret_msg = rag_assitant._generate_retrieve_user_reply(message)
        else:
            _context = {"problem": message, "n_results": n_results}
            ret_msg = rag_assitant.message_generator(rag_assitant, None, _context)
        return ret_msg if ret_msg else message

    if description:
        retrieve_content.__doc__ = description
    else:
        retrieve_content.__doc__ = "retrieve content from documents to assist question answering or code generation."
        docs = retrieve_config.get("docs_path", [])
        if docs:
            docs_str = "\n".join(docs if isinstance(docs, list) else [docs])
            retrieve_content.__doc__ += f"Availale Documents:\n{docs_str}"

    return retrieve_content, rag_assitant  # for debug use
