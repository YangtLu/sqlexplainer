#!/usr/bin/env python3
"""Generate natural language explanations for SQL using schema comments and an LLM API."""

from __future__ import annotations

import argparse
import csv
import json
import re
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from urllib import error, parse, request


TABLE_COMMENT_RE = re.compile(
    r"COMMENT\s+ON\s+TABLE\s+([\w\.\"']+)\s+IS\s+'((?:''|[^'])*)'\s*;",
    re.IGNORECASE,
)

COLUMN_COMMENT_RE = re.compile(
    r"COMMENT\s+ON\s+COLUMN\s+([\w\.\"']+)\s+IS\s+'((?:''|[^'])*)'\s*;",
    re.IGNORECASE,
)


@dataclass
class TableMeta:
    table_name: str
    table_comment: Optional[str] = None
    columns: Dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    api_url: str
    api_key: str
    model: str
    timeout: int = 60


def load_config_from_file(config_path: Path) -> Config:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file does not exist: {config_path}")

    raw_text = config_path.read_text(encoding="utf-8")
    try:
        config_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in config file {config_path}: {exc}") from exc

    api_url = config_data.get(
        "api_url", "https://api.openai.com/v1/chat/completions"
    )
    api_key = config_data.get("api_key", "")
    model = config_data.get("model", "gpt-4o-mini")
    timeout = int(config_data.get("timeout", 60))
    return Config(api_url=api_url, api_key=api_key, model=model, timeout=timeout)


def normalize_identifier(identifier: str) -> str:
    identifier = identifier.strip().strip('"').strip("'")
    if "." in identifier:
        identifier = identifier.split(".")[-1]
    return identifier.lower()


def read_sql_from_input(input_dir: Path) -> str:
    sql_files = sorted(input_dir.glob("*.sql"))
    if not sql_files:
        raise FileNotFoundError(f"No .sql file found under: {input_dir}")

    if len(sql_files) > 1:
        names = ", ".join(f.name for f in sql_files)
        raise ValueError(
            f"Expected exactly one SQL file under {input_dir}, found: {names}"
        )

    return sql_files[0].read_text(encoding="utf-8").strip()


def parse_comment_sql(sql_text: str, default_table_name: str) -> TableMeta:
    meta = TableMeta(table_name=normalize_identifier(default_table_name))

    table_matches = TABLE_COMMENT_RE.findall(sql_text)
    if table_matches:
        raw_table, comment = table_matches[0]
        meta.table_name = normalize_identifier(raw_table)
        meta.table_comment = comment.replace("''", "'")

    for raw_column, comment in COLUMN_COMMENT_RE.findall(sql_text):
        col_expr = raw_column.strip().strip('"').strip("'")
        if "." in col_expr:
            parts = col_expr.split(".")
            possible_table = normalize_identifier(parts[-2]) if len(parts) >= 2 else None
            col_name = normalize_identifier(parts[-1])
            if possible_table and possible_table != meta.table_name:
                continue
        else:
            col_name = normalize_identifier(col_expr)

        meta.columns[col_name] = comment.replace("''", "'")

    return meta


def load_all_table_meta(comments_dir: Path) -> Dict[str, TableMeta]:
    all_meta: Dict[str, TableMeta] = {}
    for sql_file in sorted(comments_dir.glob("*.sql")):
        table_name = sql_file.stem
        parsed = parse_comment_sql(sql_file.read_text(encoding="utf-8"), table_name)
        all_meta[normalize_identifier(parsed.table_name)] = parsed
    return all_meta


def build_schema_context(all_meta: Dict[str, TableMeta]) -> str:
    if not all_meta:
        return "未提供任何表注释信息。"

    lines: List[str] = []
    for table_name in sorted(all_meta.keys()):
        meta = all_meta[table_name]
        header = f"- 表 `{table_name}`"
        if meta.table_comment:
            header += f"（注释：{meta.table_comment}）"
        lines.append(header)

        if meta.columns:
            for col in sorted(meta.columns.keys()):
                lines.append(f"  - 列 `{col}`：{meta.columns[col]}")
        else:
            lines.append("  - 未解析到列注释")

    return "\n".join(lines)


def _normalize_text_cell(value: Optional[str]) -> str:
    if value is None:
        return ""
    return value.strip()


