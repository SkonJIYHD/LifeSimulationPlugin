# utils/llm_helper.py
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

_JSON_BLOCK_RE = re.compile(r'```(?:json)?\s*([\s\S]*?)```', re.IGNORECASE)


def _find_json_candidates(text: str) -> list[str]:
    """Find all potential JSON object substrings using brace-depth tracking."""
    candidates = []
    i = 0
    while i < len(text):
        if text[i] == '{':
            depth = 0
            in_string = False
            escape = False
            for j in range(i, len(text)):
                ch = text[j]
                if escape:
                    escape = False
                    continue
                if ch == '\\' and in_string:
                    escape = True
                    continue
                if ch == '"' and not escape:
                    in_string = not in_string
                    continue
                if not in_string:
                    if ch == '{':
                        depth += 1
                    elif ch == '}':
                        depth -= 1
                        if depth == 0:
                            candidates.append(text[i:j + 1])
                            break
            i = j + 1 if depth == 0 else i + 1
        else:
            i += 1
    return candidates


def _parse_json(text: str) -> dict | None:
    # 1. 直接解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    # 2. 提取 ```json ... ``` 块
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # 3. 提取所有 {...} 块（支持嵌套），尝试每个作为 JSON
    for candidate in _find_json_candidates(text):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _validate(data: dict, schema: dict) -> bool:
    required = schema.get("required", [])
    props = schema.get("properties", {})
    for key in required:
        if key not in data:
            return False
        expected_type = props.get(key, {}).get("type")
        if expected_type == "array" and not isinstance(data[key], list):
            return False
        if expected_type == "string" and not isinstance(data[key], str):
            return False
        if expected_type == "number" and not isinstance(data[key], (int, float)):
            return False
    return True


async def generate_json(
    ctx: Any,
    prompt: list[dict],
    schema: dict,
    budget_key: str,
    budget: Any,
    timeout: float = 30.0,
    max_retries: int = 2,
    max_repair_attempts: int = 2,
) -> dict | None:
    """
    调用 LLM 生成 JSON。返回 None 表示彻底失败，调用方必须处理 fallback。
    - 检查 budget 预算
    - 带 timeout 的 LLM 调用
    - JSON 解析（支持 markdown 代码块）
    - schema 校验，失败时最多 repair max_repair_attempts 次
    - 指数退避重试
    """
    if not budget.can_llm_call(budget_key):
        logger.warning("LLM budget exceeded for %s", budget_key)
        return None

    current_prompt = list(prompt)
    repair_attempts = 0

    for attempt in range(max_retries + 1):
        try:
            result = await asyncio.wait_for(
                ctx.llm.generate(prompt=current_prompt),
                timeout=timeout,
            )
            if not result.get("success"):
                logger.warning("LLM returned success=False, attempt %d", attempt + 1)
                continue

            data = _parse_json(result.get("response", ""))
            if data is None:
                logger.warning("JSON parse failed, attempt %d", attempt + 1)
                continue

            if _validate(data, schema):
                budget.record_llm(budget_key)
                return data

            # schema 校验失败，尝试修复
            if repair_attempts < max_repair_attempts:
                repair_attempts += 1
                missing = [k for k in schema.get("required", []) if k not in data]
                current_prompt = current_prompt + [
                    {"role": "assistant", "content": result["response"]},
                    {"role": "user", "content":
                     f"Your response is missing required fields: {missing}. "
                     f"Please return a valid JSON with all required fields."},
                ]
                continue

            logger.warning("Schema validation failed after %d repair attempts", repair_attempts)
            return None

        except asyncio.TimeoutError:
            logger.warning("LLM timeout attempt %d/%d for %s", attempt + 1, max_retries + 1, budget_key)
        except asyncio.CancelledError:
            raise  # 不吞 CancelledError
        except Exception as e:
            logger.error("LLM error: %s", e, exc_info=True)

        if attempt < max_retries:
            await asyncio.sleep(2 ** attempt)

    return None
