#!/usr/bin/env python3
"""Validate a practical multimodal dialogue sample against format + automatable dataset rules."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ALLOWED_TASK_TYPES = {
    "看图创作",
    "信息提取与整理",
    "文档翻译",
    "代码debug",
    "逻辑推理",
    "深度研究",
    "多跳搜索",
    "生活/工作/学习实用问题",
}
ALLOWED_SCENARIOS = {"生活", "工作", "学习"}
ALLOWED_DIFFICULTY = {"基础", "中等", "困难"}
ALLOWED_OUTPUT_TYPES = {
    "摘要",
    "表格",
    "翻译稿",
    "修复方案",
    "研究报告",
    "行动计划",
    "创作文案",
    "推理结论",
}

# task_type -> allowed output_types (first entry is preferred default)
TASK_OUTPUT_TYPES: dict[str, tuple[str, ...]] = {
    "看图创作": ("创作文案",),
    "信息提取与整理": ("表格",),
    "文档翻译": ("翻译稿",),
    "生活/工作/学习实用问题": ("行动计划",),
    "逻辑推理": ("推理结论", "摘要"),
    "代码debug": ("修复方案",),
    "深度研究": ("研究报告", "摘要"),
    "多跳搜索": ("研究报告", "摘要"),
}

ROOT_KEYS = {"sample_id", "task_type", "scenario", "images", "dialogue", "final_output", "meta"}
IMAGE_KEYS = {"image_id", "image_path"}
TURN_KEYS = {"turn_id", "role", "content"}
FO_KEYS = {"answer", "output_type", "evidence"}
EVIDENCE_KEYS = {"image_id", "evidence_text"}
META_KEYS = {
    "language",
    "turn_count",
    "image_count",
    "difficulty",
    "routed_task_type",
    "route_confidence",
    "route_reason",
    "source_paths",
    "qa_status",
    "review_queue",
    "ocr_spotcheck",
}

# Only scene folders are hard-bound; chart/receipt folders are modality, not scenario.
CATEGORY_SCENARIO = {
    "生活场景": {"生活"},
    "工作场景": {"工作"},
    "学习材料": {"学习"},
    "文档截图": {"工作", "学习", "生活"},
    "代码报错": {"工作", "学习"},
}

ALLOWED_QA_STATUS = {"format_pass", "human_pass", "rejected", "auto_pass"}

# Tasks / output types that must converge on a final deliverable in the last turn
DELIVERABLE_TASK_TYPES = {
    "看图创作",
    "生活/工作/学习实用问题",
    "信息提取与整理",
}
DELIVERABLE_OUTPUT_TYPES = {"创作文案", "行动计划", "表格"}

FINALIZE_USER = re.compile(
    r"(定稿|最终|确认|发布|完整表|行动计划|交付|整理成|输出一[张份]|可直接|"
    r"final\s*draft|deliverable)",
    re.IGNORECASE,
)

ASSISTANT_DELIVERABLE_PREFIX = re.compile(
    r"^(已按你的要求定稿[：:]\s*|定稿如下[：:]\s*|最终文案[：:]\s*|"
    r"交付表格如下[：:]\s*|完整行动计划如下[：:]\s*|最终交付如下[：:]\s*)"
)

COPY_EXPLAIN_START = re.compile(
    r"^(背景是|因为|这是因为|原因是|图中可见的原因|之所以)"
)

PLACEHOLDER_EVIDENCE = re.compile(
    r"(^见图\b)|(与任务相关的可见内容)|(见图中与任务相关)"
)

# Lazy / incomplete markdown table markers
TABLE_LAZY = re.compile(
    r"(\.{3}|…|（?其他(?:类似)?字段略）?|其余略|字段略|内容略|（省略|略\）)"
)

FIRST_TURN_PLACEHOLDER = re.compile(
    r"(\[图片\]|【图片】|\(图片\)|（图片）|^图片$)"
)

# Fake / malformed image markers models sometimes emit
BAD_IMAGE_MARKER = re.compile(
    r"(</image>)|(<image>\s*img_\d+\s*</image>)|(?<![A-Za-z0-9_])img_\d{3}(?![A-Za-z0-9_])",
    re.IGNORECASE,
)

# Receipt PII: cashier field must be redacted; bare multi-word lowercase latin names banned
CASHIER_PLAIN = re.compile(
    r"(?i)(收银员|Cashier)\s*[:：|]\s*(?!\*{2,}|＊{2,}|已脱敏)([^\s|，,。；;]{1,40})"
)
LATIN_PERSON_NAME = re.compile(
    r"(?<![A-Za-z])([a-z]{2,}(?:\s+[a-z]{2,}){1,3})(?![A-Za-z])"
)

MIN_FIRST_USER_INTENT_CHARS = 8
MIN_COPY_ANSWER_CHARS = 40
MIN_ANSWER_BODY_RATIO = 0.70


def _norm_ws(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())


def _strip_deliverable_prefix(text: str) -> str:
    return ASSISTANT_DELIVERABLE_PREFIX.sub("", (text or "").strip())


def _extra_keys(obj: dict, allowed: set[str], prefix: str, errs: list[str]) -> None:
    bad = sorted(set(obj.keys()) - allowed)
    for k in bad:
        errs.append(f"{prefix} unexpected field: {k}")


def _strip_first_user_intent(content: str) -> str:
    text = content.replace("<image>", "")
    text = BAD_IMAGE_MARKER.sub("", text)
    text = FIRST_TURN_PLACEHOLDER.sub("", text)
    text = re.sub(r"\s+", "", text)
    return text


def _collect_text_blobs(data: dict) -> str:
    parts: list[str] = []
    for turn in data.get("dialogue") or []:
        if isinstance(turn, dict) and isinstance(turn.get("content"), str):
            parts.append(turn["content"])
    fo = data.get("final_output") if isinstance(data.get("final_output"), dict) else {}
    if isinstance(fo.get("answer"), str):
        parts.append(fo["answer"])
    for ev in fo.get("evidence") or []:
        if isinstance(ev, dict) and isinstance(ev.get("evidence_text"), str):
            parts.append(ev["evidence_text"])
    return "\n".join(parts)


def _check_receipt_redaction(data: dict, errs: list[str]) -> None:
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    src = meta.get("source_paths") or []
    is_receipt = False
    if isinstance(src, list):
        for sp in src:
            if isinstance(sp, str) and sp.startswith("收据/"):
                is_receipt = True
                break
    if not is_receipt:
        return
    blob = _collect_text_blobs(data)
    m = CASHIER_PLAIN.search(blob)
    if m:
        val = (m.group(2) or "").strip()
        if val and not re.fullmatch(r"[\*＊]+", val) and val != "已脱敏":
            errs.append(
                f"receipt PII: cashier/收银员 value must be redacted (***/已脱敏), got {val!r}"
            )
    for pm in LATIN_PERSON_NAME.finditer(blob):
        name = pm.group(1)
        # skip common non-name phrases
        if name in {"taman daya", "johor bahru", "cash bill", "modelling clay", "kiddy fish"}:
            continue
        if "sdn" in name or "bhd" in name:
            continue
        errs.append(
            f"receipt PII: unredacted lowercase person-like name {name!r} "
            f"(use *** for header/cashier names)"
        )
        break


def _markdown_table_data_rows(text: str) -> int:
    """Count non-separator table rows that look like data (have pipes)."""
    rows = 0
    for line in text.splitlines():
        s = line.strip()
        if "|" not in s:
            continue
        # separator like |---|---|
        if re.match(r"^\|?[\s:\-|]+\|?$", s):
            continue
        rows += 1
    # rows includes header; data rows = rows - 1
    return max(0, rows - 1)


def _check_table_quality(text: str, label: str, errs: list[str]) -> None:
    if TABLE_LAZY.search(text):
        errs.append(f"{label}: markdown table looks incomplete (ellipsis/略/其他字段略)")
    data_rows = _markdown_table_data_rows(text)
    # Wide single-row delivery tables (e.g. one receipt summary) are valid;
    # lazy ellipsis rows are already banned above.
    if data_rows < 1:
        errs.append(
            f"{label}: markdown table needs header + at least 1 data row "
            f"(found {data_rows} data rows)"
        )


def validate_sample(data: dict, *, check_image_files: bool = False, images_root: Path | None = None) -> list[str]:
    errs: list[str] = []

    if not isinstance(data, dict):
        return ["root must be a JSON object"]

    _extra_keys(data, ROOT_KEYS, "root", errs)

    sample_id = data.get("sample_id")
    if not isinstance(sample_id, str) or not sample_id.strip():
        errs.append("sample_id missing or empty")
    elif not re.match(r"^practical_mm_dialogue_\d{6}$", sample_id):
        errs.append("sample_id should match practical_mm_dialogue_XXXXXX")

    task_type = data.get("task_type")
    if task_type not in ALLOWED_TASK_TYPES:
        errs.append(f"task_type invalid: {task_type!r}")

    scenario = data.get("scenario")
    if scenario not in ALLOWED_SCENARIOS:
        errs.append(f"scenario invalid: {scenario!r}")

    images = data.get("images")
    if not isinstance(images, list) or not images:
        errs.append("images must be a non-empty list")
        images = []
    elif not (1 <= len(images) <= 10):
        errs.append(f"image_count must be 1..10, got {len(images)}")

    image_ids: list[str] = []
    for i, im in enumerate(images):
        if not isinstance(im, dict):
            errs.append(f"images[{i}] must be object")
            continue
        _extra_keys(im, IMAGE_KEYS, f"images[{i}]", errs)
        iid = im.get("image_id")
        ip = im.get("image_path")
        if not isinstance(iid, str) or not iid.strip():
            errs.append(f"images[{i}].image_id missing")
        else:
            if iid in image_ids:
                errs.append(f"duplicate image_id: {iid}")
            image_ids.append(iid)
        if not isinstance(ip, str) or not ip.strip():
            errs.append(f"images[{i}].image_path missing")
        elif check_image_files and images_root is not None:
            p = images_root / ip
            if not p.is_file():
                errs.append(f"image file missing: {p}")

    dialogue = data.get("dialogue")
    if not isinstance(dialogue, list) or not dialogue:
        errs.append("dialogue must be a non-empty list")
        dialogue = []
    elif not (3 <= len(dialogue) <= 10):
        errs.append(f"turn_count must be 3..10, got {len(dialogue)}")

    marker_total = 0
    prev_role = None
    for i, turn in enumerate(dialogue):
        if not isinstance(turn, dict):
            errs.append(f"dialogue[{i}] must be object")
            continue
        _extra_keys(turn, TURN_KEYS, f"dialogue[{i}]", errs)
        tid = turn.get("turn_id")
        role = turn.get("role")
        content = turn.get("content")
        if tid != i + 1:
            errs.append(f"dialogue[{i}].turn_id expected {i + 1}, got {tid!r}")
        if role not in {"user", "assistant"}:
            errs.append(f"dialogue[{i}].role invalid: {role!r}")
        if not isinstance(content, str) or not content.strip():
            errs.append(f"dialogue[{i}].content empty")
            content = ""
        else:
            n_mark = content.count("<image>")
            marker_total += n_mark
            if role == "assistant" and n_mark > 0:
                errs.append(f"dialogue[{i}]: <image> must only appear in user turns")
            if BAD_IMAGE_MARKER.search(content):
                errs.append(
                    f"dialogue[{i}]: malformed image marker "
                    f"(ban </image>, <image>img_xxx</image>, bare img_00x)"
                )
        if i == 0 and role != "user":
            errs.append("dialogue must start with user")
        if i == 0 and role == "user" and isinstance(content, str):
            intent = _strip_first_user_intent(content)
            if len(intent) < MIN_FIRST_USER_INTENT_CHARS:
                errs.append(
                    f"first user turn must state a task intent "
                    f"(≥{MIN_FIRST_USER_INTENT_CHARS} chars after removing <image>/placeholders), "
                    f"got {len(intent)}"
                )
        if prev_role is not None and role == prev_role:
            errs.append(f"dialogue[{i}] role should alternate, got consecutive {role}")
        prev_role = role

    if images and marker_total != len(images):
        errs.append(f"<image> count {marker_total} != images length {len(images)}")

    fo = data.get("final_output")
    if not isinstance(fo, dict):
        errs.append("final_output must be object")
        fo = {}
    else:
        _extra_keys(fo, FO_KEYS, "final_output", errs)

    answer = fo.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        errs.append("final_output.answer missing or empty")
    ot = fo.get("output_type")
    if ot not in ALLOWED_OUTPUT_TYPES:
        errs.append(f"final_output.output_type invalid: {ot!r}")
    else:
        allowed_ot = TASK_OUTPUT_TYPES.get(task_type) if task_type in ALLOWED_TASK_TYPES else None
        if allowed_ot is not None and ot not in allowed_ot:
            errs.append(
                f"output_type={ot!r} not allowed for task_type={task_type!r} "
                f"(expected one of {list(allowed_ot)})"
            )
        if isinstance(answer, str) and answer.strip():
            if ot == "表格":
                if "|" not in answer:
                    errs.append("output_type=表格 but answer has no markdown table pipes")
                else:
                    _check_table_quality(answer, "final_output.answer", errs)
            if ot == "行动计划":
                if not re.search(r"(^|\n)\s*([0-9]+[\.、\)]|[-*•])\s+", answer):
                    errs.append("output_type=行动计划 but answer has no numbered/bulleted steps")

    evidence = fo.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errs.append("final_output.evidence must be non-empty list")
    else:
        for j, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                errs.append(f"evidence[{j}] must be object")
                continue
            _extra_keys(ev, EVIDENCE_KEYS, f"evidence[{j}]", errs)
            eid = ev.get("image_id")
            et = ev.get("evidence_text")
            if eid not in image_ids:
                errs.append(f"evidence[{j}].image_id not in images: {eid!r}")
            if not isinstance(et, str) or not et.strip():
                errs.append(f"evidence[{j}].evidence_text empty")
            elif PLACEHOLDER_EVIDENCE.search(et.strip()):
                errs.append(f"evidence[{j}].evidence_text looks like placeholder")

    # answer must be subset of last assistant (no silent extras in answer)
    last_assistant = None
    last_user = None
    for turn in reversed(dialogue):
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        if role == "assistant" and last_assistant is None:
            last_assistant = turn.get("content") or ""
        elif role == "user" and last_assistant is not None and last_user is None:
            last_user = turn.get("content") or ""
            break

    needs_deliverable = (
        task_type in DELIVERABLE_TASK_TYPES or ot in DELIVERABLE_OUTPUT_TYPES
    )
    if needs_deliverable and isinstance(last_user, str):
        if not FINALIZE_USER.search(last_user):
            errs.append(
                "last user turn must request final deliverable "
                "(e.g. 定稿/交付/完整表/行动计划/整理成)"
            )

    if isinstance(answer, str) and isinstance(last_assistant, str) and answer.strip():
        a = _norm_ws(answer)
        b = _norm_ws(last_assistant)
        if a not in b:
            errs.append(
                "final_output.answer must be contained in the last assistant turn "
                "(no content only in answer)"
            )
        elif needs_deliverable:
            body = _norm_ws(_strip_deliverable_prefix(last_assistant))
            if body and len(a) < MIN_ANSWER_BODY_RATIO * len(body) and a != body:
                errs.append(
                    "final_output.answer must be the main body of the last assistant "
                    "turn (deliverable), not a short aside from an earlier draft"
                )
        if ot == "创作文案":
            if len(answer.strip()) < MIN_COPY_ANSWER_CHARS:
                errs.append(
                    f"output_type=创作文案 requires answer length "
                    f">={MIN_COPY_ANSWER_CHARS}, got {len(answer.strip())}"
                )
            if COPY_EXPLAIN_START.search(answer.strip()):
                errs.append(
                    "output_type=创作文案 answer looks like an explanation, "
                    "not publishable copy (last turn must be the final copy itself)"
                )
        # Also reject lazy tables hiding only in last assistant when answer is 表格
        if ot == "表格" and "|" in last_assistant:
            if TABLE_LAZY.search(last_assistant):
                errs.append(
                    "last assistant turn: markdown table looks incomplete "
                    "(ellipsis/略/其他字段略)"
                )

    meta = data.get("meta")
    if not isinstance(meta, dict):
        errs.append("meta must be object")
        meta = {}
    else:
        _extra_keys(meta, META_KEYS, "meta", errs)

    if meta.get("language") not in {"zh", "zh-CN", "zh_cn"}:
        errs.append(f"meta.language expected zh, got {meta.get('language')!r}")
    if meta.get("turn_count") != len(dialogue):
        errs.append(
            f"meta.turn_count {meta.get('turn_count')!r} != len(dialogue) {len(dialogue)}"
        )
    if meta.get("image_count") != len(images):
        errs.append(
            f"meta.image_count {meta.get('image_count')!r} != len(images) {len(images)}"
        )
    if meta.get("difficulty") not in ALLOWED_DIFFICULTY:
        errs.append(f"meta.difficulty invalid: {meta.get('difficulty')!r}")

    qs = meta.get("qa_status")
    if qs is not None and qs not in ALLOWED_QA_STATUS:
        errs.append(
            f"meta.qa_status invalid: {qs!r} "
            f"(allowed: format_pass/human_pass/rejected; auto_pass legacy-ok)"
        )
    rq = meta.get("review_queue")
    if rq is not None and not isinstance(rq, bool):
        errs.append(f"meta.review_queue must be bool if present, got {type(rq).__name__}")
    ocr = meta.get("ocr_spotcheck")
    if ocr is not None and not isinstance(ocr, (dict, list)):
        errs.append(
            f"meta.ocr_spotcheck must be object or list if present, got {type(ocr).__name__}"
        )

    # Extraction: spotcheck key_numbers must land in the delivered table (answer).
    # api_ok/verified semantics unchanged — this only catches "read but dropped".
    if task_type == "信息提取与整理" and isinstance(ocr, dict):
        keys = ocr.get("key_numbers")
        if isinstance(keys, list) and keys and isinstance(answer, str):
            ans_norm = _norm_ws(answer)
            missing_keys: list[str] = []
            for kn in keys:
                if not isinstance(kn, str) or not kn.strip():
                    continue
                if _norm_ws(kn) not in ans_norm:
                    missing_keys.append(kn.strip())
            if missing_keys:
                preview = ", ".join(missing_keys[:8])
                more = f" (+{len(missing_keys) - 8} more)" if len(missing_keys) > 8 else ""
                errs.append(
                    "ocr_spotcheck.key_numbers missing from final_output.answer: "
                    f"{preview}{more}"
                )

    # scenario vs source_paths category (scene folders only)
    src = meta.get("source_paths")
    if isinstance(src, list) and src and scenario in ALLOWED_SCENARIOS:
        for sp in src:
            if not isinstance(sp, str) or "/" not in sp:
                continue
            cat = sp.split("/", 1)[0]
            allowed = CATEGORY_SCENARIO.get(cat)
            if allowed and scenario not in allowed:
                errs.append(
                    f"scenario={scenario!r} mismatches source category {cat!r} "
                    f"(expected one of {sorted(allowed)})"
                )

    _check_receipt_redaction(data, errs)

    return errs


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate practical multimodal dialogue sample JSON")
    parser.add_argument("path", type=Path, help="sample JSON path")
    parser.add_argument(
        "--check-files",
        action="store_true",
        help="also check image files exist under sample parent dir",
    )
    args = parser.parse_args()
    data = json.loads(args.path.read_text(encoding="utf-8"))
    root = args.path.parent if args.check_files else None
    errs = validate_sample(data, check_image_files=args.check_files, images_root=root)
    if errs:
        print(f"FAIL {args.path} ({len(errs)} errors)")
        for e in errs:
            print(f"  - {e}")
        return 1
    print(f"OK {args.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
