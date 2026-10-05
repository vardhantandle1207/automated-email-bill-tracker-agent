"""LLM client.

chat() posts the conversation and the tool descriptions to an OpenAI-compatible
chat endpoint and returns the model's reply. Gemini is the default. The
omniroute entry is wired in but has never been run against a real server.
"""

import os
import time

import requests

# chosen with LLM_PROVIDER (default: gemini)
PROVIDERS = {
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-3.6-flash",
    },
    "omniroute": {
        "url": "http://localhost:20128/v1/chat/completions",
        "url_env": "OMNIROUTE_URL",  # self-hosted, so the address can differ
        "key_env": "OMNIROUTE_API_KEY",
        "model_env": "OMNIROUTE_MODEL",
        "default_model": "auto",
    },
}
BUSY = (429, 500, 502, 503, 504)  # rate limited or overloaded


def chat(messages: list[dict], tools: list[dict] | None = None) -> tuple[dict, int]:
    """Send the conversation to the LLM. Returns (its reply message, tokens used)."""
    provider = PROVIDERS[os.getenv("LLM_PROVIDER", "gemini")]
    url = os.getenv(provider.get("url_env", ""), provider["url"])
    api_key = os.getenv(provider["key_env"])
    if not api_key:
        raise RuntimeError(f"Set {provider['key_env']} in your .env file (see .env.example)")

    body = {"model": os.getenv(provider["model_env"], provider["default_model"]), "messages": messages}
    if tools:
        body["tools"] = tools

    # when the provider is busy, wait 20s, 40s ... 100s between tries, then give up
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

    data = response.json()
    return data["choices"][0]["message"], (data.get("usage") or {}).get("total_tokens", 0)
