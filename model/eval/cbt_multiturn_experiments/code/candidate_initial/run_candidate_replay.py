"""Pinned Gemma 4 / Qwen3.5 GGUF 모델을 한 GPU에서 순차 진단한다."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from cbt_harness import Generation
from generate_replay_diagnostic import load_cases, replay_session


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
PORT = 18081
ENDPOINT = f"http://127.0.0.1:{PORT}"
CONTEXT_SIZE = 8192
RESPONSE_LIMIT = 384


def file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_verified(asset, directory):
    destination = directory / asset["filename"]
    if destination.exists():
        if file_hash(destination) != asset["sha256"]:
            raise ValueError("Existing asset hash mismatch: " + asset["filename"])
        return destination
    partial = destination.with_suffix(destination.suffix + ".partial")
    digest = hashlib.sha256()
    count = 0
    checkpoint = 0
    with requests.get(asset["url"], stream=True, timeout=(30, 60)) as response:
        response.raise_for_status()
        with partial.open("xb") as handle:
            for chunk in response.iter_content(8 * 1024 * 1024):
                handle.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if count - checkpoint >= 1024 ** 3:
                    print("DOWNLOAD", asset["filename"], round(count / 1024 ** 3, 2), "GiB", flush=True)
                    checkpoint = count
    if digest.hexdigest() != asset["sha256"]:
        raise ValueError("Downloaded asset hash mismatch: " + asset["filename"])
    if count != asset["size"]:
        raise ValueError("Downloaded asset size mismatch: " + asset["filename"])
    partial.replace(destination)
    print("VERIFIED", asset["filename"], flush=True)
    return destination


def server_environment(binary_directory):
    environment = os.environ.copy()
    library_dirs = sorted({str(path.parent) for path in binary_directory.rglob("*.so*")})
    environment["LD_LIBRARY_PATH"] = ":".join(library_dirs + [environment.get("LD_LIBRARY_PATH", "")])
    return environment


def wait_for_server(process):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("llama-server exited before readiness; inspect server log")
        try:
            response = requests.get(ENDPOINT + "/health", timeout=3)
            if response.ok and response.headers.get("Content-Type", "").startswith("application/json") and response.json().get("status") == "ok":
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    raise TimeoutError("llama-server did not become ready")


def request_json(route, payload):
    response = requests.post(ENDPOINT + route, json=payload, timeout=(10, 120))
    if not response.ok:
        raise RuntimeError(f"Local inference {route} HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


def generation_payload(messages):
    return {"messages": messages, "temperature": 0.0, "max_tokens": RESPONSE_LIMIT,
            "seed": 42, "repeat_penalty": 1.05, "repeat_last_n": CONTEXT_SIZE,
            "presence_penalty": 0.0, "frequency_penalty": 0.0, "stream": False,
            "chat_template_kwargs": {"enable_thinking": False}, "reasoning_effort": "none"}


def run_model(model_info, binary, environment, cases, prompt):
    label = model_info["label"]
    directory = RESULTS / label
    directory.mkdir()
    command = [str(binary), "-m", str(ROOT / "assets" / model_info["filename"]),
               "--host", "127.0.0.1", "--port", str(PORT), "--ctx-size", str(CONTEXT_SIZE),
               "--parallel", "1", "--n-gpu-layers", "99", "--threads", "6",
               "--batch-size", "512", "--ubatch-size", "128", "--flash-attn", "on",
               "--no-context-shift", "--jinja", "--reasoning", "off",
               "--chat-template-kwargs", '{"enable_thinking":false}']
    with (directory / "server.log").open("x") as log:
        process = subprocess.Popen(command, env=environment, stdout=log, stderr=subprocess.STDOUT)
        try:
            wait_for_server(process)
            properties = requests.get(ENDPOINT + "/props", timeout=10).json()
            (directory / "server_properties.json").write_text(json.dumps(properties, ensure_ascii=False, indent=2))
            template = properties.get("chat_template", "")
            if not template:
                raise ValueError("Native model chat template missing")
            (directory / "runtime.json").write_text(json.dumps({"model": model_info,
                "server_command": command, "template_sha256": hashlib.sha256(template.encode()).hexdigest(),
                "gpu": subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total,memory.used", "--format=csv,noheader"], text=True).strip()}, indent=2))
            with (directory / "raw_calls.jsonl").open("x") as calls, (directory / "turn_events.jsonl").open("x") as journal, (directory / "sessions_unblinded.jsonl").open("x") as sessions:
                def generate(messages, purpose):
                    assert purpose == "response"
                    payload = generation_payload(messages)
                    rendered = request_json("/apply-template", payload)["prompt"]
                    tokens = request_json("/tokenize", {"content": rendered, "add_special": True, "parse_special": True})["tokens"]
                    if len(tokens) + RESPONSE_LIMIT > CONTEXT_SIZE:
                        raise ValueError("Context would overflow; history is not truncated")
                    started = time.perf_counter()
                    response = request_json("/v1/chat/completions", payload)
                    elapsed = round(time.perf_counter() - started, 3)
                    calls.write(json.dumps({"request": payload, "response": response,
                                           "rendered_prompt_tokens": len(tokens)}, ensure_ascii=False) + "\n")
                    calls.flush()
                    choice = response["choices"][0]
                    message = choice["message"]
                    text = message.get("content") or ""
                    if message.get("reasoning_content") or "<think>" in text:
                        raise ValueError("Thinking output observed despite non-thinking configuration")
                    return Generation(text=text.strip(), generated_tokens=response["usage"]["completion_tokens"],
                                      seconds=elapsed, finish_reason="eos" if choice["finish_reason"] == "stop" else choice["finish_reason"])

                for case in cases:
                    def record(turn):
                        journal.write(json.dumps({"case_id": case["case_id"], "condition": label, **turn}, ensure_ascii=False) + "\n")
                        journal.flush()
                        print("TURN", label, case["case_id"], turn["turn_index"], turn["generation_events"][-1]["finish_reason"], flush=True)
                    session = replay_session(case, generate, prompt, harness_version="legacy", on_turn=record)
                    sessions.write(json.dumps({"condition": label, **session}, ensure_ascii=False) + "\n")
                    sessions.flush()
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover-before-generation", action="store_true")
    args = parser.parse_args()
    config = json.loads((ROOT / "candidate_config.json").read_text())
    cases = load_cases(ROOT / "cases.json")
    prompt = (ROOT / "system_prompt.txt").read_text().strip()
    if args.recover_before_generation:
        old_manifest = json.loads((RESULTS / "manifest.json").read_text())
        assert old_manifest["status"] == "failed"
        assert not any(path.read_text().strip() for name in ["raw_calls.jsonl", "turn_events.jsonl", "sessions_unblinded.jsonl"] for path in RESULTS.rglob(name)), "Cannot restart after generation"
        archive = ROOT / "preflight_failure"
        assert not archive.exists()
        RESULTS.rename(archive)
        RESULTS.mkdir()
        archive.rename(RESULTS / "preflight_failure")
    else:
        RESULTS.mkdir(exist_ok=False)
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    manifest = {"status": "preparing", "purpose": "fixed_client_replay_diagnostic_only", "evaluation_eligible": False,
                "config": config, "case_count": len(cases),
                "cases_file_sha256": file_hash(ROOT / "cases.json"),
                "system_prompt_sha256": file_hash(ROOT / "system_prompt.txt"),
                "generation": {"temperature": 0.0, "seed": 42, "repeat_penalty": 1.05, "repeat_last_n": CONTEXT_SIZE,
                               "max_tokens": RESPONSE_LIMIT, "context_size": CONTEXT_SIZE, "thinking": False},
                "source_code_sha256": {name: file_hash(ROOT / name) for name in ["run_candidate_replay.py", "generate_replay_diagnostic.py", "cbt_harness.py"]},
                "models": {}, "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "limitations": ["GGUF Q4_0 differs from prior Transformers NF4 backend.", "Greedy is a pattern diagnostic, not each model's official sampling recommendation.", "Fixed clients do not adapt; original improvements are not treatment effects.", "R001 is a short mid-conversation excerpt, not a complete counseling session."]}
    manifest_path = RESULTS / "manifest.json"
    def save():
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    save()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(download_verified, asset, assets) for asset in config["binaries"] + config["models"]]
            for future in futures:
                future.result()
        binary_directory = ROOT / "llama_runtime"
        binary_directory.mkdir(exist_ok=True)
        for asset in config["binaries"]:
            with tarfile.open(assets / asset["filename"]) as archive:
                archive.extractall(binary_directory, filter="data")
        binaries = list(binary_directory.rglob("llama-server"))
        assert len(binaries) == 1
        binary = binaries[0].resolve()
        environment = server_environment(binary_directory)
        version = subprocess.check_output([str(binary), "--version"], env=environment, text=True, stderr=subprocess.STDOUT)
        (RESULTS / "runtime.json").write_text(json.dumps({"llama_version": version, "binary_sha256": file_hash(binary),
            "gpu": subprocess.check_output(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], text=True).strip()}, indent=2))
        manifest["status"] = "running"
        save()
        for model_info in config["models"]:
            manifest["models"][model_info["label"]] = "running"
            save()
            run_model(model_info, binary, environment, cases, prompt)
            manifest["models"][model_info["label"]] = "complete"
            save()
        manifest.update(status="complete", finished_at_utc=datetime.now(timezone.utc).isoformat())
        save()
        print("COMPLETE", flush=True)
    except Exception as error:
        manifest.update(status="failed", error_type=type(error).__name__, error=str(error))
        save()
        raise


if __name__ == "__main__":
    main()
