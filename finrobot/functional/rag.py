from autogen.agentchat.contrib.retrieve_user_proxy_agent import RetrieveUserProxyAgent
from typing import Annotated


def get_rag_function(retrieve_config):

    def termination_msg(x):
        return (
            isinstance(x, dict)
            and "TERMINATE" == str(x.get("content", ""))[-9:].upper()
        )

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
            "Refined message which keeps the original meaning and can be used to retrieve content for code generation and question answering.",
        ],
        n_results: Annotated[int, "number of results"] = 3,
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

    return retrieve_content