def _is_missing_text(value: str) -> bool:
    return value == "" or value.lower() in {"null", "none", "na", "n/a"}


def _try_parse_number(value: str) -> Optional[float]:
    try:
        return float(value)
    except ValueError:
        return None


def build_result_context(input_dir: Path) -> str:
    result_candidates = [input_dir / "result.csv", input_dir / "result"]
    result_path = next((p for p in result_candidates if p.exists()), None)
    if result_path is None:
        return "未提供查询结果文件（期望在 input 目录下存在 result.csv）。"

    with result_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    if not fieldnames:
        return f"查询结果文件 `{result_path.name}` 缺少表头，无法分析。"

    row_count = len(rows)
    lines: List[str] = [
        f"- 结果文件：`{result_path.name}`",
        f"- 结果行数：{row_count}",
        f"- 结果字段：{', '.join(fieldnames)}",
    ]

    for col in fieldnames:
        values = [_normalize_text_cell(r.get(col)) for r in rows]
        non_missing = [v for v in values if not _is_missing_text(v)]
        null_rate = 0.0 if row_count == 0 else (row_count - len(non_missing)) / row_count

        numeric_values: List[float] = []
        non_numeric_exists = False
        for v in non_missing:
            n = _try_parse_number(v)
            if n is None:
                non_numeric_exists = True
                break
            numeric_values.append(n)

        if non_missing and not non_numeric_exists:
            avg_val = sum(numeric_values) / len(numeric_values)
            lines.append(
                (
                    f"  - `{col}`: 数值列, non_null={len(non_missing)}, "
                    f"null_rate={null_rate:.2%}, min={min(numeric_values):.4g}, "
                    f"max={max(numeric_values):.4g}, avg={avg_val:.4g}"
                )
            )
        else:
            counts: Dict[str, int] = {}
            for v in non_missing:
                counts[v] = counts.get(v, 0) + 1
            top_values = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:3]
            top_text = ", ".join(f"{v}({n})" for v, n in top_values) if top_values else "无"
            lines.append(
                (
                    f"  - `{col}`: 类别/文本列, non_null={len(non_missing)}, "
                    f"null_rate={null_rate:.2%}, unique={len(counts)}, top={top_text}"
                )
            )

    return "\n".join(lines)


