"""R002 새 결과를 검증하고 기존 프롬프트 결과와 나란히 정리한다."""

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/question_prompt_R002_20261007"
PREVIOUS = ROOT / "outputs/prompt_ablation_3cases_20261006/original"


def read_sessions(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def summarize(session):
    turns = session["turns"]
    return {
        "response_count": len(turns),
        "question_mark_turns": sum(bool(re.search(r"[?？]", row["response"])) for row in turns),
        "vague_permission_ending_turns": sum(bool(re.search(r"어떠세요|어떨까요|어떻게 생각하시", row["response"])) for row in turns),
        "exact_duplicate_turns": sum(row["repetition_candidates"]["exact_prior_response"] for row in turns),
        "repeated_question_turns": sum(bool(row["repetition_candidates"]["repeated_question_candidates"]) for row in turns),
        "token_cap_turns": sum(row["generation_events"][-1]["finish_reason"] == "length" for row in turns),
    }


def main():
    cases = json.loads((OUTPUT / "cases.json").read_text())
    assert len(cases) == 1 and cases[0]["case_id"] == "R002"
    expected_clients = cases[0]["client_turns"]
    current = read_sessions(OUTPUT / "sessions_unblinded.jsonl")
    previous = [row for row in read_sessions(PREVIOUS / "sessions_unblinded.jsonl") if row["case_id"] == "R002"]
    assert len(current) == len(previous) == 2
    manifest = json.loads((OUTPUT / "manifest.json").read_text())
    old_manifest = json.loads((PREVIOUS / "manifest.json").read_text())
    assert manifest["status"] == "complete"
    assert manifest["harness_version"] == "legacy-system-prompt-only"
    assert manifest["generation"] == old_manifest["generation"]
    assert manifest["system_prompt_sha256"] == hashlib.sha256((OUTPUT / "system_prompt.txt").read_bytes()).hexdigest()
    assert old_manifest["system_prompt_sha256"] == hashlib.sha256((OUTPUT / "system_prompt_original.txt").read_bytes()).hexdigest()
    for session in current + previous:
        assert len(session["turns"]) == 14
        assert [row["client_text"] for row in session["turns"]] == expected_clients
        assert all(row["response"].strip() and not row["state"] and not row["plan"] for row in session["turns"])
        assert all(len(row["generation_events"]) == 1 for row in session["turns"])
    ordered = [("기존 Base", next(row for row in previous if row["condition"] == "base")),
               ("수정 Base", next(row for row in current if row["condition"] == "base")),
               ("기존 CBT 파인튜닝", next(row for row in previous if row["condition"] == "tuned")),
               ("수정 CBT 파인튜닝", next(row for row in current if row["condition"] == "tuned"))]
    summary = {label: summarize(session) for label, session in ordered}
    (OUTPUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["# R002 · 질문 규칙 변경 전후 비교", "",
             "내담자 발화 14개 고정. Base와 CBT 파인튜닝 모델 모두 기본 프롬프트만 사용하며, 계획·상태 하네스는 사용하지 않았다.", "",
             "기존 결과는 2026-10-06 생성 자료를 재사용했다. 새 결과는 질문·개입 관련 두 문장만 수정한 프롬프트로 생성했다.", "",
             "NF4 4bit / greedy / repetition_penalty 1.05 / 응답 최대 384토큰 / seed 42 / thinking 비활성화.", "",
             "학습 노출 사례의 고정 발화 재생 진단이다. 내담자의 호전은 새 상담자의 효과가 아니며, 이후 발화가 질문에 맞지 않을 수 있다.", "",
             "## 문자열 수준 참고 지표", "",
             "질문은 물음표가 있는 응답 수, 표현 후보는 ‘어떠세요·어떨까요·어떻게 생각하시’가 있는 응답 수다. 의미 반복·상담 품질 점수가 아니다.", "",
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
    print("Verified: 28 new responses, matching clients/settings/prompt hashes; no additional harness calls.")


if __name__ == "__main__":
    main()
