"""완료된 고정 내담자 재생 결과의 완전성·중복·내부 메모 실패를 점검한다.

의미 반복이나 CTRS 점수를 자동 판정하지 않는다. 원본 응답은 변경하지 않는다.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from cbt_harness import repetition_candidates
from prepare_replay_diagnostic import file_hash


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def audit(results: Path, cases_path: Path) -> tuple[dict, str]:
    manifest = json.loads((results / "manifest.json").read_text(encoding="utf-8"))
    if manifest["status"] != "complete":
        raise ValueError("완료된 실행만 최종 집계합니다.")
    if manifest["cases_file_sha256"] != file_hash(cases_path):
        raise ValueError("실행 입력의 체크섬과 로컬 입력이 다릅니다.")
    cases = {row["case_id"]: row for row in json.loads(cases_path.read_text(encoding="utf-8"))}
    sessions = read_jsonl(results / "sessions_unblinded.jsonl")
    journal = read_jsonl(results / "turn_events.jsonl")
    expected = {(case_id, condition) for case_id in cases for condition in ("base", "tuned")}
    actual = [(session["case_id"], session["condition"]) for session in sessions]
    if len(actual) != len(expected) or set(actual) != expected:
        raise ValueError("세션이 누락되거나 중복되었습니다.")
    event_keys = [(row["case_id"], row["condition"], row["turn_index"]) for row in journal]
    if len(event_keys) != len(set(event_keys)):
        raise ValueError("턴 이벤트 키가 중복되었습니다.")
    events = {key: row for key, row in zip(event_keys, journal)}
    statistics = []
    transcript = ["# 고정 내담자 재생 진단 대화록", "",
                  "학습 분할의 내담자 발화를 고정 입력한 진단용 기록입니다. 후속 발화는 새 상담 응답에 적응하지 않습니다.",
                  "정식 CTRS 평가셋이 아니며, 반복 응답·오류도 수정하지 않았습니다.", ""]
    for session in sessions:
        case_id, condition = session["case_id"], session["condition"]
        turns = session["turns"]
        client_texts = [turn["client_text"] for turn in turns]
        if client_texts != cases[case_id]["client_turns"]:
            raise ValueError(f"{case_id}/{condition}: 원본 내담자 발화 또는 순서가 다릅니다.")
        history = []
        warning_counts = Counter()
        literal_duplicates = normalized_duplicates = similar_candidates = repeated_questions = 0
        state_failures = 0
        token_counts = []
        prior_responses = []
        transcript.extend([f"## {case_id} — {condition}", "",
                           f"원본 세션: {session['source_session_id']} · 내담자 발화 {len(turns)}개", ""])
        for turn in turns:
            key = (case_id, condition, turn["turn_index"])
            if events.get(key) != {"case_id": case_id, "condition": condition, **turn}:
                raise ValueError(f"{key}: 세션과 턴 이벤트가 일치하지 않습니다.")
            history.append({"role": "user", "content": turn["client_text"]})
            repetition = repetition_candidates(turn["response"], history)
            if repetition != turn["repetition_candidates"]:
                raise ValueError(f"{key}: 반복 후보 재계산이 다릅니다.")
            literal_duplicates += turn["response"] in prior_responses
            normalized_duplicates += repetition["exact_prior_response"]
            similar_candidates += repetition["maximum_prior_response_similarity"] >= 0.9
            repeated_questions += bool(repetition["repeated_question_candidates"])
            state_failures += any(warning.startswith("state_fallback:") for warning in turn["warnings"])
            warning_counts.update(turn["warnings"])
            token_counts.append(turn["generation_events"][-1]["generated_tokens"])
            transcript.extend([f"### 대화쌍 {turn['turn_index']}", "",
                               "내담자: " + turn["client_text"], "",
                               "상담자: " + turn["response"], ""])
            if turn["warnings"]:
                transcript.extend(["내부 경고: " + " / ".join(turn["warnings"]), ""])
            history.append({"role": "assistant", "content": turn["response"]})
            prior_responses.append(turn["response"])
        if history != session["messages"]:
            raise ValueError(f"{case_id}/{condition}: 대화 이력과 턴 기록이 다릅니다.")
        statistics.append({
            "case_id": case_id, "condition": condition, "counselor_turns": len(turns),
            "literal_duplicate_turns": literal_duplicates,
            "normalized_duplicate_turns": normalized_duplicates,
            "similarity_ge_0_9_candidate_turns": similar_candidates,
            "repeated_question_candidate_turns": repeated_questions,
            "state_fallback_turns": state_failures,
            "response_tokens_le_10_turns": sum(count <= 10 for count in token_counts),
            "response_length_cap_turns": sum(turn["generation_events"][-1]["finish_reason"] == "length" for turn in turns),
            "warning_counts": dict(warning_counts),
        })
    planned_turns = sum(len(case["client_turns"]) for case in cases.values()) * 2
    if len(journal) != planned_turns:
        raise ValueError("예상 턴 수와 실제 턴 수가 다릅니다.")
    return {
        "status": "complete", "session_count": len(sessions), "counselor_turn_count": len(journal),
        "checks": {"cases_sha256_matches": True, "session_keys_unique_and_complete": True, "event_keys_unique": True,
                   "client_texts_verbatim": True, "journal_matches_sessions": True,
                   "repetition_candidates_recomputed": True},
        "definitions": {
            "duplicate_turns": "동일 세션의 이전 상담 응답 중 하나와 같은 후속 턴 수. 첫 출현은 제외.",
            "normalized_duplicate_turns": "소문자화 후 숫자·영문·한글 외 문자를 제거한 응답의 중복.",
            "similarity_ge_0_9_candidate_turns": "정규화 문자열 SequenceMatcher 유사도 0.9 이상. 의미 반복 점수가 아님.",
            "response_tokens_le_10_turns": "10 생성 토큰 이하인 짧은 응답. 부적절성의 자동 판정은 아님.",
        },
        "sessions": statistics,
        "limitations": ["3개 사례의 학습 노출 진단이다.", "고정 내담자는 새 상담 응답에 적응하지 않는다.",
                        "이 파일은 한 실행의 품질 점검이다. 조건 간 효과는 입력·프롬프트·생성 설정을 검증한 별도 대조 실험에서 비교해야 한다.",
                        "의미 반복·CTRS 점수·임상적 효과는 자동 판정하지 않는다."],
    }, "\n".join(transcript)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    args = parser.parse_args()
    summary, transcript = audit(args.results, args.cases)
    for name, content in [("quality_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n"),
                          ("DIALOGUES_UNBLINDED.md", transcript)]:
        with (args.results / name).open("x", encoding="utf-8") as output:
            output.write(content)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
