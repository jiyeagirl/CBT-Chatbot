"""동의 재확인 방지 프롬프트의 tuned-only R002 실험을 검증한다."""

import hashlib
import json
from pathlib import Path

from compare_question_prompt_experiment import read_sessions, summarize


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/no_reconsent_R002_20261007"
PREVIOUS = ROOT / "outputs/question_prompt_R002_20261007"


def main():
    cases = json.loads((OUTPUT / "cases.json").read_text())
    assert len(cases) == 1 and cases[0]["case_id"] == "R002"
    expected_clients = cases[0]["client_turns"]
    current = read_sessions(OUTPUT / "sessions_unblinded.jsonl")
    previous = [session for session in read_sessions(PREVIOUS / "sessions_unblinded.jsonl")
                if session["case_id"] == "R002" and session["condition"] == "tuned"]
    assert len(current) == len(previous) == 1
    assert current[0]["condition"] == "tuned"
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    old_manifest = json.loads((PREVIOUS / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert manifest["harness_version"] == "legacy-system-prompt-only"
    assert manifest["generation"] == old_manifest["generation"]
    assert manifest["system_prompt_sha256"] == hashlib.sha256((OUTPUT / "system_prompt.txt").read_bytes()).hexdigest()
    assert old_manifest["system_prompt_sha256"] == hashlib.sha256((OUTPUT / "system_prompt_original.txt").read_bytes()).hexdigest()
    runtime = json.loads((OUTPUT / "runtime.json").read_text())
    old_runtime = json.loads((PREVIOUS / "runtime.json").read_text())
    assert runtime["adapter_sha256"] == old_runtime["adapter_sha256"]
    assert runtime["versions"] == old_runtime["versions"]
    assert len((OUTPUT / "turn_events.jsonl").read_text().splitlines()) == 14
    for session in current + previous:
        assert len(session["turns"]) == len(expected_clients) == 14
        assert [turn["client_text"] for turn in session["turns"]] == expected_clients
        assert all(turn["response"].strip() and not turn["state"] and not turn["plan"]
                   for turn in session["turns"])
        assert all(len(turn["generation_events"]) == 1 for turn in session["turns"])
    ordered = [("수정 전 CBT 파인튜닝", previous[0]), ("동의 재확인 방지 추가", current[0])]
    summary = {label: summarize(session) for label, session in ordered}
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# R002 · 동의 재확인 방지 규칙 전후 비교", "",
             "Qwen3-8B CBT 파인튜닝 모델만 비교. 동일 내담자 발화 14개를 순서대로 입력했다.", "",
             "직전 질문 규칙 수정 프롬프트에 동의 재확인 방지·새 관점 반영·형식적 질문 마무리 금지 3개 규칙만 추가했다.", "",
             "NF4 4bit / greedy / repetition_penalty 1.05 / 최대 384토큰 / seed 42 / thinking 비활성화. 계획·상태 하네스, 재생성, 후처리 없음.", "",
             "검증: 완료 상태, 입력 발화, 생성 설정, 프롬프트 해시, 어댑터 해시, 라이브러리 버전, 턴당 생성 1회가 일치한다.", "",
             "학습 노출 사례의 고정 발화 재생 진단이다. 내담자의 사고 변화는 원본 발화에 포함되어 있으며 새 응답의 치료 효과를 뜻하지 않는다.", "",
             "## 문자열 참고 지표", "",
             "질문은 물음표가 있는 응답 수다. 표현 후보는 ‘어떠세요·어떨까요·어떻게 생각하시’ 포함 응답 수이며 의미 수준 반복이나 CTRS 점수가 아니다.", "",
             "| 조건 | 질문 응답 | 표현 후보 | 완전 중복 | 동일 질문 후보 | 토큰 상한 |",
             "|---|---:|---:|---:|---:|---:|"]
    for label, stats in summary.items():
        lines.append(f"| {label} | {stats['question_mark_turns']} | {stats['vague_permission_ending_turns']} | {stats['exact_duplicate_turns']} | {stats['repeated_question_turns']} | {stats['token_cap_turns']} |")
    for index, client_text in enumerate(expected_clients):
        lines.extend(["", f"## 대화쌍 {index + 1}", "", "내담자: " + client_text])
        for label, session in ordered:
            lines.extend(["", "### " + label, "", session["turns"][index]["response"]])
    (OUTPUT / "COMPARISON.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("Verified 14 new responses: same inputs, generation, adapter and versions; one generation per turn.")


if __name__ == "__main__":
    main()
