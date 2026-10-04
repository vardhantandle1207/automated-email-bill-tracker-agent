"""CONCEPT 1: THE LLM (the agent's brain).

An LLM is just a web API. We send it the conversation so far and the list of
tools it may use. It sends back ONE new message. That message is either plain
text, or a request to call one or more tools.

Gemini and OpenRouter both understand the same "OpenAI-style" chat format, so
changing provider only changes the URL, the key and the model name.
"""

import os
import time

import requests

# Step 1: The providers we can talk to. Choose one with LLM_PROVIDER (default: gemini).
PROVIDERS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-3.6-flash",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "model_env": "OPENROUTER_MODEL",
        "default_model": "google/gemma-4-31b-it:free",
    },
}
BUSY = (429, 500, 502, 503, 504)  # "rate limited" or "server overloaded": worth retrying


def chat(messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, int]:
    """Send the conversation to the LLM. Returns (its reply message, tokens used)."""
    # Step 2: Read the provider settings and the API key from the environment.
    provider = PROVIDERS[os.getenv("LLM_PROVIDER", "gemini")]
    api_key = os.getenv(provider["key_env"])
    if not api_key:
        raise RuntimeError(f"Set {provider['key_env']} in your .env file (see .env.example)")

    # Step 3: Build the request: which model, the conversation, and the tools it may call.
    body = {"model": os.getenv(provider["model_env"], provider["default_model"]), "messages": messages}
    if tools:
        body["tools"] = tools

    # Step 4: Send it. If the provider is busy, wait and try again, a little longer each time
    #         (20s, 40s, 60s, 80s, 100s), then give up.
    for attempt in range(1, 7):
        response = requests.post(
            provider["url"], headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=180
        )
        if response.status_code not in BUSY or attempt == 6:
            break
        print(f"LLM is busy ({response.status_code}). Waiting {20 * attempt}s, then retry {attempt} of 5...")
        time.sleep(20 * attempt)
    if not response.ok:
        raise RuntimeError(f"LLM request failed ({response.status_code}): {response.text[:300]}")

    # Step 5: Hand back the reply message and how many tokens the call used.
    data = response.json()
    return data["choices"][0]["message"], (data.get("usage") or {}).get("total_tokens", 0)
