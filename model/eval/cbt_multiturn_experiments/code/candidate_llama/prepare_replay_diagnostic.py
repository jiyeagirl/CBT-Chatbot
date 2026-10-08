"""정규화 sessions JSONL에서 원본 내담자 고정 재생용 사례만 추출한다.

학습 분할 사용 여부와 입력 해시를 기록한다. 모든 산출물은 진단용이며
자연스러운 상호작용 평가셋이나 CTRS 성능 비교로 표시하지 않는다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def new_output_directory(path: Path) -> None:
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        raise ValueError(f"기존 결과를 덮어쓰지 않습니다: {path}")
    path.mkdir(parents=True, exist_ok=True)


def select_cases(
    sessions: list[dict[str, Any]], *, source_split: str, count: int = 5,
    min_client_turns: int = 3, max_client_turns: int | None = None, seed: int = 42,
) -> list[dict[str, Any]]:
    if source_split not in {"train", "validation", "test"}:
        raise ValueError("원본 분할을 train/validation/test 중 하나로 명시하세요.")
    if count < 1 or min_client_turns < 1 or (
        max_client_turns is not None and max_client_turns < min_client_turns
    ):
        raise ValueError("사례 수와 최소·최대 내담자 턴 수가 잘못되었습니다.")
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    session_ids: set[str] = set()
    for session in sessions:
        session_id = session.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id가 필요합니다. SFT 예시가 아니라 sessions JSONL을 사용하세요.")
        if session_id in session_ids:
            raise ValueError(f"중복 session_id: {session_id}")
        session_ids.add(session_id)
        messages = session.get("messages", [])
        dialogue = [row for row in messages if row.get("role") != "system"]
        if not dialogue or any(
            row.get("role") != ("user" if index % 2 == 0 else "assistant")
            or not isinstance(row.get("content"), str) or not row["content"].strip()
            for index, row in enumerate(dialogue)
        ):
            raise ValueError(f"{session_id}: 정규화된 교대 대화가 아닙니다.")
        client_turns = [row["content"] for row in dialogue if row["role"] == "user"]
        if len(client_turns) < min_client_turns:
            continue
        candidates[str(session.get("source", "unknown"))].append({
            "source_session_id": session_id,
            "source_group_id": session.get("group_id", session_id),
            "source": session.get("source", "unknown"),
            "source_stratum": session.get("stratum", ""),
            "source_split": source_split,
            "training_split": source_split == "train",
            "purpose": "fixed_client_replay_diagnostic_only",
            "evaluation_eligible": False,
            "original_client_turn_count": len(client_turns),
            "client_turns_truncated": max_client_turns is not None and len(client_turns) > max_client_turns,
            "client_turns": client_turns[:max_client_turns],
        })

    randomizer = random.Random(seed)
    for source in sorted(candidates):
        randomizer.shuffle(candidates[source])
    cases: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    while len(cases) < count:
        added = False
        for source in sorted(candidates):
            while candidates[source]:
                candidate = candidates[source].pop()
                group_key = f"{source}:{candidate['source_group_id']}"
                if group_key in used_groups:
                    continue
                used_groups.add(group_key)
                cases.append({"case_id": f"R{len(cases) + 1:03d}", **candidate})
                added = True
                break
            if len(cases) == count:
                break
        if not added:
            raise ValueError(f"조건에 맞는 서로 다른 내담자 그룹이 {count}개보다 적습니다.")
    return cases


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-file", type=Path, required=True)
    parser.add_argument("--source-split", choices=["train", "validation", "test"], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-count", type=int, default=5)
    parser.add_argument("--min-client-turns", type=int, default=3)
    parser.add_argument(
        "--max-client-turns", type=int,
        help="생략하면 정규화된 원본 세션의 내담자 발화를 끝까지 사용합니다.",
    )
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    if args.sessions_file.stem in {"train", "validation", "test"} and args.sessions_file.stem != args.source_split:
        parser.error("파일명과 --source-split이 다릅니다.")
    sessions = [json.loads(line) for line in args.sessions_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    cases = select_cases(
        sessions, source_split=args.source_split, count=args.case_count,
        min_client_turns=args.min_client_turns, max_client_turns=args.max_client_turns, seed=args.seed,
    )
    new_output_directory(args.output_dir)
    (args.output_dir / "cases.json").write_text(json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "purpose": "fixed_client_replay_diagnostic_only", "evaluation_eligible": False,
        "source_split_declared": args.source_split, "training_split": args.source_split == "train",
        "sessions_file": str(args.sessions_file.resolve()), "sessions_file_sha256": file_hash(args.sessions_file),
        "case_count": len(cases), "seed": args.seed, "max_client_turns": args.max_client_turns,
        "replay_scope": "full_normalized_session" if args.max_client_turns is None else "limited_client_turns",
        "truncated_case_count": sum(case["client_turns_truncated"] for case in cases),
        "total_client_turns": sum(len(case["client_turns"]) for case in cases),
        "source_counts": {source: sum(case["source"] == source for case in cases) for source in sorted({case["source"] for case in cases})},
        "limitation": "내담자는 생성 상담자 응답에 적응하지 않는다. 후속 질문·답변 불일치와 학습 노출 영향을 별도로 검토해야 한다.",
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"진단용 입력 준비 완료: {args.output_dir.resolve()} ({len(cases)}사례; 모델 생성 없음)")


if __name__ == "__main__":
    main()
