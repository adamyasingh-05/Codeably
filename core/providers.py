"""
core/providers.py
Unified provider interface. Each provider wraps its SDK into:
  client.chat(system, messages, tools) -> {content: [...]}

Tool calling is fully supported for: Anthropic, OpenAI, Groq
Text-only mode (no tool calls) for: Gemini, Mistral, Cohere, Ollama, OpenRouter
  — these providers will still work but the agent will respond in text only
    and won't be able to call tools autonomously.
"""

import json, os, urllib.request, urllib.error

# ── Base ─────────────────────────────────────────────────────────────────────

class BaseClient:
    supports_tools = False  # subclasses override

    def chat(self, system: str, messages: list, tools: list) -> dict:
        raise NotImplementedError

# ── Anthropic ─────────────────────────────────────────────────────────────────

class AnthropicClient(BaseClient):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def chat(self, system, messages, tools):
        kwargs = dict(model=self.model, max_tokens=8096,
                      system=system, messages=messages)
        if tools:
            kwargs["tools"] = tools
        r = self.client.messages.create(**kwargs)
        return {"content": [b.model_dump() for b in r.content]}

# ── OpenAI ────────────────────────────────────────────────────────────────────

class OpenAIClient(BaseClient):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "gpt-4o"):
        import openai
        self.client = openai.OpenAI(api_key=api_key)
        self.model = model

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _convert_messages_for_openai(messages)
        kwargs = dict(model=self.model, messages=msgs, max_tokens=4096)
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"]
            }} for t in tools]
            kwargs["tool_choice"] = "auto"
        r = self.client.chat.completions.create(**kwargs)
        msg = r.choices[0].message
        content = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})
        if msg.tool_calls:
            for tc in msg.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments)
                })
        return {"content": content}

# ── Groq ──────────────────────────────────────────────────────────────────────

class GroqClient(BaseClient):
    supports_tools = True

    def __init__(self, api_key: str, model: str = "llama-3.3-70b-versatile"):
        from groq import Groq
        self.client = Groq(api_key=api_key)
        self.model = model

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _convert_messages_for_openai(messages)
        kwargs = dict(model=self.model, messages=msgs, max_tokens=4096)
        if tools:
            kwargs["tools"] = [{"type": "function", "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"]
            }} for t in tools]
            kwargs["tool_choice"] = "auto"
        r = self.client.chat.completions.create(**kwargs)
        msg = r.choices[0].message
        content = []
        if msg.content:
            content.append({"type": "text", "text": msg.content})
        if msg.tool_calls:
            for tc in msg.tool_calls:
                content.append({
                    "type": "tool_use",
                    "id": tc.id,
                    "name": tc.function.name,
                    "input": json.loads(tc.function.arguments or "{}")
                })
        return {"content": content}

# ── Gemini ─────────────────────────────────────────────────────────────────────

class GeminiClient(BaseClient):
    supports_tools = False  # Gemini tool format is different; text-only for now

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        self.genai = genai
        self.model_name = model

    def chat(self, system, messages, tools):
        history = []
        for m in messages[:-1]:
            role = "model" if m["role"] == "assistant" else "user"
            content = m["content"] if isinstance(m["content"], str) else json.dumps(m["content"])
            history.append({"role": role, "parts": [content]})
        last = messages[-1]["content"]
        if not isinstance(last, str):
            last = json.dumps(last)
        model = self.genai.GenerativeModel(self.model_name)
        chat = model.start_chat(history=history)
        r = chat.send_message(f"{system}\n\n{last}")
        return {"content": [{"type": "text", "text": r.text}]}

# ── Mistral ───────────────────────────────────────────────────────────────────

class MistralClient(BaseClient):
    supports_tools = False  # text-only wrapper

    def __init__(self, api_key: str, model: str = "mistral-large-latest"):
        from mistralai import Mistral
        self.client = Mistral(api_key=api_key)
        self.model = model

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _flatten_messages(messages)
        r = self.client.chat.complete(model=self.model, messages=msgs, max_tokens=4096)
        return {"content": [{"type": "text", "text": r.choices[0].message.content}]}

# ── Cohere ────────────────────────────────────────────────────────────────────

class CohereClient(BaseClient):
    supports_tools = False  # text-only wrapper

    def __init__(self, api_key: str, model: str = "command-r-plus"):
        import cohere
        self.client = cohere.ClientV2(api_key=api_key)
        self.model = model

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _flatten_messages(messages)
        r = self.client.chat(model=self.model, messages=msgs, max_tokens=4096)
        return {"content": [{"type": "text", "text": r.message.content[0].text}]}

