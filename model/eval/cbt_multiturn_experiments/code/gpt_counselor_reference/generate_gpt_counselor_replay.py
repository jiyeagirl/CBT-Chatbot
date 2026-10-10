"""R002의 고정 내담자 발화로 GPT 상담자를 진단한다. GPU와 재시도는 사용하지 않는다."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
import time
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from dotenv import load_dotenv
import certifi

from cbt_harness import repetition_candidates


ROOT = Path(__file__).resolve().parents[1]
MODEL = "gpt-6-luna"
CASES = ROOT / "outputs/replay_diagnostic_train_3_v2_full_inputs_20261006/cases.json"
PROMPT = ROOT / "qwen3_8b_qlora/system_prompt.txt"
BASELINE = ROOT / "outputs/prompt_ablation_3cases_20261006/original/sessions_unblinded.jsonl"


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    load_dotenv(ROOT / ".env.local", override=False)
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("API key is not configured.")
    endpoint = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    if endpoint != "https://api.openai.com/v1":
        raise SystemExit("Custom API endpoint requires separate confirmation.")
    case = next(row for row in json.loads(CASES.read_text()) if row["case_id"] == "R002")
    baseline = next(row for row in map(json.loads, BASELINE.read_text().splitlines())
                    if row["case_id"] == "R002" and row["condition"] == "tuned")
    assert len(case["client_turns"]) == len(baseline["turns"]) == 14
    assert case["client_turns"] == [row["client_text"] for row in baseline["turns"]]
    output = ROOT / "outputs" / ("gpt_luna_counselor_R002_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    output.mkdir(parents=True, exist_ok=False)
    manifest = {
        "status": "running", "model": MODEL, "case_id": "R002",
        "source_session_id": case["source_session_id"], "evaluation_eligible": False,
        "training_split": case["training_split"], "fixed_client_replay": True,
        "harness_plan_state": False, "runpod_used": False, "drive_upload": False,
        "reasoning_effort": "none", "max_output_tokens": 384,
        "sampling": "API default; not matched to Qwen greedy decoding",
        "retries": 0, "prompt_sha256": hashlib.sha256(PROMPT.read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
        "baseline_path": str(BASELINE), "completed_turns": 0,
    }
    save_json(output / "manifest.json", manifest)
    history = [{"role": "developer", "content": PROMPT.read_text()}]
    turns = []
    print("Output: " + str(output), flush=True)
    for index, client_text in enumerate(case["client_turns"], start=1):
        history.append({"role": "user", "content": client_text})
        payload = {"model": MODEL, "input": history, "reasoning": {"effort": "none"},
                   "max_output_tokens": 384, "store": False}
        request = Request(endpoint + "/responses", data=json.dumps(payload).encode(),
                          headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                          method="POST")
        started = time.monotonic()
        try:
            with urlopen(request, timeout=60, context=ssl.create_default_context(cafile=certifi.where())) as response:
                raw = json.load(response)
        except Exception as error:
            manifest.update(status="failed", error_type=type(error).__name__)
            reason = getattr(error, "reason", None)
            if reason is not None:
                manifest["transport_reason_type"] = type(reason).__name__
                manifest["transport_errno"] = getattr(reason, "errno", None)
                manifest["certificate_verify_message"] = getattr(reason, "verify_message", None)
            if isinstance(error, HTTPError):
                manifest["http_status"] = error.code
            save_json(output / "manifest.json", manifest)
            print(f"Stopped safely: {type(error).__name__}; no retry", flush=True)
            print(json.dumps({name: value for name, value in manifest.items()
                              if name.startswith("transport_") or name == "certificate_verify_message"}), flush=True)
            return
        response_text = "\n".join(part["text"] for message in raw.get("output", [])
                                  if message.get("type") == "message"
                                  for part in message.get("content", []) if part.get("type") == "output_text")
        row = {"turn_index": index, "client_text": client_text, "response": response_text,
               "returned_model": raw.get("model"), "status": raw.get("status"),
               "seconds": round(time.monotonic() - started, 3), "usage": raw.get("usage", {}),
               "repetition_candidates": repetition_candidates(response_text, history),
               "incomplete_details": raw.get("incomplete_details")}
        turns.append(row)
        with (output / "turns.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        manifest["completed_turns"] = index
        save_json(output / "manifest.json", manifest)
        print(f"Turn {index}/14: {row['status']}", flush=True)
        if raw.get("status") != "completed" or not response_text.strip():
            manifest["status"] = "incomplete"
            save_json(output / "manifest.json", manifest)
            return
        history.append({"role": "assistant", "content": response_text})
    input_tokens = sum(row["usage"].get("input_tokens", 0) for row in turns)
    cached_tokens = sum(row["usage"].get("input_tokens_details", {}).get("cached_tokens", 0) for row in turns)
    output_tokens = sum(row["usage"].get("output_tokens", 0) for row in turns)
    estimate = ((input_tokens - cached_tokens) * 0.10 + cached_tokens * 0.01 + output_tokens * 0.50) / 1_000_000
    manifest.update(status="complete", input_tokens=input_tokens, cached_tokens=cached_tokens,
                    output_tokens=output_tokens, estimated_cost_usd=estimate,
                    pricing_source="https://developers.openai.com/api/docs/models/gpt-6-luna")
    save_json(output / "manifest.json", manifest)
    save_json(output / "session.json", {"case": case, "messages": history, "turns": turns})
    lines = ["# R002 상담자 비교: Qwen-CBT vs GPT-6 Luna", "",
             "같은 기본 프롬프트·고정 내담자 발화 14개. 추가 계획/상태 하네스 없음.", "",
             "Qwen은 기존 생성 결과, GPT는 이번 API 생성 결과입니다. 원본 내담자 발화는 새 상담자 응답과 어긋날 수 있습니다.", "",
             "학습 자료 재사용 진단이며 일반화·CTRS 평가가 아닙니다. 샘플링·토크나이저·추론 환경은 동일하지 않습니다.", "",
             f"API 사용량: 입력 {input_tokens}, 캐시 {cached_tokens}, 출력 {output_tokens} 토큰. 추정 비용 ${estimate:.6f}.", ""]
    for gpt_turn, qwen_turn in zip(turns, baseline["turns"]):
        lines.extend([f"## 대화쌍 {gpt_turn['turn_index']}", "", "내담자: " + gpt_turn["client_text"], "",
                      "### 기존 Qwen-CBT", "", qwen_turn["response"], "",
                      "### GPT-6 Luna", "", gpt_turn["response"], ""])
    (output / "COMPARISON.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"status": "complete", "turns": len(turns), "estimated_cost_usd": estimate}), flush=True)


if __name__ == "__main__":
    main()
