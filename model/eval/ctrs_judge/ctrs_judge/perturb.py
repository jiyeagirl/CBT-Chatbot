"""망가뜨린 대화(perturbation) 생성. 각 유형은 CTRS 한 항목의 점수 하락을 기대하고 만듦.

규칙 기반(API 불필요): repeat, no_empathy
LLM 재작성(API 필요):  lecture, directive, offtopic
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Callable

PROMPT_DIR = Path(__file__).resolve().parent.parent / "perturb_prompts"

# 유형 -> 점수 하락을 기대하는 항목
EXPECTED_DROP = {
    "repeat": "general_1_understanding",
    "no_empathy": "general_2_interpersonal_effectiveness",
    "directive": "general_3_collaboration",
    "lecture": "CBT_1_guided_discovery",
    "offtopic": "CBT_2_focus",
}
RULE_BASED = ("repeat", "no_empathy")
LLM_BASED = ("lecture", "directive", "offtopic")

_SENT_SPLIT = re.compile(r"(?<=[.?!])\s+")


def _therapist_idx(turns: list[dict]) -> list[int]:
    return [i for i, t in enumerate(turns) if t["role"] == "therapist"]


def repeat(turns: list[dict]) -> list[dict]:
    """세 번째 상담자 발화부터 두 번째 상담자 발화(첫 탐색 질문)를 그대로 반복함."""
    idx = _therapist_idx(turns)
    if len(idx) < 3:
        raise ValueError("상담자 발화가 3개 미만")
    anchor = turns[idx[1]]["text"]
    out = [dict(t) for t in turns]
    for i in idx[2:]:
        out[i]["text"] = anchor
    return out


def no_empathy(turns: list[dict]) -> list[dict]:
    """첫 인사를 제외하고 상담자 발화에서 마지막 문장만 남겨 공감, 반영 문장을 제거함."""
    idx = _therapist_idx(turns)
    out = [dict(t) for t in turns]
    for i in idx[1:]:
        sentences = _SENT_SPLIT.split(out[i]["text"].strip())
        out[i]["text"] = sentences[-1]
    return out


def parse_rewrite_output(text: str, n_expected: int) -> list[str]:
    s = text.strip()
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    arr = json.loads(s)
    if not isinstance(arr, list) or not all(isinstance(x, str) and x.strip() for x in arr):
        raise ValueError("문자열 배열이 아님")
    if len(arr) != n_expected:
        raise ValueError(f"상담자 발화 수 불일치: {len(arr)} != {n_expected}")
    return arr


def llm_rewrite(turns: list[dict], kind: str, complete: Callable[[str], str], attempts: int = 3) -> list[dict]:
    idx = _therapist_idx(turns)
    template = (PROMPT_DIR / "common.txt").read_text(encoding="utf-8")
    instruction = (PROMPT_DIR / f"{kind}.txt").read_text(encoding="utf-8").strip()
    dialogue = "\n".join(
        f"{'상담자' if t['role'] == 'therapist' else '내담자'}: {t['text']}" for t in turns)
    prompt = (template.replace("{n_therapist}", str(len(idx)))
              .replace("{instruction}", instruction).replace("{dialogue}", dialogue))
    last: Exception | None = None
    for _ in range(attempts):
        try:
            new = parse_rewrite_output(complete(prompt), len(idx))
            break
        except (ValueError, json.JSONDecodeError) as e:
            last = e
    else:
        raise RuntimeError(f"{kind} 재작성 실패: {last}")
    out = [dict(t) for t in turns]
    for i, text in zip(idx, new):
        out[i]["text"] = text.strip()
    out[idx[0]]["text"] = turns[idx[0]]["text"]  # 인사는 원문 유지
    return out


def make_variant(base: dict, kind: str, complete: Callable[[str], str] | None = None) -> dict:
    if kind in RULE_BASED:
        turns = {"repeat": repeat, "no_empathy": no_empathy}[kind](base["turns"])
    elif kind in LLM_BASED:
        if complete is None:
            raise ValueError(f"{kind}는 LLM 호출 함수가 필요함")
        turns = llm_rewrite(base["turns"], kind, complete)
    else:
        raise ValueError(f"알 수 없는 유형: {kind}")
    meta = {**base.get("meta", {}), "perturbation": kind, "base_id": base["conversation_id"],
            "expected_drop": EXPECTED_DROP[kind]}
    return {"conversation_id": f"{base['conversation_id']}__{kind}", "turns": turns, "meta": meta}


def as_original(base: dict) -> dict:
    return {**base, "meta": {**base.get("meta", {}), "perturbation": "original", "base_id": base["conversation_id"]}}
