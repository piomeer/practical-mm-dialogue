#!/usr/bin/env python3
"""Optional VL spot-check: extract merchant/key numbers from receipt/doc images into meta.

api_ok = API call succeeded. verified is always false here — never treat as OCR ground truth.
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

SAMPLES = ROOT / "实用多轮对话类图文数据集" / "samples"
PENDING = SAMPLES / "_pending_review"
DATA = ROOT / "data"
LOG_DIR = ROOT / "logs"
USAGE_PATH = LOG_DIR / "qwen_token_usage.jsonl"
DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-flash"

SPOTCHECK_CATS = {"收据", "文档截图"}

SYSTEM = """你是OCR抽检助手。只根据图片读出可见原文，不要推理、不要改写。
收据特别注意：
- header_person_name：页眉手写/印刷的人名（如 tan woon yann），不是店名。
- merchant_legal_name：法定店名/公司名（如 BOOK TALK (TAMAN DAYA) SDN BHD），不要用人名冒充。
- 单据号逐字符照抄，禁止臆造斜杠或空格。
文档截图：merchant_legal_name 可填标题；header_person_name 通常为空。

输出一个 JSON 对象：
{
  "header_person_name": "页眉人名原文，无则空字符串",
  "merchant_legal_name": "法定店名或文档标题原文，看不清则空字符串",
  "key_numbers": ["图中见到的编号/金额/百分比等原文片段（可含行价、手写批注，供人审）", "..."],
  "core_keys": ["单据头+结算必备原文：发票号、日期、时间、GST/客户号、应付总额(取整后)、实付、找零等"],
  "notes": "不确定处一句话，可空"
}

