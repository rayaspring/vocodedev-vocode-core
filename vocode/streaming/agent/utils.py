from copy import deepcopy
import re
from typing import (
    Dict,
    Any,
    AsyncGenerator,
    AsyncIterable,
    Callable,
    List,
    Literal,
    Optional,
    TypeVar,
    Union,
)

from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import Choice, ChoiceDelta

# from openai.openai_object import OpenAIObject
from vocode.streaming.models.actions import FunctionCall, FunctionFragment
from vocode.streaming.models.events import Sender
from vocode.streaming.models.transcript import (
    ActionFinish,
    ActionStart,
    EventLog,
    Message,
    Transcript,
)

SENTENCE_ENDINGS = [".", "!", "?", "\n"]


async def collate_response_async(
    gen: AsyncIterable[Union[str, FunctionFragment]],
    sentence_endings: List[str] = SENTENCE_ENDINGS,
    get_functions: Literal[True, False] = False,
) -> AsyncGenerator[Union[str, FunctionCall], None]:
    sentence_endings_pattern = "|".join(map(re.escape, sentence_endings))
    list_item_ending_pattern = r"\n"
    buffer = ""
    function_name_buffer = ""
    function_args_buffer = ""
    prev_ends_with_money = False
    async for token in gen:
        if not token:
            continue
        if isinstance(token, str):
            if prev_ends_with_money and token.startswith(" "):
                yield buffer.strip()
                buffer = ""

            buffer += token
            possible_list_item = bool(re.match(r"^\d+[ .]", buffer))
            ends_with_money = bool(re.findall(r"\$\d+.$", buffer))
            if re.findall(
                list_item_ending_pattern
                if possible_list_item
                else sentence_endings_pattern,
                token,
            ):
                if not ends_with_money:
                    to_return = buffer.strip()
                    if to_return:
                        yield to_return
                    buffer = ""
            prev_ends_with_money = ends_with_money
        elif isinstance(token, FunctionFragment):
            function_name_buffer += token.name
            function_args_buffer += token.arguments
    to_return = buffer.strip()
    if to_return:
        yield to_return
    if function_name_buffer and get_functions:
        yield FunctionCall(name=function_name_buffer, arguments=function_args_buffer)


async def openai_get_tokens(gen) -> AsyncGenerator[Union[str, FunctionFragment], None]:
    async for event in gen:
        # choices = event.get("choices", [])
        choices: List[Choice] = event.choices
        if len(choices) == 0:
            continue
        choice: Choice= choices[0]
        if choice.finish_reason:
            break
        delta: ChoiceDelta= choice.delta
        # if "text" in delta and delta["text"] is not None:
        #     token = delta["text"]
        #     yield token
        if delta.content is not None:
            token = delta.content
            yield token
        # if "content" in delta and delta["content"] is not None:
        #     token = delta["content"]
        #     yield token
        # elif "function_call" in delta and delta["function_call"] is not None:
        elif delta.function_call is not None:
            yield FunctionFragment(
                name=delta.function_call.name,
                arguments=delta.function_call.arguments,
            )


def find_last_punctuation(buffer: str) -> Optional[int]:
    indices = [buffer.rfind(ending) for ending in SENTENCE_ENDINGS]
    if not indices:
        return None
    return max(indices)


def get_sentence_from_buffer(buffer: str):
    last_punctuation = find_last_punctuation(buffer)
    if last_punctuation:
        return buffer[: last_punctuation + 1], buffer[last_punctuation + 1 :]
    else:
        return None, None


def format_openai_chat_messages_from_transcript(
    transcript: Transcript, 
    prompt_preamble: Optional[str] = None,
    prompt_epilogue: Optional[str] = None
) -> List[dict]:
    chat_messages: List[Dict[str, Optional[Any]]] = (
        [{"role": "system", "content": prompt_preamble}] if prompt_preamble else []
    )

    # merge consecutive bot messages
    new_event_logs: List[EventLog] = []
    idx = 0
    while idx < len(transcript.event_logs):
        bot_messages_buffer: List[Message] = []
        current_log = transcript.event_logs[idx]
        while isinstance(current_log, Message) and current_log.sender == Sender.BOT:
            bot_messages_buffer.append(current_log)
            idx += 1
            try:
                current_log = transcript.event_logs[idx]
            except IndexError:
                break
        if bot_messages_buffer:
            merged_bot_message = deepcopy(bot_messages_buffer[-1])
            merged_bot_message.text = " ".join(
                event_log.text for event_log in bot_messages_buffer
            )
            new_event_logs.append(merged_bot_message)
        else:
            new_event_logs.append(current_log)
            idx += 1

    for event_log in new_event_logs:
        if isinstance(event_log, Message):
            chat_messages.append(
                {
                    "role": "assistant" if event_log.sender == Sender.BOT else "user",
                    "content": event_log.text,
                }
            )
        elif isinstance(event_log, ActionStart):
            chat_messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "function_call": {
                        "name": event_log.action_type,
                        "arguments": event_log.action_input.params.json(),
                    },
                }
            )
        elif isinstance(event_log, ActionFinish):
            chat_messages.append(
                {
                    "role": "function",
                    "name": event_log.action_type,
                    "content": event_log.action_output.response.json(),
                }
            )
    if prompt_epilogue:
        chat_messages.append(
            {
                "role": "system", 
                "content": prompt_epilogue,
            }
        )

    return chat_messages


def vector_db_result_to_openai_chat_message(vector_db_result):
    return {"role": "user", "content": vector_db_result}

def replace_map_symbols(message, symbol_map):
    """
    Replace symbols in the message based on the provided symbol_map.

    Parameters:
    - message (str): The input message containing symbols to be replaced.
    - symbol_map (dict): A dictionary mapping symbol keys to their corresponding values.

    Returns:
    - str: The message with symbols replaced based on the provided symbol_map.
    """
    import re

    pattern = re.compile("|".join(re.escape(key) for key in symbol_map.keys()))
    return pattern.sub(lambda match: symbol_map[match.group(0)], message)