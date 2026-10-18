#!/usr/bin/env python3
"""평가셋 구성: 멀쩡한 대화 20개 + 망가뜨린 대화 10개 = 30개 (API 불필요).

- 멀쩡한 20개: datasets/cactus_ko_sample20.jsonl 그대로
- 망가뜨린 10개: 위 20개 중 10개(한 칸 건너 하나씩)를 골라 5유형을 돌아가며 각 2개씩 망가뜨림
  (같은 원본은 한 번만 사용. 짝이 되는 원본이 20개 안에 있으므로 원본 대비 하락폭을 바로 비교 가능)
출력: datasets/perturbed_10.jsonl (망가진 10개), datasets/eval_set_30.jsonl (20 + 10)
LLM으로 다시 쓰고 싶으면 --llm-model gpt-6.1-sol (OPENAI_API_KEY 필요, 선택 사항)
"""
import argparse
from pathlib import Path

from ctrs_judge.conversation import load_conversations
from ctrs_judge.cactus_ko import write_jsonl
from ctrs_judge.perturb import EXPECTED_DROP, as_original, make_variant

HERE = Path(__file__).resolve().parent
ORDER = ["repeat", "no_empathy", "directive", "lecture", "offtopic"]

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--input", default=str(HERE / "datasets" / "cactus_ko_sample20.jsonl"))
ap.add_argument("--n-broken", type=int, default=10)
ap.add_argument("--llm-model", help="선택. 지정하면 lecture, directive, offtopic을 LLM으로 재작성")
a = ap.parse_args()

convs = load_conversations(a.input)
bases = [{"conversation_id": c.conversation_id, "turns": c.turns, "meta": c.meta} for c in convs]
if a.n_broken > len(bases):
    ap.error("망가뜨릴 수가 원본 수보다 많음")

complete = None
if a.llm_model:
    from ctrs_judge.client import JudgeClient, load_model_configs
    from run_eval import load_dotenv
    load_dotenv()
    client = JudgeClient(a.llm_model, {**load_model_configs()[a.llm_model], "max_output_tokens": 8000})
    complete = lambda p: client.complete(p).text  # noqa: E731

step = max(len(bases) // a.n_broken, 1)
picked = bases[::step][: a.n_broken]
broken = [make_variant(b, ORDER[k % len(ORDER)], complete) for k, b in enumerate(picked)]
originals = [as_original(b) for b in bases]

write_jsonl(broken, HERE / "datasets" / "perturbed_10.jsonl")
write_jsonl(originals + broken, HERE / "datasets" / "eval_set_30.jsonl")
for r in broken:
    print(f"{r['conversation_id']:32s} 기대 하락: {r['meta']['expected_drop']}")
print(f"멀쩡한 {len(originals)}개 + 망가진 {len(broken)}개 = {len(originals) + len(broken)}개 -> datasets/eval_set_30.jsonl")