core_keys 规则（硬门禁用，须精简）：
- 要：发票号、交易日期、交易时间（可分行）、GST ID、顾客号、Total After Adj / 应付总额、Cash/实付、Change/找零、文档标题级关键数字。
- 不要：行项目单价（如 93.90SR）、手写批注号（如 A05023）、取整前小计（已有 After Adj 总额时）、把日期与时间硬拼成一条。
- key_numbers 仍可收录全量观测值；core_keys 只放摘要交付也应覆盖的结算字段。
不要 Markdown 代码围栏。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def image_to_data_url(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if not mime:
        mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def extract_json(text: str) -> dict:
    text = (text or "").strip()
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


def resolve_image(data: dict) -> Path | None:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    src = meta.get("source_paths") or []
    if isinstance(src, list) and src:
        p = DATA / str(src[0])
        if p.is_file():
            return p
    images = data.get("images") or []
    if images and isinstance(images[0], dict):
        name = Path(images[0].get("image_path") or "").name
        if name:
            for cat in SPOTCHECK_CATS:
                cand = DATA / cat / name
                if cand.is_file():
                    return cand
            samp = SAMPLES / "images" / name
            if samp.is_file():
                return samp
    return None


def category_of(data: dict) -> str:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    src = meta.get("source_paths") or []
    if isinstance(src, list) and src and isinstance(src[0], str) and "/" in src[0]:
        return src[0].split("/", 1)[0]
    return ""


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def time_perf() -> float:
    import time

    return time.perf_counter()


def spotcheck_one(client: OpenAI, model: str, data: dict) -> dict | None:
    cat = category_of(data)
    if cat not in SPOTCHECK_CATS:
        return None
    img = resolve_image(data)
    if img is None:
        return {
            "api_ok": False,
            "verified": False,
            "error": "image_not_found",
            "checked_at": utc_now(),
            "note": "api_ok=false means call/image failed; never treat spotcheck as OCR ground truth",
        }
    user_content = [
        {"type": "text", "text": f"类别：{cat}\n请按 schema 抽取可见原文。页眉人名≠店名。"},
        {"type": "image_url", "image_url": {"url": image_to_data_url(img)}},
    ]
    t0 = time_perf()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user_content},
        ],
        temperature=0.1,
    )
    elapsed_ms = int((time_perf() - t0) * 1000)
    text = (resp.choices[0].message.content or "") if resp.choices else ""
    usage = getattr(resp, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    total_tokens = getattr(usage, "total_tokens", 0) or (prompt_tokens + completion_tokens)
    append_jsonl(
        USAGE_PATH,
        {
            "stage": "ocr_spotcheck",
            "model": model,
            "ok": True,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "elapsed_ms": elapsed_ms,
            "started_at": utc_now(),
            "ended_at": utc_now(),
            "error": None,
            "local_path": _rel(img),
        },
    )
    parsed = extract_json(text)
    # Back-compat: old field merchant_or_title may appear; prefer merchant_legal_name
    merchant = parsed.get("merchant_legal_name") or parsed.get("merchant_or_title") or ""
    key_numbers = parsed.get("key_numbers") or []
    if not isinstance(key_numbers, list):
        key_numbers = []
    core_keys = parsed.get("core_keys") or []
    if not isinstance(core_keys, list):
        core_keys = []
    # Normalize to non-empty strings only
    key_numbers = [str(x).strip() for x in key_numbers if str(x).strip()]
    core_keys = [str(x).strip() for x in core_keys if str(x).strip()]
    return {
        "api_ok": True,
        "verified": False,
        "category": cat,
        "image": _rel(img),
        "header_person_name": parsed.get("header_person_name") or "",
        "merchant_legal_name": merchant,
        "key_numbers": key_numbers,
        "core_keys": core_keys,
        "notes": parsed.get("notes") or "",
        "checked_at": utc_now(),
        "model": model,
        "tokens": total_tokens,
        "note": (
            "api_ok only means the VL call returned JSON; verified is always false. "
            "key_numbers=observed (human clue); core_keys=validate hard gate when present."
        ),
    }


def apply_spotcheck(path: Path, client: OpenAI, model: str) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    result = spotcheck_one(client, model, data)
    if result is None:
        return {"path": str(path), "skipped": True, "reason": "not_receipt_or_doc"}
    meta = data.setdefault("meta", {})
    meta["ocr_spotcheck"] = result
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    pending = PENDING / path.name
    if pending.is_file() or meta.get("review_queue") is True:
        PENDING.mkdir(parents=True, exist_ok=True)
        pending.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return {"path": str(path), "skipped": False, "ocr_spotcheck": result}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OCR spot-check (api_ok only; never OCR ground truth)"
    )
    parser.add_argument("samples", nargs="*", type=Path, help="sample JSON paths")
    parser.add_argument("--from-pending", action="store_true", help="format_pass queue samples")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        print("缺少 DASHSCOPE_API_KEY", file=sys.stderr)
        return 2

    paths: list[Path] = list(args.samples)
    if args.from_pending:
        for p in sorted(SAMPLES.glob("practical_mm_dialogue_*.json")):
            data = json.loads(p.read_text(encoding="utf-8"))
            meta = data.get("meta") or {}
            if meta.get("qa_status") in {"format_pass", "auto_pass"} or meta.get("review_queue"):
                if category_of(data) in SPOTCHECK_CATS:
                    paths.append(p)

    if not paths:
        print("请提供样本路径或 --from-pending", file=sys.stderr)
        return 2

    client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE)
    for path in paths:
        if not path.is_file():
            print(f"missing {path}", file=sys.stderr)
            continue
        info = apply_spotcheck(path, client, args.model)
        if info.get("skipped"):
            print(f"SKIP {path.name}: {info.get('reason')}")
        else:
            oc = info.get("ocr_spotcheck") or {}
            print(
                f"SPOT {path.name}: api_ok={oc.get('api_ok')} verified={oc.get('verified')} "
                f"merchant={oc.get('merchant_legal_name')!r} "
                f"header_person={oc.get('header_person_name')!r} "
                f"core_keys={oc.get('core_keys')} "
                f"keys={oc.get('key_numbers')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
