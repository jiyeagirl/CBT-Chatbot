#!/usr/bin/env python3
"""Qwen3-8B를 4-bit QLoRA로 지도 미세조정한다."""

from __future__ import annotations

import argparse
import json
import math
import random
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train-file", type=Path, required=True)
    parser.add_argument("--validation-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/qwen3-8b-cbt"))
    parser.add_argument("--model-name", default="Qwen/Qwen3-8B")
    parser.add_argument("--max-length", type=int, default=4096)
    parser.add_argument("--epochs", type=float, default=1.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--eval-batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation", type=int, default=16)
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.05)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--logging-steps", type=int, default=10)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--max-eval-samples", type=int, default=None,
                        help="사전 시험에서만 검증 예시 수를 제한합니다.")
    parser.add_argument("--max-steps", type=int, default=-1, help="20-step smoke test 등에 사용")
    parser.add_argument(
        "--source-balance",
        choices=("equal", "none"),
        default="equal",
        help="equal은 짧은 출처를 복원추출해 CACTUS/AIHub 예시 수를 맞춥니다.",
    )
    parser.add_argument("--resume-from-checkpoint", default=None)
    parser.add_argument("--report-to", choices=("tensorboard", "wandb", "none"), default="tensorboard")
    args = parser.parse_args()
    if args.save_steps < 1 or args.save_total_limit < 1:
        parser.error("저장 간격과 체크포인트 보존 개수는 1 이상이어야 합니다.")
    if args.max_eval_samples is not None and args.max_eval_samples < 1:
        parser.error("--max-eval-samples는 1 이상이어야 합니다.")
    return args


def balance_by_source(dataset, seed: int):
    """각 출처의 예시 수를 최대 출처 크기에 맞춰 복원추출한다."""
    from datasets import concatenate_datasets

    source_to_indices: dict[str, list[int]] = {}
    for index, source in enumerate(dataset["source"]):
        source_to_indices.setdefault(str(source), []).append(index)

    if len(source_to_indices) < 2:
        return dataset

    target_size = max(len(indices) for indices in source_to_indices.values())
    rng = random.Random(seed)
    balanced_parts = []
    for source, indices in sorted(source_to_indices.items()):
        sampled = list(indices)
        if len(sampled) < target_size:
            sampled.extend(rng.choices(indices, k=target_size - len(sampled)))
        rng.shuffle(sampled)
        balanced_parts.append(dataset.select(sampled))
        print(f"source={source}: {len(indices):,} -> {len(sampled):,}")

    return concatenate_datasets(balanced_parts).shuffle(seed=seed)


