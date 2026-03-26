#!/usr/bin/env python3
"""Generate natural language explanations for SQL using schema comments and an LLM API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from urllib import error, request


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


def build_messages(sql_text: str, schema_context: str) -> List[Dict[str, str]]:
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
""".strip()

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def call_llm_api(config: Config, messages: List[Dict[str, str]]) -> str:
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.model,
        "messages": messages,
        "temperature": 0.2,
    }

    req = request.Request(
        config.api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=config.timeout) as resp:
            raw = resp.read().decode("utf-8")
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM API HTTP error {exc.code}: {body}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"LLM API connection error: {exc}") from exc

    data = json.loads(raw)

    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "Unexpected LLM API response format. Raw response:\n"
            + json.dumps(data, ensure_ascii=False, indent=2)
        ) from exc


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
        "--api-url",
        default=os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions"),
        help="LLM API endpoint. Can also be set by LLM_API_URL env var.",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("LLM_API_KEY", ""),
        help="LLM API key. Can also be set by LLM_API_KEY env var.",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        help="Model name. Can also be set by LLM_MODEL env var.",
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
    messages = build_messages(sql_text, schema_context)

    if args.dry_run:
        print("[DRY RUN] Parsed schema context:\n")
        print(schema_context)
        print("\n[DRY RUN] Prompt preview:\n")
        print(messages[1]["content"][:1200])
        return 0

    if not args.api_key:
        print(
            "Missing API key. Set --api-key or LLM_API_KEY environment variable.",
            file=sys.stderr,
        )
        return 1

    explanation = call_llm_api(
        Config(
            api_url=args.api_url,
            api_key=args.api_key,
            model=args.model,
            timeout=args.timeout,
        ),
        messages,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(explanation + "\n", encoding="utf-8")

    print(f"Explanation saved to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
