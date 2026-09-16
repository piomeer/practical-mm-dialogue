#!/usr/bin/env python3
"""Design multi-turn dialogue tasks for images via DashScope Qwen (OpenAI-compatible)."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
DESIGNS_PATH = LOG_DIR / "qwen_task_designs.jsonl"
USAGE_PATH = LOG_DIR / "qwen_token_usage.jsonl"
DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-flash"

DEFAULT_IMAGES = [
    "收据/0003sroie_x00016469612.jpg",
    "生活场景/0005a_picnic_spread_with_waffles_and_berries.jpg",
    "工作场景/0001abbotsford_house_study_room.jpg",
    "文档截图/0001slide_2012_02_20fy11roadshow_12022102244.jpg",
    "图表推理/0001chartqa_10095.jpg",
]

SYSTEM_PROMPT = """你是实用多轮图文对话数据集的任务设计师。
根据用户给出的一张真实图片，设计一条可落地的多轮对话任务方案。
要求：
1. 对话必须强依赖图片内容，不能做成无关闲聊。
2. 多轮需递进：澄清 → 用图提取/分析 → 修正或深化 → 可交付结果。
3. 只输出一个 JSON 对象，不要 Markdown 代码围栏，不要额外说明。
JSON 字段：
- local_path: 字符串（沿用输入路径）
- task_type: 看图创作 / 信息提取与整理 / 文档翻译 / 逻辑推理 / 生活/工作/学习实用问题 等之一
- scenario: 生活 / 工作 / 学习
- goal: 一句话可交付目标
- turn_plan: 字符串数组，3~6 步递进计划
- image_must_use: 字符串数组，必须从图中读出的证据点
- output_type: 表格 / 创作文案 / 翻译稿 / 推理结论 / 行动计划 / 摘要 等
- risks: 字符串数组，模糊、隐私、不适合该任务等风险
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def image_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/jpeg"
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            raise
        return json.loads(m.group(0))


def design_one(client: OpenAI, model: str, rel: str) -> tuple[dict | None, dict]:
    img_path = ROOT / "data" / rel
    if not img_path.is_file():
        usage = {
            "model": model,
            "local_path": rel,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "started_at": utc_now(),
            "ended_at": utc_now(),
            "elapsed_ms": 0,
            "ok": False,
            "error": f"missing file: {img_path}",
        }
        return None, usage

    data_url = image_to_data_url(img_path)
    user_text = (
        f"图片相对路径：{rel}\n"
        "请基于图片内容设计任务流程 JSON。"
    )
    started = time.perf_counter()
    started_at = utc_now()
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=1.0,
            top_p=0.95,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": user_text},
                    ],
                },
            ],
        )
        ended_at = utc_now()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        u = resp.usage
        usage = {
            "model": model,
            "local_path": rel,
            "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens": getattr(u, "total_tokens", 0) or 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_ms": elapsed_ms,
            "ok": True,
            "error": None,
        }
        content = (resp.choices[0].message.content or "").strip()
        design = extract_json(content)
        design["local_path"] = rel
        design["_raw_model"] = model
        design["_elapsed_ms"] = elapsed_ms
        return design, usage
    except Exception as e:
        ended_at = utc_now()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = {
            "model": model,
            "local_path": rel,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_ms": elapsed_ms,
            "ok": False,
            "error": str(e),
        }
        return None, usage


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen 任务设计试跑")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="DashScope 模型 ID")
    parser.add_argument(
        "--paths",
        nargs="*",
        default=DEFAULT_IMAGES,
        help="相对 data/ 的图片路径",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        print(
            "缺少 DASHSCOPE_API_KEY。请在项目根目录 .env 中填写后重试。\n"
            "示例见 .env.example",
            file=sys.stderr,
        )
        return 2

    client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    wall_start = time.perf_counter()
    sum_prompt = sum_completion = sum_total = 0
    ok_n = fail_n = 0

    print(f"model={args.model}  images={len(args.paths)}")
    for i, rel in enumerate(args.paths, 1):
        print(f"[{i}/{len(args.paths)}] {rel} …", flush=True)
        design, usage = design_one(client, args.model, rel)
        append_jsonl(USAGE_PATH, usage)
        if design is not None:
            append_jsonl(DESIGNS_PATH, design)
            ok_n += 1
            print(
                f"  ok  tokens={usage['total_tokens']}  "
                f"elapsed_ms={usage['elapsed_ms']}  "
                f"task={design.get('task_type')}  goal={str(design.get('goal', ''))[:60]}",
                flush=True,
            )
        else:
            fail_n += 1
            print(
                f"  FAIL elapsed_ms={usage['elapsed_ms']}  error={usage.get('error')}",
                flush=True,
            )
        sum_prompt += usage.get("prompt_tokens", 0) or 0
        sum_completion += usage.get("completion_tokens", 0) or 0
        sum_total += usage.get("total_tokens", 0) or 0

    wall_ms = int((time.perf_counter() - wall_start) * 1000)
    print("---")
    print(f"ok={ok_n} fail={fail_n}")
    print(
        f"tokens: prompt={sum_prompt} completion={sum_completion} total={sum_total}"
    )
    print(f"wall_elapsed_ms={wall_ms}")
    print(f"designs -> {DESIGNS_PATH}")
    print(f"usage   -> {USAGE_PATH}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
