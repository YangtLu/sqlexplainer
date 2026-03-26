# SQL Explainer

将复杂 SQL 查询转换为自然语言说明的脚本项目。

## 功能

- 从 `input/` 目录读取 1 个待解释 SQL 文件。
- 从 `comments/` 目录读取多个建表/注释 SQL 文件，提取：
  - `COMMENT ON TABLE ... IS '...'`
  - `COMMENT ON COLUMN ... IS '...'`
- 把 SQL 与注释上下文拼装成高质量提示词。
- 调用兼容 Chat Completions 格式的 LLM API 生成中文解释。
- 输出到 `output/explanation.md`。

## 安装

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> 当前脚本仅使用 Python 标准库，`requirements.txt` 为空占位。

## 目录约定

```text
.
├── input/
│   └── query.sql          # 待解释 SQL（必须且仅有 1 个 .sql 文件）
├── comments/
│   ├── student_info.sql   # 表注释与字段注释
│   └── ...
└── output/
```

## 运行

```bash
export LLM_API_KEY="your_api_key"
python sql_explainer.py \
  --input-dir input \
  --comments-dir comments \
  --output output/explanation.md \
  --api-url https://api.openai.com/v1/chat/completions \
  --model gpt-4o-mini
```

### 本地预览（不调用 LLM API）

```bash
python sql_explainer.py --input-dir input --comments-dir comments --dry-run
```

也可以全部用命令参数传入，不依赖环境变量。

## 示例注释格式

脚本支持如下格式（可混合大小写）：

```sql
COMMENT ON TABLE student_info IS '学生信息';
COMMENT ON COLUMN id IS '学号';
COMMENT ON COLUMN name IS '姓名';
COMMENT ON COLUMN age IS '年龄';
COMMENT ON COLUMN city IS '城市';
```

以及带表前缀的列注释：

```sql
COMMENT ON COLUMN student_info.id IS '学号';
```

## 常见问题

1. **报错 “Missing API key”**
   - 请设置 `LLM_API_KEY` 或传 `--api-key`。

2. **报错 “Expected exactly one SQL file”**
   - `input/` 下必须且仅能有一个 `.sql` 查询文件。

3. **某些字段注释没被识别**
   - 请确认注释语句符合 `COMMENT ON COLUMN ... IS '...';` 形式。

