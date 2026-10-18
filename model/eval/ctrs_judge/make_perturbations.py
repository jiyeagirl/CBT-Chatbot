#!/usr/bin/env python3
"""원본 N개와 망가뜨린 버전을 하나의 jsonl로 만듦(run_eval.py 입력 형식 그대로).

  python make_perturbations.py                         # 규칙 기반 2종(repeat, no_empathy), API 불필요
  python make_perturbations.py --types lecture directive offtopic --llm-model gpt-6.1-sol   # OPENAI_API_KEY 필요
같은 --out에 다시 실행하면 이미 있는 id는 건너뛰고 없는 것만 추가함.
"""
import argparse
import json
from pathlib import Path

from ctrs_judge.client import JudgeClient, load_model_configs
from ctrs_judge.conversation import load_conversations
from ctrs_judge.perturb import EXPECTED_DROP, LLM_BASED, as_original, make_variant
from run_eval import load_dotenv

HERE = Path(__file__).resolve().parent

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--input", default=str(HERE / "datasets" / "cactus_ko_sample20.jsonl"))
ap.add_argument("--n", type=int, default=10, help="원본 대화 수(입력 앞에서부터)")
ap.add_argument("--types", nargs="+", default=["repeat", "no_empathy"], choices=list(EXPECTED_DROP))
ap.add_argument("--llm-model", default="gpt-6.1-sol", help="LLM 재작성에 쓸 models.json 키")
ap.add_argument("--out", default=str(HERE / "datasets" / "perturbed_10.jsonl"))
a = ap.parse_args()

out = Path(a.out)
existing = {json.loads(l)["conversation_id"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()} \
    if out.exists() else set()
complete = None
if any(t in LLM_BASED for t in a.types):
    load_dotenv()
    cfg = {**load_model_configs()[a.llm_model], "max_output_tokens": 8000}
    client = JudgeClient(a.llm_model, cfg)
    complete = lambda p: client.complete(p).text  # noqa: E731

added = 0
with open(out, "a", encoding="utf-8") as f:
    for conv in load_conversations(a.input, a.n):
        base = {"conversation_id": conv.conversation_id, "turns": conv.turns, "meta": conv.meta}
        rows = [as_original(base)] + [make_variant(base, t, complete) for t in a.types
                                     if f"{conv.conversation_id}__{t}" not in existing]
        for r in rows:
            if r["conversation_id"] not in existing:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
                existing.add(r["conversation_id"])
                added += 1
print(f"추가 {added}줄 -> {out}")
