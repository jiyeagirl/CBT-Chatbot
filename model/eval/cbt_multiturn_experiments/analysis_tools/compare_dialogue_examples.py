"""3개 고정 발화 사례의 예시 프롬프트 2×2 실험 검증·비교 노트."""

import hashlib
import json
from pathlib import Path

from compare_question_prompt_experiment import read_sessions, summarize


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/dialogue_examples_3cases_20261007"


def main():
    cases = json.loads((OUTPUT / "cases.json").read_text())
    sessions = {}
    manifests = []
    metrics = []
    for variant, prompt_file in [("control", "system_prompt.txt"), ("examples", "system_prompt_examples.txt")]:
        directory = OUTPUT / variant
        manifest = json.loads((directory / "manifest.json").read_text())
        assert manifest["status"] == "complete"
        assert manifest["harness_version"] == "legacy-system-prompt-only"
        assert manifest["cases_file_sha256"] == hashlib.sha256((OUTPUT / "cases.json").read_bytes()).hexdigest()
        assert manifest["system_prompt_sha256"] == hashlib.sha256((OUTPUT / prompt_file).read_bytes()).hexdigest()
        manifests.append(manifest)
        rows = read_sessions(directory / "sessions_unblinded.jsonl")
        assert len(rows) == len(cases) * 2
        for case in cases:
            for condition in ["base", "tuned"]:
                matches = [row for row in rows if row["case_id"] == case["case_id"] and row["condition"] == condition]
                assert len(matches) == 1
                session = matches[0]
                assert [turn["client_text"] for turn in session["turns"]] == case["client_turns"]
                assert all(turn["response"].strip() and not turn["state"] and not turn["plan"] and
                           len(turn["generation_events"]) == 1 for turn in session["turns"])
                sessions[variant, condition, case["case_id"]] = session
                metrics.append({"variant": variant, "condition": condition, "case_id": case["case_id"], **summarize(session)})
        assert len((directory / "turn_events.jsonl").read_text().splitlines()) == sum(len(case["client_turns"]) for case in cases) * 2
    assert manifests[0]["generation"] == manifests[1]["generation"]
    assert manifests[0]["source_code_sha256"] == manifests[1]["source_code_sha256"]
    control_prompt = (OUTPUT / "system_prompt.txt").read_text().rstrip()
    assert (OUTPUT / "system_prompt_examples.txt").read_text().startswith(control_prompt + "\n\n")
    runtime = json.loads((OUTPUT / "runtime.json").read_text())
    adapter = ROOT / "work/replay_diagnostic_assets/model/outputs/qwen3-8b-cbt-e1/final_adapter/adapter_model.safetensors"
    assert runtime["adapter_sha256"] == hashlib.sha256(adapter.read_bytes()).hexdigest()
    (OUTPUT / "summary.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n")
    lines = ["# 대화 예시 추가 · Base / CBT 파인튜닝 비교", "",
             "동일한 고정 내담자 발화 3개 사례, 프롬프트 2종 × 모델 2종. 총 12세션·140응답.", "",
             "현재 프롬프트(control)와 동일 프롬프트 끝에 전환 예시 2개를 추가한 버전(examples)만 비교한다. 시스템 프롬프트 외 계획·상태 하네스 없음.", "",
             "NF4 4bit / greedy / repetition_penalty 1.05 / 최대 384토큰 / seed 42 / thinking 비활성화. 대화 이력 유지, 턴당 생성 1회, 후처리 없음.", "",
             "고정 발화 재생이므로 이후 내담자 반응은 새 상담자 응답에 적응하지 않는다. 학습 노출 사례의 진단이며 치료 효과·정식 CTRS 평가가 아니다.", "",
             "## 문자열 참고 지표", "",
             "질문 수는 물음표 포함 응답 수, 표현 후보는 ‘어떠세요·어떨까요·어떻게 생각하시’ 포함 응답 수. 의미 반복·상담 품질 점수가 아니다.", "",
             "| 사례 | 모델 | 예시 | 응답 | 질문 | 표현 후보 | 동일 질문 후보 | 완전 중복 | 상한 종료 |",
             "|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for row in metrics:
        lines.append(f"| {row['case_id']} | {row['condition']} | {row['variant']} | {row['response_count']} | {row['question_mark_turns']} | {row['vague_permission_ending_turns']} | {row['repeated_question_turns']} | {row['exact_duplicate_turns']} | {row['token_cap_turns']} |")
    for case in cases:
        lines.extend(["", "## " + case["case_id"]])
        case_lines = ["# " + case["case_id"] + " · 프롬프트 예시 비교", "", "각 모델의 예시 없는 응답과 예시 추가 응답을 나란히 기록한다."]
        for index, client in enumerate(case["client_turns"]):
            section = ["", f"### 대화쌍 {index + 1}", "", "내담자: " + client]
            for condition in ["base", "tuned"]:
                for variant in ["control", "examples"]:
                    section.extend(["", f"#### {condition} · {variant}", "", sessions[variant, condition, case["case_id"]]["turns"][index]["response"]])
            lines.extend(section)
            case_lines.extend(section)
        (OUTPUT / f"{case['case_id']}_COMPARISON.md").write_text("\n".join(case_lines) + "\n")
    (OUTPUT / "COMPARISON.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    print("Verified 12 sessions / 140 responses, identical clients/settings/code and matching adapter hash.")


if __name__ == "__main__":
    main()
