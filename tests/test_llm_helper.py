# tests/test_llm_helper.py
import pytest
from utils.llm_helper import _parse_json


def test_parse_json_direct():
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_parse_json_markdown_block():
    text = '```json\n{"a": 1}\n```'
    assert _parse_json(text) == {"a": 1}


def test_parse_json_embedded_object():
    """Fix 10: should extract first valid JSON from text with multiple braces."""
    text = 'Here is the result {"intent":"hello"} note {extra}'
    result = _parse_json(text)
    assert result == {"intent": "hello"}


def test_parse_json_greedy_not_used():
    """Fix 10: greedy regex would capture too much; non-greedy should find first valid."""
    text = '{"valid": true} and {"also_valid": false}'
    result = _parse_json(text)
    assert result == {"valid": True}


def test_parse_json_invalid_returns_none():
    assert _parse_json("no json here") is None


def test_parse_json_nested_braces():
    text = 'response: {"data": {"nested": true}} done'
    result = _parse_json(text)
    assert result is not None
    assert "data" in result
