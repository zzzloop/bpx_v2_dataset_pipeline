"""Stateless, project-scoped DeepSeek translation for VLA task labels."""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
import urllib.error
import urllib.request

from bpx_v2_dataset_pipeline.collector.catalog import TranslationResult, translate_task

_API_URL = "https://api.deepseek.com/chat/completions"
_MODEL = "deepseek-v4-flash"
_SYSTEM_PROMPT = """Translate exactly one Chinese robot-manipulation instruction into a concise English imperative
for VLA training. Preserve object identity, color, quantity, source, destination, spatial relation, and hand.
Do not invent actions or scene details. Return JSON only as {\"english\": \"...\"}. Do not add explanations."""
_CHINESE_CHARACTER = re.compile(r"[\u3400-\u9fff]")


@dataclasses.dataclass(frozen=True, slots=True)
class TranslatorInfo:
    provider: str
    model: str
    enabled: bool


def _read_project_key(project_root: pathlib.Path) -> str:
    """Read only this project's .env.local without modifying process/global env."""
    path = project_root / ".env.local"
    if not path.is_file():
        return ""
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == "DEEPSEEK_API_KEY":
            return value.strip().strip('"').strip("'")
    return ""


class TaskTranslator:
    """Use deterministic presets first, then one isolated DeepSeek request."""

    def __init__(self, api_key: str, *, timeout_seconds: float = 15.0) -> None:
        self._api_key = api_key.strip()
        self._timeout_seconds = timeout_seconds

    @classmethod
    def from_project(cls, project_root: pathlib.Path) -> TaskTranslator:
        return cls(_read_project_key(project_root))

    @property
    def info(self) -> TranslatorInfo:
        return TranslatorInfo(provider="deepseek", model=_MODEL, enabled=bool(self._api_key))

    def translate(self, chinese: str) -> TranslationResult:
        local = translate_task(chinese)
        if local.english or not self._api_key:
            return local
        text = chinese.strip()
        if len(text) > 500:
            raise ValueError("中文指令不能超过 500 个字符")
        payload = {
            "model": _MODEL,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 128,
            "stream": False,
        }
        request = urllib.request.Request(
            _API_URL,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_seconds) as response:
                body = json.load(response)
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"DeepSeek API 返回 HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            raise RuntimeError("无法连接 DeepSeek API; 请检查工控机网络") from error
        try:
            content = body["choices"][0]["message"]["content"]
            english = json.loads(content)["english"].strip()
        except (KeyError, IndexError, TypeError, json.JSONDecodeError, AttributeError) as error:
            raise RuntimeError("DeepSeek API 返回了无法解析的翻译结果") from error
        if not english or len(english) > 400 or _CHINESE_CHARACTER.search(english):
            raise RuntimeError("DeepSeek API 返回的英文不符合任务标签约束")
        return TranslationResult(english=english, source="deepseek_v4_flash", confidence="model")
