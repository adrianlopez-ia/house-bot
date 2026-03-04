"""Robust JSON extraction from LLM text responses.

LLMs frequently wrap valid JSON in markdown fences or add preamble text.
These helpers strip that away and fall back to substring extraction.
"""
from __future__ import annotations

import json
import logging
from typing import Union

logger = logging.getLogger(__name__)


def parse_json_array(text: str) -> list:
    return _parse(text, list, "array")


def parse_json_object(text: str) -> dict:
    return _parse(text, dict, "object")


def _parse(text: str, expected_type: type, label: str) -> Union[list, dict]:
    text = _strip_fences(text)
    try:
        result = json.loads(text)
        if isinstance(result, expected_type):
            return result
    except json.JSONDecodeError:
        pass

    open_char, close_char = ("[", "]") if expected_type is list else ("{", "}")
    start = text.find(open_char)
    end = text.rfind(close_char)
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    logger.warning("Failed to parse JSON %s from LLM response (len=%d)", label, len(text))
    return expected_type()


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        else:
            text = text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()