def main() -> None:
    args = parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from transformers import TrainerCallback, set_seed
    from trl import SFTConfig, SFTTrainer

    if not torch.cuda.is_available():
        raise SystemExit("CUDA GPU가 필요합니다. RunPod GPU Pod에서 실행하세요.")

    if args.output_dir.exists() and any(args.output_dir.iterdir()) and not args.resume_from_checkpoint:
        raise SystemExit("출력 폴더가 비어 있지 않습니다. 새 경로나 --resume-from-checkpoint를 사용하세요.")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    set_seed(args.seed)
    bf16 = bool(torch.cuda.is_bf16_supported())
    compute_dtype = torch.bfloat16 if bf16 else torch.float16
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"precision: {'bf16' if bf16 else 'fp16'}")

    data_files = {
        "train": str(args.train_file),
        "validation": str(args.validation_file),
    }
    datasets = load_dataset("json", data_files=data_files)
    train_dataset = datasets["train"]
    validation_dataset = datasets["validation"]
    if args.max_eval_samples is not None:
        validation_dataset = validation_dataset.shuffle(seed=args.seed).select(
            range(min(args.max_eval_samples, len(validation_dataset)))
        )

    if args.source_balance == "equal":
        train_dataset = balance_by_source(train_dataset, args.seed)

    # Match the non-thinking template used by dataset validation and chat.py.
    train_dataset = train_dataset.add_column(
        "chat_template_kwargs", [{"enable_thinking": False}] * len(train_dataset)
    )
    validation_dataset = validation_dataset.add_column(
        "chat_template_kwargs", [{"enable_thinking": False}] * len(validation_dataset)
    )

    print(f"train examples: {len(train_dataset):,}")
    print(f"validation examples: {len(validation_dataset):,}")

    tokenizer = AutoTokenizer.from_pretrained(args.model_name, use_fast=True)
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    quantization_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=compute_dtype,
    )
    model = AutoModelForCausalLM.from_pretrained(
        args.model_name,
        quantization_config=quantization_config,
        torch_dtype=compute_dtype,
        device_map={"": 0},
        low_cpu_mem_usage=True,
        attn_implementation="sdpa",
    )
    model.config.use_cache = False
    model = prepare_model_for_kbit_training(
        model,
        use_gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
    )

    lora_config = LoraConfig(
        task_type="CAUSAL_LM",
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    training_config = SFTConfig(
        output_dir=str(args.output_dir),
        max_length=args.max_length,
        completion_only_loss=True,
        packing=False,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.eval_batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        learning_rate=args.learning_rate,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        weight_decay=0.01,
        max_grad_norm=1.0,
        bf16=bf16,
        fp16=not bf16,
        optim="paged_adamw_8bit",
        logging_steps=args.logging_steps,
        logging_nan_inf_filter=False,
        eval_strategy="no",
        save_strategy="steps",
        save_steps=min(args.save_steps, args.max_steps) if args.max_steps > 0 else args.save_steps,
        save_total_limit=args.save_total_limit,
        save_only_model=False,
        load_best_model_at_end=False,
        report_to=[] if args.report_to == "none" else [args.report_to],
        remove_unused_columns=True,
        dataset_num_proc=2,
        seed=args.seed,
        data_seed=args.seed,
    )

    class StopOnNonFinite(TrainerCallback):
        def on_log(self, args, state, control, logs=None, **kwargs):
            for key in ("loss", "grad_norm", "eval_loss"):
                if logs and key in logs and not math.isfinite(float(logs[key])):
                    raise FloatingPointError(f"step={state.global_step}: {key}가 유한하지 않습니다.")

    trainer = SFTTrainer(
        model=model,
        args=training_config,
        train_dataset=train_dataset,
        eval_dataset=validation_dataset,
        processing_class=tokenizer,
        callbacks=[StopOnNonFinite()],
    )

    for name, dataset in (("train", trainer.train_dataset), ("validation", trainer.eval_dataset)):
        for index, example in enumerate(dataset):
            mask = example.get("completion_mask")
            if mask is None or not any(mask[1:]):
                raise ValueError(f"{name}[{index}]: 학습할 completion 토큰이 없습니다.")

    run_config = {
        "model_name": args.model_name,
        "max_length": args.max_length,
        "epochs": args.epochs,
        "learning_rate": args.learning_rate,
        "batch_size": args.batch_size,
        "gradient_accumulation": args.gradient_accumulation,
        "lora_r": args.lora_r,
        "lora_alpha": args.lora_alpha,
        "lora_dropout": args.lora_dropout,
        "source_balance": args.source_balance,
        "seed": args.seed,
        "bf16": bf16,
        "gpu": torch.cuda.get_device_name(0),
        "train_examples": len(train_dataset),
        "validation_examples": len(validation_dataset),
        "save_steps": training_config.save_steps,
        "max_eval_samples": args.max_eval_samples,
        "enable_thinking": False,
    }
    (args.output_dir / "run_config.json").write_text(
        json.dumps(run_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    train_result = trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    if not math.isfinite(train_result.training_loss):
        raise FloatingPointError("최종 training loss가 유한하지 않습니다.")
    trainer.save_metrics("train", train_result.metrics)
    trainer.save_state()

    final_adapter = args.output_dir / "final_adapter"
    trainer.save_model(str(final_adapter))
    tokenizer.save_pretrained(final_adapter)
    metrics = trainer.evaluate()
    trainer.save_metrics("eval", metrics)
    if not math.isfinite(float(metrics["eval_loss"])):
        raise FloatingPointError("최종 eval loss가 유한하지 않습니다.")
    print(f"Peak VRAM allocated: {torch.cuda.max_memory_allocated() / 1024**3:.2f} GiB")
    print(f"완료: {final_adapter.resolve()}")


if __name__ == "__main__":
    main()
