# Qwen3-VL + Unsloth experiment policy

## Hypotheses

H1: Fine-tuned Qwen3-VL can identify the *semantic target and rough location* on dense construction drawings better than generic SAM prompt heuristics.

H2: `Qwen→SAM→Mask→Vector` can outperform both `small segmentation→vector` and `small segmentation→SAM` on QTO geometry while remaining operationally acceptable.

H3: Direct polygon token generation may work for bounded/simple contours but is not assumed precise enough for general QTO.

## Model ladder

```text
2B = efficiency lower bound
4B = primary
8B = optional upper bound
```

Use Instruct editions first. Thinking editions are out of scope for geometry extraction unless a later benchmark demonstrates a need.

## Required ablation

For 4B:

1. zero-shot;
2. LoRA with vision frozen;
3. LoRA with vision+language adaptation.

Same split and comparable training budget where practical. This isolates whether building-drawing domain shift requires visual adaptation.

## Training outputs

Prefer strict structured output. Localization schema uses integer coordinates 0..1000 relative to the exact input image to reduce token burden and eliminate ambiguity. The model never outputs meters/m².

## Quantization

Accuracy baseline first, compression second. If BF16/FP16 is feasible, record it. QLoRA/4-bit is allowed as a memory-saving experiment, but promotion requires measured downstream QTO quality; vision quantization can materially change spatial performance.

## Anti-leakage

- GT may generate train labels.
- GT must never select val/test crop/bbox/prompt.
- test uses production-like deterministic source-only tiling.
- Qwen→SAM test prompt is exactly Qwen output; no GT repair.
- oracle GT→SAM is diagnostic only.

## Runtime

Do not assume vLLM/SGLang supports the exact trained vision LoRA. Promotion requires a real load/inference smoke with the selected runtime. Merged weights or Transformers inference are acceptable if provenance and benchmarks remain reproducible.

## Failure buckets

- schema failure;
- missed target;
- wrong-class target;
- text/dimension confusion;
- bbox too coarse;
- seed point outside target;
- tile-edge truncation;
- SAM prompt propagation error;
- direct polygon topology invalid;
- excessive latency/VRAM.
