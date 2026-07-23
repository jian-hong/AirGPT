# LTX-2 Video Generator — AirGPT

**Status:** shipped (mock + cloud + local hooks) · **Port:** `8020` (canonical; research also floated 8090 — do not dual-bind)  
**GitHub:** https://github.com/Lightricks/LTX-2 · **Weights:** https://huggingface.co/Lightricks/LTX-2.3  
**Research:** [LTX-2 brief](798639a0-b676-45df-8da1-f1a6c7cd9870)

## License

**LTX-2 Community License** (not Apache). Free for most use; entities with ≥ **$10M** annual revenue need a paid commercial license from Lightricks. Legal review before shipping generation in product.

## Hardware reality

Official comfort zone: **32GB+ VRAM**, 32–64GB RAM, CUDA **12.7+**, PyTorch ~= 2.7, Gemma 3 12B text encoder (gated HF). On RTX 4070 (12GB): prefer **cloud** or mock; local only with distilled + `fp8-cast` + offload — expect pain. Do **not** co-reside local LTX with vLLM on 12GB.

## Modes

| Mode | When | Notes |
|------|------|--------|
| **cloud** | `LTX_API_KEY` set | Async `POST https://api.ltx.video/v2/text-to-video` |
| **local** | `third_party/LTX-2` (or `LTX2_ROOT`) + GPU | DistilledPipeline first; separate worker preferred over in-process |
| **mock** | default / CI | ffmpeg color plate or text stub |

## API (AirGPT)

```
GET  /api/video/capability
POST /api/video/generate   {prompt, duration, width, height, seed, mode?}
GET  /api/video/status/{id}
GET  /api/video/result/{id}
GET  /api/video/file/{id}
GET  /api/video/jobs
```

UI: sidebar **Video**. Outputs: `video-assets/08-ltx2-outputs/`.

## Local install (GPU)

```bash
git clone https://github.com/Lightricks/LTX-2.git third_party/LTX-2
cd third_party/LTX-2 && uv sync
hf download Lightricks/LTX-2.3 \
  ltx-2.3-22b-distilled-1.1.safetensors \
  ltx-2.3-spatial-upscaler-x2-1.1.safetensors \
  --local-dir models/ltx-2.3
hf download google/gemma-3-12b-it-qat-q4_0-unquantized --local-dir models/gemma-3-12b
```

RTX 4070 (12 GB): use distilled + `--quantization fp8-cast --offload cpu` if OOM.

## Port lock

See `apps_registry.json`. LTX-2 uses **8020** — never 8000/8001/8010/8765.

## Related

- Marketing plates (Higgsfield): `docs/VIDEO_PLAN_HIGGSFIELD.md` + `video-assets/05-higgsfield-plates/`
- LTX-2 generative clips: `video-assets/08-ltx2-outputs/`
