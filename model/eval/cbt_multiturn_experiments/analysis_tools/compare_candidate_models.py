"""Gemma 4 / Qwen3.5 진단 결과를 검증하고 사례별 비교 노트를 만든다."""

import hashlib
import json
from pathlib import Path

from compare_question_prompt_experiment import read_sessions, summarize


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/candidate_models_20261007"
LABELS = {"qwen35_9b": "Qwen3.5-9B", "gemma4_31b": "Gemma 4 31B IT"}


def validate_results(output, labels):
    """입력·설정·실제 대화 이력을 검증한 뒤 세션과 참고 지표를 반환한다."""
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert set(manifest["models"]) == set(labels)
    assert manifest["system_prompt_sha256"] == hashlib.sha256((output / "system_prompt.txt").read_bytes()).hexdigest()
    assert manifest["cases_file_sha256"] == hashlib.sha256((output / "cases.json").read_bytes()).hexdigest()
    assert (output / "system_prompt.txt").read_bytes() == (ROOT / "outputs/dialogue_examples_3cases_20261007/system_prompt.txt").read_bytes()
    for name, digest in manifest["source_code_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    config = json.loads((output / "candidate_config.json").read_text())
    assert manifest["config"] == config
    cases = json.loads((output / "cases.json").read_text())
    assert [case["case_id"] for case in cases] == ["R001", "R002", "R004"]
    expected_count = sum(len(case["client_turns"]) for case in cases)
    sessions = {}
    metrics = []
    for label in labels:
        assert manifest["models"][label] == "complete"
        directory = output / label
        runtime = json.loads((directory / "runtime.json").read_text())
        assert runtime["model"] == next(info for info in config["models"] if info["label"] == label)
        rows = read_sessions(directory / "sessions_unblinded.jsonl")
        assert len(rows) == len(cases)
        calls = read_sessions(directory / "raw_calls.jsonl")
        assert len(calls) == expected_count
        assert len((directory / "turn_events.jsonl").read_text().splitlines()) == expected_count
        for call in calls:
            payload = call["request"]
            sampling = runtime["model"].get("sampling", {})
            assert payload["temperature"] == sampling.get("temperature", 0) and payload["max_tokens"] == 384
            for key, value in sampling.items():
                assert payload[key] == value
            assert payload["seed"] == 42 and payload["repeat_penalty"] == 1.05
            assert payload["repeat_last_n"] == manifest["generation"]["context_size"] == 8192
            assert not payload["chat_template_kwargs"]["enable_thinking"]
            assert call["rendered_prompt_tokens"] + 384 <= manifest["generation"]["context_size"]
            assert not call["response"]["choices"][0]["message"].get("reasoning_content")
        cursor = 0
        for case in cases:
            matches = [session for session in rows if session["case_id"] == case["case_id"]]
            assert len(matches) == 1
            session = matches[0]
            assert [turn["client_text"] for turn in session["turns"]] == case["client_turns"]
            for index, turn in enumerate(session["turns"]):
                assert turn["response"].strip() and not turn["state"] and not turn["plan"]
                assert len(turn["generation_events"]) == 1
                call = calls[cursor]
                expected_history = [{"role": "system", "content": (output / "system_prompt.txt").read_text().strip()}]
                for previous in session["turns"][:index]:
                    expected_history.extend([{"role": "user", "content": previous["client_text"]},
                                             {"role": "assistant", "content": previous["response"]}])
                expected_history.append({"role": "user", "content": turn["client_text"]})
                assert call["request"]["messages"] == expected_history
                assert call["response"]["choices"][0]["message"]["content"].strip() == turn["response"]
                cursor += 1
            sessions[label, case["case_id"]] = session
            metrics.append({"model": labels[label], "case_id": case["case_id"], **summarize(session),
                            "generation_seconds": round(sum(turn["generation_events"][0]["seconds"] for turn in session["turns"]), 3)})
    return cases, sessions, metrics


def main():
    cases, sessions, metrics = validate_results(OUTPUT, LABELS)
    (OUTPUT / "summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    lines = ["# Gemma 4 31B IT / Qwen3.5-9B · 고정 내담자 발화 비교", "",
             "3사례 × 2모델 = 6세션, 상담자 응답 70개. 현재 상담 시스템 프롬프트 사용, 추가 대화 예시와 LoRA 없음.", "",
             "공통 설정: GGUF Q4_0, llama.cpp b11429, greedy(temperature 0), repeat_penalty 1.05, repeat_last_n 8192(전체 문맥), seed 42, 비사고 모드, 응답 최대 384토큰, context 8192.", "",
             "모델별 내장 채팅 템플릿은 다르다. GGUF 파일 revision·SHA-256과 실행 바이너리 해시를 기록했다. 이전 Qwen3 Transformers/NF4 결과와는 실행기·양자화 차이가 있으므로 엄격한 동일 조건 성능 비교가 아니다.", "",
             "내담자 발화는 고정 재생이며 새 상담자의 질문에 적응하지 않는다. 원본 호전 표현은 새 모델의 효과가 아니다. R001은 짧은 중간 구간이므로 완결 세션 평가에 부적합하다. 정식 CTRS 평가가 아닌 반복·대화 흐름 진단이다.", "",
             "## 문자열 참고 지표", "",
             "질문=물음표 포함 응답 수. 표현 후보=‘어떠세요·어떨까요·어떻게 생각하시’ 포함 응답 수. 질문이 적다고 CBT 품질이 좋은 것은 아니다.", "",
             "| 모델 | 사례 | 응답 | 질문 | 동일 질문 후보 | 완전 중복 | 상한 종료 | 생성 시간(초) |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in metrics:
        lines.append(f"| {row['model']} | {row['case_id']} | {row['response_count']} | {row['question_mark_turns']} | {row['repeated_question_turns']} | {row['exact_duplicate_turns']} | {row['token_cap_turns']} | {row['generation_seconds']} |")
    for case in cases:
        case_lines = ["# " + case["case_id"] + " · 후보 모델 비교", ""]
        section = ["", "## " + case["case_id"]]
        for index, client in enumerate(case["client_turns"]):
            section.extend(["", f"### 대화쌍 {index + 1}", "", "내담자: " + client])
            for label, title in LABELS.items():
                turn = sessions[label, case["case_id"]]["turns"][index]
                finish = turn["generation_events"][0]["finish_reason"]
                section.extend(["", "#### " + title + (" · 토큰 상한 종료" if finish == "length" else ""), "", turn["response"]])
        case_lines.extend(section)
        (OUTPUT / f"{case['case_id']}_COMPARISON.md").write_text("\n".join(case_lines) + "\n")
        lines.extend(section)
    (OUTPUT / "COMPARISON.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("Verified: 6 sessions, 70 responses; full history, identical client scripts and one generation per turn.")


if __name__ == "__main__":
    main()
