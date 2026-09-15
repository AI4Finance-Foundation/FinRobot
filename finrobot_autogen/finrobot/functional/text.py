from typing import Annotated

class TextUtils:

    def check_text_length(
        text: Annotated[str, "text to check"],
        min_length: Annotated[int, "minimum length of the text, default to 0"] = 0,
        max_length: Annotated[int, "maximum length of the text, default to 100000"] = 100000,
    ) -> str:
        """
        Check if the length of the text is exceeds than the maximum length.
        """
        length = len(text.split())
        if length > max_length:
            return f"Text length {length} exceeds the maximum length of {max_length}."
        elif length < min_length:
            return f"Text length {length} is less than the minimum length of {min_length}."
        else:
            return f"Text length {length} is within the expected range."