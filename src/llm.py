import os
import time
import json
import requests
from typing import Optional, Dict, Any


class GeminiClient:
    """Minimal Gemini API client using REST (no external SDK required).

    Env:
      - GOOGLE_API_KEY (required)
      - GEMINI_MODEL (default: gemini-1.5-flash)
      - LLM_TEMPERATURE (float, default: 0.2)
      - LLM_MAX_OUTPUT_TOKENS (int, default: 2048)
    """

    def __init__(self) -> None:
        self.api_key = os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise RuntimeError("GOOGLE_API_KEY is required for Gemini API")
        self.model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        try:
            self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        except Exception:
            self.temperature = 0.2
        try:
            self.max_tokens = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "2048"))
        except Exception:
            self.max_tokens = 2048
        self.base_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"

    def generate_markdown(self, prompt: str, system: Optional[str] = None, retries: int = 3, timeout: int = 30) -> str:
        headers = {"Content-Type": "application/json"}
        payload: Dict[str, Any] = {
            "contents": [
                {"role": "user", "parts": [{"text": prompt}]}
            ],
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": self.max_tokens,
                "topP": 0.95,
                "topK": 40,
            },
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        last_err: Optional[Exception] = None
        for i in range(retries):
            try:
                resp = requests.post(
                    self.base_url,
                    params={"key": self.api_key},
                    headers=headers,
                    data=json.dumps(payload),
                    timeout=timeout,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    # Response shape: candidates[0].content.parts[0].text
                    cands = data.get("candidates", [])
                    if not cands:
                        return ""
                    parts = (cands[0].get("content", {}) or {}).get("parts", [])
                    texts = [p.get("text", "") for p in parts]
                    return "\n".join(t for t in texts if t)
                else:
                    last_err = RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:200]}")
            except Exception as e:
                last_err = e
            time.sleep(1 + i * 2)
        if last_err:
            raise last_err
        return ""

