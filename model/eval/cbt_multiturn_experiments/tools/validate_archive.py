"""Offline checks of this curated archive; never prints suspected secret contents."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9_-]{20,}", r"hf_[A-Za-z0-9]{20,}",
    r"[?&](?:token|api_key|access_token)=[A-Za-z0-9_-]{12,}",
    r"(?:API_KEY|RUNPOD_API_KEY|JUPYTER_TOKEN)\s*=\s*['\"][A-Za-z0-9_-]{16,}['\"]",
    r"/" + r"Users/[^\s]+", r"https?://[^\s]+\.proxy\.runpod\.net",
)
FORBIDDEN_NAMES = {"cases.json", "profiles.json", "profiles_used.json", "raw_calls.jsonl",
                   "sessions_unblinded.jsonl", "sessions_blinded.jsonl", "adapter_model.safetensors"}
TRANSCRIPT_KEYS = {"client_text", "baseline_disclosures", "utterance", "dialogue", "messages", "raw_output"}


def transcript_keys(value):
    if isinstance(value, dict):
        return bool(set(value) & TRANSCRIPT_KEYS) or any(transcript_keys(item) for item in value.values())
    return isinstance(value, list) and any(transcript_keys(item) for item in value)


def validate() -> dict:
    errors = []
    checksum_path = ROOT / "CHECKSUMS.sha256"
    expected = {}
    for line in checksum_path.read_text().splitlines():
        sha, name = line.split("  ", 1)
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or name in expected:
            errors.append("Invalid/duplicate checksum path: " + name)
        expected[name] = sha
    files = [p for p in ROOT.rglob("*") if p.is_file() and "__pycache__" not in p.parts and p != checksum_path]
    if set(expected) != {p.relative_to(ROOT).as_posix() for p in files}:
        errors.append("Checksum inventory differs from actual files")
    python_count = 0
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.is_symlink() or path.name in FORBIDDEN_NAMES or path.name.startswith(".env"):
            errors.append("Forbidden file: " + relative)
        if path.suffix in {".gguf", ".safetensors", ".bin", ".zip", ".gz", ".csv", ".jsonl"}:
            errors.append("Excluded raw/binary type: " + relative)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected.get(relative):
            errors.append("Checksum mismatch: " + relative)
        text = data.decode("utf-8")
        # The scanner's own regex source contains patterns, not credential values.
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, text):
                errors.append("Sensitive-pattern candidate: " + relative)
        if path.suffix == ".py":
            ast.parse(text, filename=relative)
            python_count += 1
        if path.suffix == ".json":
            payload = json.loads(text)
            if transcript_keys(payload):
                errors.append("Transcript-bearing JSON key: " + relative)
        if path.suffix == ".md":
            for target in re.findall(r"(?<!!)\[[^\]]*\]\(([^)]+)\)", text):
                if target.startswith(("https://", "http://", "mailto:", "#")):
                    continue
                clean = target.split("#", 1)[0]
                if not (path.parent / clean).exists():
                    errors.append("Broken local link: " + relative + " -> " + clean)
    provenance = json.loads((ROOT / "provenance.json").read_text())
    for entry in provenance["files"]:
        path = ROOT / entry["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            errors.append("Source-copy identity changed: " + entry["path"])
    results_manifest = ROOT / "dialogue_results_manifest.json"
    dialogue_count = 0
    if results_manifest.exists():
        manifest = json.loads(results_manifest.read_text())
        approved = {"R002": "cactus_0207", "R004": "cactus_0900"}
        result_paths = set()
        for entry in manifest["files"]:
            name = entry["path"]
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append("Invalid dialogue path")
                continue
            if approved.get(entry["case_id"]) != entry["source_session_id"]:
                errors.append("Non-approved dialogue: " + name)
            path = ROOT / relative
            if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["rendered_sha256"]:
                errors.append("Dialogue identity changed: " + name)
            if path.exists() and "unhighlighted_rendered_sha256" in entry:
                opening = '<span style="color:#c62828" data-cbt-repeat="true">'
                plain = re.sub(re.escape(opening) + r"(.*?)</span>", lambda match: match.group(1), path.read_text(), flags=re.S)
                plain = re.sub(r"<!--repeat-->\*\*(.*?)\*\*<!--/repeat-->", lambda match: match.group(1), plain, flags=re.S)
                plain = re.sub(r"\*\*<!--repeat-->(.*?)<!--/repeat-->\*\*", lambda match: match.group(1), plain, flags=re.S)
                plain = plain.replace('<!--repeat-gap-->', '')
                if hashlib.sha256(plain.encode()).hexdigest() != entry["unhighlighted_rendered_sha256"]:
                    errors.append("Highlighted dialogue changed original text: " + name)
            if "highlighted_html_path" in entry:
                html_relative = Path(entry["highlighted_html_path"])
                if html_relative.is_absolute() or ".." in html_relative.parts:
                    errors.append("Invalid highlight HTML path")
                else:
                    html_path = ROOT / html_relative
                    if not html_path.exists() or hashlib.sha256(html_path.read_bytes()).hexdigest() != entry["highlighted_html_sha256"]:
                        errors.append("Highlight HTML identity changed: " + name)
            if name in result_paths:
                errors.append("Duplicate dialogue entry: " + name)
            result_paths.add(name)
        actual_results = {p.relative_to(ROOT).as_posix() for p in ROOT.glob("experiments/*/results/*") if p.is_file()}
        if result_paths != actual_results or manifest["session_count"] != len(result_paths):
            errors.append("Dialogue inventory differs from approved manifest")
        dialogue_count = len(result_paths)
    result = {"valid": not errors, "files_checked": len(files), "python_syntax_checked": python_count,
              "approved_cactus_dialogues_checked": dialogue_count,
              "preserved_source_copies_checked": len(provenance["files"]), "errors": errors,
              "scope": "Offline structure/checksum/pattern checks, not clinical validation or legal clearance"}
    if errors:
        raise ValueError(json.dumps(result, ensure_ascii=False))
    return result


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
