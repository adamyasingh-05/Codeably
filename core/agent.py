"""
core/agent.py
The main agent loop — sends messages to the AI, runs tools, loops until done.
Works with any provider via the providers module.
"""

import json
from core.tools.index import TOOL_DEFS, execute_tool

MAX_TURNS = 50

def run_agent(task: str, client, db=None, stream_cb=None):
    """
    Run the agent loop.
    - task: user's task string
    - client: a provider client with a .chat() method
    - db: optional database connection
    - stream_cb: optional callback(event_dict) for streaming output to UI
    Returns final summary string.
    """
    messages = [{"role": "user", "content": task}]
    system = (
        "You are Codeably, an autonomous coding agent. "
        "You have tools available. Use them to complete the user's task. "
        "Think step by step. When done, call the `done` tool with a summary. "
        "IMPORTANT: Before calling delete_file or delete_files_bulk, you MUST call confirm_delete first. "
        "For AI-powered tools (explain_code, review_code, etc.) that return __AI_TASK__: "
        "treat the content after __AI_TASK__: as a prompt and answer it directly."
    )

    for turn in range(MAX_TURNS):
        response = client.chat(
            system=system,
            messages=messages,
            tools=TOOL_DEFS,
        )

        # collect text + tool calls
        text_parts = []
        tool_calls = []

        for block in response.get("content", []):
            if block["type"] == "text":
                text_parts.append(block["text"])
            elif block["type"] == "tool_use":
                tool_calls.append(block)

        text = "\n".join(text_parts).strip()
        if text and stream_cb:
            stream_cb({"type": "text", "text": text})

        # append assistant message
        messages.append({"role": "assistant", "content": response["content"]})

        if not tool_calls:
            # no more tools — done
            return text or "Task complete."

        # run tools
        tool_results = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_input = tc.get("input", {})

            if stream_cb:
                stream_cb({"type": "tool_start", "tool": tool_name, "input": tool_input})

            result = execute_tool(tool_name, tool_input, db=db, ai_client=client)

            # AI tools: the agent answers inline
            if isinstance(result, str) and result.startswith("__AI_TASK__:"):
                ai_prompt = result[len("__AI_TASK__:"):]
                ai_resp = client.chat(
                    system="You are a helpful coding assistant.",
                    messages=[{"role": "user", "content": ai_prompt}],
                    tools=[]
                )
                result = "".join(
                    b["text"] for b in ai_resp.get("content", []) if b["type"] == "text"
                )

            if stream_cb:
                stream_cb({"type": "tool_end", "tool": tool_name, "result": str(result)})

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tc["id"],
                "content": str(result),
            })

            # stop if done
            if tool_name == "done":
                return str(result)

        messages.append({"role": "user", "content": tool_results})

    return "Max turns reached."
