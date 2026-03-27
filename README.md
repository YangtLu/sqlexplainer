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
│   ├── query.sql          # 待解释 SQL（必须且仅有 1 个 .sql 文件）
│   └── result.csv         # SQL 查询结果（可选，建议提供）
├── comments/
│   ├── student_info.sql   # 表注释与字段注释
│   └── ...
├── example/
│   ├── input1/            # 示例 1（含 query.sql + comments/）
│   ├── input2/            # 示例 2（含 query.sql + comments/）
│   └── input3/            # 示例 3（三表复杂 JOIN）
└── output/
```

## 运行

```bash
cp config/api_config.json config/api_config.local.json
# 编辑 config/api_config.local.json，填入 api_key / model
python sql_explainer.py \
  --input-dir input \
  --comments-dir comments \
  --output output/explanation.md \
  --config config/api_config.local.json
```

### 本地预览（不调用 LLM API）

```bash
python sql_explainer.py --input-dir input --comments-dir comments --dry-run --config config/api_config.local.json
```

## API 配置文件（新增）

请把 API 相关配置集中放到 JSON 文件中：

```json
{
  "api_url": "https://api.openai.com/v1/chat/completions",
  "api_key": "your_api_key_here",
  "model": "gpt-4o-mini",
  "timeout": 60
}
```

默认读取路径：`config/api_config.json`，也可以通过 `--config` 指定其他文件。

## 示例文件组织（已按目录提供）

你提到“示例应该直接生成在 input 里面”，仓库现在已内置：

- 默认可直接运行的示例在：
  - `input/query.sql`
  - `comments/student_info.sql`
- 另外在 `example/` 下提供多套示例目录，便于切换且避免冲突：
  - `example/input1/`（示例 1）
  - `example/input2/`（示例 2）
  - `example/input3/`（示例 3，三表复杂 JOIN）

### 示例 1：统计各城市成年学生数量

- SQL：`example/input1/query.sql`
- 注释：`example/input1/comments/student_info.sql`
- 结果：`example/input1/result.csv`

预期解释重点：
- 查询目标：按城市统计成年学生人数；
- 逻辑步骤：过滤 `age >= 18`、按 `city` 分组、`COUNT(*)` 聚合、按人数降序排序；
- 结果字段：`city` 与 `adult_count` 的业务含义。

### 示例 2：找出每个班级平均成绩最高的前 3 个班

- SQL：`example/input2/query.sql`
- 注释：`example/input2/comments/exam_scores.sql`
- 结果：`example/input2/result.csv`

预期解释重点：
- 查询目标：在指定学期里评估班级整体表现；
- 逻辑步骤：学期过滤、班级分组、`AVG(score)` 聚合、排序并截取前 3；
- 风险提醒：平均分可能受样本量影响，可补充最小样本数约束。

### 示例 3：按月按地区分析支付订单 GMV 与品类结构

- SQL：`example/input3/query.sql`
- 注释：
  - `example/input3/comments/fact_orders.sql`
  - `example/input3/comments/fact_order_items.sql`
  - `example/input3/comments/dim_products.sql`
- 结果：`example/input3/result.csv`

预期解释重点：
- 查询目标：统计 2025Q1 各地区每月支付订单表现及电子品类贡献；
- 逻辑步骤：CTE 过滤支付订单、与明细表内连接、与商品维表左连接、订单粒度聚合再月-地区聚合、`HAVING` 过滤低样本、窗口函数排名；
- 风险提醒：类目缺失导致 `LEFT JOIN` 空值、`HAVING` 可能筛掉长尾地区、占比字段存在除零保护逻辑。

### 从示例目录切换到运行目录

如果你想把某个示例直接切到 `input/` 与 `comments/` 下运行：

```bash
# 切换到示例 1
cp example/input1/query.sql input/query.sql
cp example/input1/comments/*.sql comments/
cp example/input1/result.csv input/result.csv

# 或切换到示例 2
cp example/input2/query.sql input/query.sql
cp example/input2/comments/*.sql comments/
cp example/input2/result.csv input/result.csv

# 或切换到示例 3
cp example/input3/query.sql input/query.sql
cp example/input3/comments/*.sql comments/
cp example/input3/result.csv input/result.csv
```

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
   - 请在 `--config` 对应 JSON 文件中设置 `api_key`。

2. **报错 “Expected exactly one SQL file”**
   - `input/` 下必须且仅能有一个 `.sql` 查询文件。

3. **某些字段注释没被识别**
   - 请确认注释语句符合 `COMMENT ON COLUMN ... IS '...';` 形式。
