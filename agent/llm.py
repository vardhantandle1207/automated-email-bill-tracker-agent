"""CONCEPT 1: THE LLM (the agent's brain).

An LLM is just a web API. We send it the conversation so far and the list of
tools it may use. It sends back ONE new message. That message is either plain
text, or a request to call one or more tools.

Gemini and OmniRoute both understand the same "OpenAI-style" chat format, so
changing provider only changes the URL, the key and the model name.
(OmniRoute is a free gateway you run yourself: one endpoint in front of many LLMs.)
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
    "omniroute": {
        "url": "http://localhost:20128/v1/chat/completions",  # OmniRoute running on your machine
        "url_env": "OMNIROUTE_URL",                           # set this if yours runs somewhere else
        "key_env": "OMNIROUTE_API_KEY",
        "model_env": "OMNIROUTE_MODEL",
        "default_model": "auto",                              # let OmniRoute pick the model
    },
}
BUSY = (429, 500, 502, 503, 504)  # "rate limited" or "server overloaded": worth retrying


def chat(messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, int]:
    """Send the conversation to the LLM. Returns (its reply message, tokens used)."""
    # Step 2: Read the provider settings, its URL and the API key from the environment.
    provider = PROVIDERS[os.getenv("LLM_PROVIDER", "gemini")]
    url = os.getenv(provider.get("url_env", ""), provider["url"])
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
            url, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=180
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
