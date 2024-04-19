from autogen import register_function, ConversableAgent
from .data_source import *
from .functional.coding import CodingUtils

from typing import List, Callable
from functools import wraps
from pandas import DataFrame


def stringify_output(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if isinstance(result, DataFrame):
            return result.to_string()
        else:
            return str(result)
    return wrapper


def register_toolkits(config: List[dict|Callable], caller: ConversableAgent, executor: ConversableAgent):

    """Register tools from a configuration list."""

    for tool in config:
        tool_dict = {"function": tool} if callable(tool) else tool
        if "function" not in tool_dict or not callable(tool_dict["function"]):
            raise ValueError("Function not found in tool configuration or not callable.")
        tool_function = tool_dict["function"]
        name = tool_dict.get("name", tool_function.__name__)
        description = tool_dict.get("description", tool_function.__doc__)
        register_function(
            stringify_output(tool_function),
            caller=caller,
            executor=executor,
            name=name,
            description=description,
        )

def register_code_writing(caller: ConversableAgent, executor: ConversableAgent):
    
        """Register code writing tools."""
    
        register_toolkits(
            [
                {
                    "function": CodingUtils.list_dir,
                    "name": "list_files",
                    "description": "List files in a directory.",
                },
                {
                    "function": CodingUtils.see_file,
                    "name": "see_file",
                    "description": "Check the contents of a chosen file.",
                },
                {
                    "function": CodingUtils.modify_code,
                    "name": "modify_code",
                    "description": "Replace old piece of code with new one.",
                },
                {
                    "function": CodingUtils.create_file_with_code,
                    "name": "create_file_with_code",
                    "description": "Create a new file with provided code.",
                },
            ],
            caller,
            executor,
        )