# ── Ollama (local) ────────────────────────────────────────────────────────────

class OllamaClient(BaseClient):
    supports_tools = False  # text-only; Ollama tool support varies by model

    def __init__(self, model: str = "llama3.2", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _flatten_messages(messages)
        payload = json.dumps({"model": self.model, "messages": msgs, "stream": False}).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/chat", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return {"content": [{"type": "text", "text": data["message"]["content"]}]}

# ── OpenRouter ────────────────────────────────────────────────────────────────

class OpenRouterClient(BaseClient):
    supports_tools = False  # varies by underlying model; use text-only for safety

    def __init__(self, api_key: str, model: str = "anthropic/claude-sonnet-4-6"):
        self.api_key = api_key
        self.model = model

    def chat(self, system, messages, tools):
        msgs = [{"role": "system", "content": system}] + _flatten_messages(messages)
        payload = json.dumps({"model": self.model, "messages": msgs, "max_tokens": 4096}).encode()
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/codeably",
                "X-Title": "Codeably"
            },
            method="POST")
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        return {"content": [{"type": "text", "text": data["choices"][0]["message"]["content"]}]}

# ── Message converters ────────────────────────────────────────────────────────

def _flatten_messages(messages: list) -> list:
    """Convert Anthropic-style messages (with tool_result content lists) to plain role/content dicts."""
    result = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            result.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Flatten tool results and text blocks into one string
            parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block["text"])
                    elif block.get("type") == "tool_result":
                        parts.append(f"[tool result: {block.get('content', '')}]")
                    elif block.get("type") == "tool_use":
                        parts.append(f"[calling tool: {block.get('name')}]")
            result.append({"role": role, "content": "\n".join(parts)})
        else:
            result.append({"role": role, "content": str(content)})
    return result

def _convert_messages_for_openai(messages: list) -> list:
    """Convert Anthropic-style messages to OpenAI format, including tool results."""
    result = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        if isinstance(content, str):
            result.append({"role": role, "content": content})
        elif isinstance(content, list):
            # Check if this is a tool_result message (user turn with results)
            tool_results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"]
            tool_uses = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_use"]
            text_blocks = [b for b in content if isinstance(b, dict) and b.get("type") == "text"]

            if tool_uses:
                # Assistant message with tool calls
                text = " ".join(b["text"] for b in text_blocks)
                tool_calls = [{
                    "id": b["id"],
                    "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input", {}))}
                } for b in tool_uses]
                msg = {"role": "assistant"}
                if text: msg["content"] = text
                msg["tool_calls"] = tool_calls
                result.append(msg)
            elif tool_results:
                # User turn with tool results — one message per result
                for tr in tool_results:
                    result.append({
                        "role": "tool",
                        "tool_call_id": tr["tool_use_id"],
                        "content": str(tr.get("content", ""))
                    })
            else:
                # Plain text blocks
                text = " ".join(b.get("text", "") for b in text_blocks if isinstance(b, dict))
                result.append({"role": role, "content": text})
        else:
            result.append({"role": role, "content": str(content)})
    return result

# ── Factory ───────────────────────────────────────────────────────────────────

PROVIDERS = {
    "anthropic":   AnthropicClient,
    "openai":      OpenAIClient,
    "groq":        GroqClient,
    "gemini":      GeminiClient,
    "mistral":     MistralClient,
    "cohere":      CohereClient,
    "ollama":      OllamaClient,
    "openrouter":  OpenRouterClient,
}

PROVIDER_MODELS = {
    "anthropic":  ["claude-sonnet-4-6", "claude-opus-4-6", "claude-haiku-4-5-20251001"],
    "openai":     ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o3", "o4-mini"],
    "groq":       ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768"],
    "gemini":     ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro"],
    "mistral":    ["mistral-large-latest", "mistral-medium", "codestral-latest"],
    "cohere":     ["command-r-plus", "command-r"],
    "ollama":     ["llama3.2", "codellama", "deepseek-coder", "qwen2.5-coder"],
    "openrouter": ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "google/gemini-pro"],
}

# Which providers fully support tool calling
TOOL_CAPABLE_PROVIDERS = {"anthropic", "openai", "groq"}

def get_client(provider: str, api_key: str = None, model: str = None, **kwargs) -> BaseClient:
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown provider: {provider}. Choose from: {list(PROVIDERS)}")
    cls = PROVIDERS[provider]
    default_model = PROVIDER_MODELS[provider][0]
    if provider == "ollama":
        return cls(model=model or default_model, **kwargs)
    return cls(api_key=api_key, model=model or default_model, **kwargs)