def build_messages(sql_text: str, schema_context: str, result_context: str) -> List[Dict[str, str]]:
    system_prompt = (
        "你是资深数据分析师，擅长把复杂 SQL 翻译为准确、易懂的中文业务说明。"
        "请结合提供的表/字段注释，先说明查询目标，再分步骤解释筛选、关联、聚合、排序与关键函数。"
        "若 SQL 中出现的字段没有注释，要明确提示“注释缺失”，但仍基于 SQL 语义给出解释。"
    )

    user_prompt = f"""
请解释以下 SQL：

```sql
{sql_text}
```

以下是表和字段注释信息：
{schema_context}

输出格式要求：
1. 一段总体业务含义总结。
2. 分点解释执行逻辑（表来源、JOIN 条件、WHERE 条件、分组、聚合、排序、限制条数等）。
3. 单独列出“结果字段含义”列表。
4. 若存在潜在风险（如笛卡尔积、空值影响、过滤条件歧义），请给出提醒。

以下是 SQL 查询结果（CSV）的概览分析，请结合它校验你的解释是否与结果一致：
{result_context}
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _is_dashscope_text_generation_endpoint(api_url: str) -> bool:
    """
    Detect DashScope non-compatible text-generation endpoint.
    """
    try:
        path = parse.urlparse(api_url).path
    except Exception:
        return False
    return path.endswith("/api/v1/services/aigc/text-generation/generation")


def _build_request_payload(config: Config, messages: List[Dict[str, str]]) -> Dict[str, object]:
    """
    Build payload based on target API protocol.
    - OpenAI-compatible chat completions: top-level `messages`
    - DashScope text-generation endpoint: `input.messages` + `parameters`
    """
    if _is_dashscope_text_generation_endpoint(config.api_url):
        return {
            "model": config.model,
            "input": {"messages": messages},
            "parameters": {"temperature": 0.1},
        }

    return {
        "model": config.model,
        "messages": messages,
        "temperature": 0.1,
    }


def _extract_response_text(config: Config, data: Dict[str, object]) -> str:
    """
    Parse response text from different API schemas.
    """
    if _is_dashscope_text_generation_endpoint(config.api_url):
        # DashScope text-generation schema (non-compatible endpoint)
        try:
            output = data["output"]  # type: ignore[index]
            if isinstance(output, dict):
                # Newer responses may nest choices/message similarly
                if "choices" in output:
                    choices = output["choices"]
                    if isinstance(choices, list) and choices:
                        first = choices[0]
                        if isinstance(first, dict):
                            msg = first.get("message")
                            if isinstance(msg, dict):
                                content = msg.get("content")
                                if isinstance(content, str) and content.strip():
                                    return content.strip()

                # Common format: output.text
                text = output.get("text")
                if isinstance(text, str) and text.strip():
                    return text.strip()
        except (KeyError, TypeError):
            pass

    # OpenAI-compatible schema
    try:
        choices = data["choices"]  # type: ignore[index]
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                msg = first.get("message")
                if isinstance(msg, dict):
                    content = msg.get("content")
                    if isinstance(content, str):
                        return content.strip()
    except (KeyError, TypeError):
        pass

    raise ValueError(
        "Unexpected LLM API response format. Raw response:\n"
        + json.dumps(data, ensure_ascii=False, indent=2)
    )


def call_llm_api(config: Config, messages: List[Dict[str, str]], max_retries: int = 2) -> str:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = _build_request_payload(config, messages)

    req = request.Request(
        config.api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    attempts = max(1, max_retries + 1)
    last_exc: Optional[Exception] = None

    for attempt in range(1, attempts + 1):
        try:
            with request.urlopen(req, timeout=config.timeout) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return _extract_response_text(config, data)
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM API HTTP error {exc.code}: {body}") from exc
        except (TimeoutError, socket.timeout) as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
        except error.URLError as exc:
            # socket timeout can also be wrapped in URLError
            if isinstance(exc.reason, TimeoutError):
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(min(2 ** (attempt - 1), 8))
                continue
            raise RuntimeError(f"LLM API connection error: {exc}") from exc

    raise RuntimeError(
        f"LLM API timeout after {config.timeout}s (retried {attempts - 1} times)."
    ) from last_exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate natural language explanation for SQL using comments + LLM API."
    )
    parser.add_argument(
        "--input-dir",
        default="input",
        help="Directory with one SQL query file. Default: input",
    )
    parser.add_argument(
        "--comments-dir",
        default="comments",
        help="Directory containing table comment SQL files. Default: comments",
    )
    parser.add_argument(
        "--output",
        default="output/explanation.md",
        help="Output file path for explanation. Default: output/explanation.md",
    )
    parser.add_argument(
        "--config",
        default="config/api_config.json",
        help="JSON config path containing api_url/api_key/model/timeout. Default: config/api_config.json",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="API timeout in seconds. Default: 60",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call API; only print parsed context and prompt preview.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry times for timeout errors. Default: 2",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)
    comments_dir = Path(args.comments_dir)

    if not input_dir.exists():
        print(f"Input directory does not exist: {input_dir}", file=sys.stderr)
        return 1
    if not comments_dir.exists():
        print(f"Comments directory does not exist: {comments_dir}", file=sys.stderr)
        return 1
    sql_text = read_sql_from_input(input_dir)
    all_meta = load_all_table_meta(comments_dir)
    schema_context = build_schema_context(all_meta)
    result_context = build_result_context(input_dir)
    messages = build_messages(sql_text, schema_context, result_context)

    if args.dry_run:
        print("[DRY RUN] Parsed schema context:\n")
        print(schema_context)
        print("\n[DRY RUN] Parsed result context:\n")
        print(result_context)
        print("\n[DRY RUN] Prompt preview:\n")
        print(messages[1]["content"][:1200])
        return 0

    try:
        config = load_config_from_file(Path(args.config))
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if not config.api_key:
        print(
            "Missing API key in config file. Please set api_key in your JSON config.",
            file=sys.stderr,
        )
        return 1

    if args.timeout:
        config.timeout = args.timeout

    explanation = call_llm_api(config, messages, max_retries=max(0, args.max_retries))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(explanation + "\n", encoding="utf-8")

    print(f"Explanation saved to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
