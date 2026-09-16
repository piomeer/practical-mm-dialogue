#!/usr/bin/env python3
"""Generate full dialogue samples via Qwen: route → write → validate → repair."""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from validate_sample import validate_sample  # noqa: E402

PROMPTS = ROOT / "prompts" / "qwen"
LOG_DIR = ROOT / "logs"
USAGE_PATH = LOG_DIR / "qwen_token_usage.jsonl"
GEN_LOG = LOG_DIR / "qwen_generate_runs.jsonl"
SAMPLES_OUT = ROOT / "实用多轮对话类图文数据集" / "samples"
DEFAULT_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = "qwen3.5-flash"

DEFAULT_IMAGES = [
    "收据/0003sroie_x00016469612.jpg",
    "生活场景/0005a_picnic_spread_with_waffles_and_berries.jpg",
    "工作场景/0001abbotsford_house_study_room.jpg",
    "文档截图/0001slide_2012_02_20fy11roadshow_12022102244.jpg",
    "图表推理/0001chartqa_10095.jpg",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_priors() -> dict:
    return json.loads((PROMPTS / "priors.json").read_text(encoding="utf-8"))


def read_prompt(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


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


def category_of(rel: str) -> str:
    return Path(rel).parts[0] if Path(rel).parts else ""


def next_sample_id(samples_dir: Path) -> str:
    max_n = 0
    for p in samples_dir.glob("practical_mm_dialogue_*.json"):
        m = re.search(r"practical_mm_dialogue_(\d{6})", p.name)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return f"practical_mm_dialogue_{max_n + 1:06d}"


def chat_vision(
    client: OpenAI,
    model: str,
    system: str,
    user_text: str,
    image_paths: list[Path],
    stage: str,
    local_paths: list[str],
) -> tuple[str, dict]:
    content: list[dict] = []
    for p in image_paths:
        content.append({"type": "image_url", "image_url": {"url": image_to_data_url(p)}})
    content.append({"type": "text", "text": user_text})

    started = time.perf_counter()
    started_at = utc_now()
    try:
        resp = client.chat.completions.create(
            model=model,
            temperature=1.0,
            top_p=0.95,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
        ended_at = utc_now()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        u = resp.usage
        usage = {
            "model": model,
            "stage": stage,
            "local_paths": local_paths,
            "prompt_tokens": getattr(u, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(u, "completion_tokens", 0) or 0,
            "total_tokens": getattr(u, "total_tokens", 0) or 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_ms": elapsed_ms,
            "ok": True,
            "error": None,
        }
        append_jsonl(USAGE_PATH, usage)
        text = (resp.choices[0].message.content or "").strip()
        return text, usage
    except Exception as e:
        ended_at = utc_now()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        usage = {
            "model": model,
            "stage": stage,
            "local_paths": local_paths,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "started_at": started_at,
            "ended_at": ended_at,
            "elapsed_ms": elapsed_ms,
            "ok": False,
            "error": str(e),
        }
        append_jsonl(USAGE_PATH, usage)
        raise


def ensure_image_markers(sample: dict) -> dict:
    """Move all <image> markers onto user turns only; count == len(images)."""
    images = sample.get("images") or []
    dialogue = sample.get("dialogue") or []
    if not images or not dialogue:
        return sample
    need = len(images)
    # Always strip from every turn first (including assistant)
    for t in dialogue:
        if isinstance(t, dict) and isinstance(t.get("content"), str):
            t["content"] = t["content"].replace("<image>", "")
    user_turns = [t for t in dialogue if isinstance(t, dict) and t.get("role") == "user"]
    for i, t in enumerate(user_turns):
        if i >= need:
            break
        c = (t.get("content") or "").lstrip()
        t["content"] = "<image>" + c
    if len(user_turns) < need and user_turns:
        extra = need - len(user_turns)
        user_turns[0]["content"] = ("<image>" * extra) + (user_turns[0].get("content") or "")
    elif not user_turns and dialogue:
        dialogue[0]["role"] = "user"
        dialogue[0]["content"] = ("<image>" * need) + str(dialogue[0].get("content") or "")
    return sample


def sync_final_answer(sample: dict) -> dict:
    """If answer empty or not ⊆ last assistant, set answer to last assistant content."""
    dialogue = sample.get("dialogue") or []
    fo = sample.get("final_output")
    if not isinstance(fo, dict):
        return sample
    last_assistant = None
    for turn in reversed(dialogue):
        if isinstance(turn, dict) and turn.get("role") == "assistant":
            last_assistant = turn.get("content") or ""
            break
    if not isinstance(last_assistant, str) or not last_assistant.strip():
        return sample
    answer = fo.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        fo["answer"] = last_assistant
        return sample
    a = re.sub(r"\s+", "", answer.strip())
    b = re.sub(r"\s+", "", last_assistant.strip())
    # Only allow answer ⊆ last assistant; if answer has extras, shrink to last assistant
    if a not in b:
        fo["answer"] = last_assistant
    return sample


def _keep(obj: dict, allowed: set[str]) -> dict:
    return {k: v for k, v in obj.items() if k in allowed}


def normalize_sample(
    sample: dict,
    sample_id: str,
    rels: list[str],
    task_type: str,
    scenario: str,
    route_meta: dict,
) -> dict:
    from validate_sample import (  # local import ok
        EVIDENCE_KEYS,
        FO_KEYS,
        IMAGE_KEYS,
        META_KEYS,
        ROOT_KEYS,
        TURN_KEYS,
        CATEGORY_SCENARIO,
    )

    # Scenario alignment with first source category when clearly constrained
    cat = Path(rels[0]).parts[0] if rels else ""
    allowed_sc = CATEGORY_SCENARIO.get(cat)
    if allowed_sc and scenario not in allowed_sc:
        scenario = sorted(allowed_sc)[0]

    sample = _keep(sample if isinstance(sample, dict) else {}, ROOT_KEYS)
    sample["sample_id"] = sample_id
    sample["task_type"] = task_type
    sample["scenario"] = scenario

    images = sample.get("images") or []
    new_images = []
    for i, rel in enumerate(rels):
        src_name = Path(rel).name
        iid = f"img_{i + 1:03d}"
        if i < len(images) and isinstance(images[i], dict) and images[i].get("image_id"):
            iid = str(images[i]["image_id"])
        new_images.append({"image_id": iid, "image_path": f"images/{src_name}"})
    sample["images"] = new_images

    dialogue = sample.get("dialogue") or []
    cleaned = []
    for i, turn in enumerate(dialogue):
        if not isinstance(turn, dict):
            continue
        t = _keep(turn, TURN_KEYS)
        t["turn_id"] = i + 1
        cleaned.append(t)
    sample["dialogue"] = cleaned
    sample = ensure_image_markers(sample)
    sample = sync_final_answer(sample)

    fo = sample.get("final_output") if isinstance(sample.get("final_output"), dict) else {}
    fo = _keep(fo, FO_KEYS)
    raw_ev = fo.get("evidence") if isinstance(fo.get("evidence"), list) else []
    fixed_ev = []
    for ev in raw_ev:
        if not isinstance(ev, dict):
            continue
        item = _keep(ev, EVIDENCE_KEYS)
        if not item.get("image_id") or not isinstance(item.get("evidence_text"), str):
            continue
        text = item["evidence_text"].strip()
        if not text:
            continue  # do NOT invent placeholder — leave for validator/repair
        item["evidence_text"] = text
        fixed_ev.append(item)
    # Ensure at least one evidence slot per image id if model provided none usable:
    # still do not invent text; repair must fill
    if not fixed_ev and new_images:
        # keep structure empty list so validator fails → repair
        fixed_ev = []
    # Re-bind image_ids that exist
    id_set = {im["image_id"] for im in new_images}
    fixed_ev = [e for e in fixed_ev if e.get("image_id") in id_set]
    fo["evidence"] = fixed_ev
    if not fo.get("output_type"):
        fo["output_type"] = "摘要"
    if not isinstance(fo.get("answer"), str):
        fo["answer"] = ""
    sample["final_output"] = fo
    sample = sync_final_answer(sample)

    meta_in = sample.get("meta") if isinstance(sample.get("meta"), dict) else {}
    meta = _keep(meta_in, META_KEYS)
    meta["language"] = "zh"
    meta["turn_count"] = len(sample.get("dialogue") or [])
    meta["image_count"] = len(new_images)
    if meta.get("difficulty") not in {"基础", "中等", "困难"}:
        meta["difficulty"] = "中等"
    meta["routed_task_type"] = route_meta.get("task_type")
    meta["route_confidence"] = route_meta.get("confidence")
    meta["route_reason"] = route_meta.get("reason")
    meta["source_paths"] = rels
    meta["qa_status"] = "auto_pass"
    sample["meta"] = meta
    return sample


def copy_images_to_samples(rels: list[str], samples_dir: Path) -> None:
    img_dir = samples_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    for rel in rels:
        src = ROOT / "data" / rel
        dest = img_dir / Path(rel).name
        if src.is_file():
            shutil.copy2(src, dest)


def generate_one(
    client: OpenAI,
    model: str,
    rels: list[str],
    sample_id: str,
    max_repair: int,
    priors: dict,
) -> tuple[dict | None, dict]:
    abs_paths = [ROOT / "data" / r for r in rels]
    for p, r in zip(abs_paths, rels):
        if not p.is_file():
            return None, {"ok": False, "error": f"missing {r}", "sample_id": sample_id}

    cat = category_of(rels[0])
    prior = priors["category_priors"].get(cat, "信息提取与整理")
    run: dict = {
        "sample_id": sample_id,
        "local_paths": rels,
        "category": cat,
        "prior": prior,
        "model": model,
        "started_at": utc_now(),
    }

    # --- route ---
    route_sys = read_prompt("route.md")
    route_user = (
        f"图片路径：{rels}\n"
        f"目录类别：{cat}\n"
        f"目录 prior（可偏离）：{prior}\n"
        "请输出路由 JSON。"
    )
    route_text, route_usage = chat_vision(
        client, model, route_sys, route_user, abs_paths, "route", rels
    )
    route = extract_json(route_text)
    task_type = route.get("task_type") or prior
    if task_type not in priors["allowed_task_types"]:
        task_type = prior
    scenario = route.get("scenario") or "生活"
    if scenario not in priors["allowed_scenarios"]:
        scenario = "生活"
    run["route"] = route
    run["task_type"] = task_type
    run["scenario"] = scenario
    run["route_tokens"] = route_usage.get("total_tokens", 0)

    # --- write ---
    tmpl_name = priors["write_template_map"].get(task_type, "write_信息提取与整理.md")
    write_sys = read_prompt(tmpl_name)
    write_user = (
        f"sample_id 必须使用：{sample_id}\n"
        f"task_type 必须使用：{task_type}\n"
        f"scenario 建议：{scenario}\n"
        f"图片文件（写入 images[].image_path 时用 images/文件名）：{[Path(r).name for r in rels]}\n"
        f"源路径：{rels}\n"
        "请根据图片写出完整样本 JSON。"
    )
    write_text, write_usage = chat_vision(
        client, model, write_sys, write_user, abs_paths, "write", rels
    )
    sample = extract_json(write_text)
    sample = normalize_sample(sample, sample_id, rels, task_type, scenario, route)
    run["write_tokens"] = write_usage.get("total_tokens", 0)

    errs = validate_sample(sample)
    run["validate_after_write"] = errs
    repairs = 0
    while errs and repairs < max_repair:
        repairs += 1
        repair_sys = read_prompt("repair.md")
        repair_user = (
            f"校验错误列表：\n"
            + "\n".join(f"- {e}" for e in errs)
            + "\n\n当前 JSON：\n"
            + json.dumps(sample, ensure_ascii=False)
            + "\n\n请输出修复后的完整 JSON。"
        )
        repair_text, repair_usage = chat_vision(
            client, model, repair_sys, repair_user, abs_paths, f"repair_{repairs}", rels
        )
        sample = extract_json(repair_text)
        sample = normalize_sample(sample, sample_id, rels, task_type, scenario, route)
        run.setdefault("repair_tokens", 0)
        run["repair_tokens"] += repair_usage.get("total_tokens", 0)
        errs = validate_sample(sample)
        run[f"validate_after_repair_{repairs}"] = errs

    run["repair_rounds"] = repairs
    run["final_errors"] = errs
    run["ok"] = len(errs) == 0
    run["ended_at"] = utc_now()

    if run["ok"]:
        copy_images_to_samples(rels, SAMPLES_OUT)
        out_path = SAMPLES_OUT / f"{sample_id}.json"
        out_path.write_text(
            json.dumps(sample, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        run["out_path"] = str(out_path.relative_to(ROOT))
    else:
        fail_dir = LOG_DIR / "failed_samples"
        fail_dir.mkdir(parents=True, exist_ok=True)
        fail_path = fail_dir / f"{sample_id}.json"
        fail_path.write_text(
            json.dumps({"sample": sample, "errors": errs, "run": run}, ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        run["fail_path"] = str(fail_path.relative_to(ROOT))

    append_jsonl(GEN_LOG, run)
    return sample if run["ok"] else None, run


def main() -> int:
    parser = argparse.ArgumentParser(description="Qwen route→write→validate→repair")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--paths", nargs="*", default=DEFAULT_IMAGES)
    parser.add_argument("--max-repair", type=int, default=2)
    parser.add_argument(
        "--group-as-one",
        action="store_true",
        help="treat all --paths as one multi-image sample",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        print("缺少 DASHSCOPE_API_KEY", file=sys.stderr)
        return 2

    priors = load_priors()
    client = OpenAI(api_key=api_key, base_url=DEFAULT_BASE)
    SAMPLES_OUT.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    if args.group_as_one:
        jobs = [list(args.paths)]
    else:
        jobs = [[p] for p in args.paths]

    wall0 = time.perf_counter()
    ok_n = fail_n = 0
    token_sum = 0
    # Reserve IDs even when a job fails (failed JSON goes to logs/, not samples/)
    next_n = int(next_sample_id(SAMPLES_OUT).rsplit("_", 1)[-1])

    for job in jobs:
        sid = f"practical_mm_dialogue_{next_n:06d}"
        next_n += 1
        print(f"=== {sid}  paths={job} ===", flush=True)
        try:
            sample, run = generate_one(
                client, args.model, job, sid, args.max_repair, priors
            )
        except Exception as e:
            fail_n += 1
            print(f"  FATAL {e}", flush=True)
            append_jsonl(
                GEN_LOG,
                {
                    "sample_id": sid,
                    "local_paths": job,
                    "ok": False,
                    "error": str(e),
                    "ended_at": utc_now(),
                },
            )
            continue

        for k in ("route_tokens", "write_tokens", "repair_tokens"):
            token_sum += run.get(k, 0) or 0

        if run.get("ok"):
            ok_n += 1
            print(
                f"  OK task={run.get('task_type')} conf={run.get('route', {}).get('confidence')} "
                f"repairs={run.get('repair_rounds')} -> {run.get('out_path')}",
                flush=True,
            )
        else:
            fail_n += 1
            print(
                f"  FAIL task={run.get('task_type')} errors={run.get('final_errors')}",
                flush=True,
            )

    wall_ms = int((time.perf_counter() - wall0) * 1000)
    print("---")
    print(f"ok={ok_n} fail={fail_n} jobs={len(jobs)}")
    print(f"approx_stage_tokens_sum={token_sum} wall_elapsed_ms={wall_ms}")
    print(f"usage_log={USAGE_PATH}")
    print(f"run_log={GEN_LOG}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
