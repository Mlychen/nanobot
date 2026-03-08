# 教学 Trace 查询工具

## 1. 工具定位

`teaching_trace.py` 是一个独立的教学 trace 查询脚本，用来读取 `logs/teaching_trace.jsonl`，并按人工排查或脚本消费的方式展示教学运行轨迹。

这个工具不挂在 `nanobot` 主 CLI 上，不参与正常运行时编排，只负责读取已经落盘的 trace 文件。

脚本位置：`scripts/teaching_trace.py`

默认 trace 文件位置：`<workspace>/logs/teaching_trace.jsonl`

推荐运行方式：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature
```

## 2. 主要功能

工具支持以下能力：

1. 读取教学 trace JSONL 文件。
2. 跳过坏行 JSON，不因为单行损坏而整体失败。
3. 查询最近 `N` 条 trace。
4. 按 `trace_id` 精确查询单条 trace。
5. 只筛选失败回合。
6. 只筛选 `log_scope=teacher-branch` 的记录。
7. 默认输出人类可读摘要。
8. 通过 `--full` 展开详细字段。
9. 通过 `--json` 输出原始 JSON，便于后续脚本处理。

## 3. 参数总览

| 参数 | 类型 | 作用 | 备注 |
|------|------|------|------|
| `--workspace PATH` | 路径 | 指定 workspace 根目录 | 默认是当前工作目录 |
| `--trace-file PATH` | 路径 | 显式指定 trace 文件路径 | 优先级高于 `--workspace` |
| `--last N` | 整数 | 只显示最近 `N` 条有效 trace | `N<=0` 时返回空结果 |
| `--trace-id ID` | 字符串 | 精确查询某个 `trace_id` | 未命中时返回非零退出码 |
| `--failed` | 开关 | 只显示包含 `failure` 字段的 trace | 可与 `--last` 联用 |
| `--teacher-branch-only` | 开关 | 只显示 `log_scope=teacher-branch` 的记录 | 适合快速隔离教学分支 trace |
| `--full` | 开关 | 在人类摘要模式下展开详细字段 | 对 `--json` 无额外影响 |
| `--json` | 开关 | 输出机器可读 JSON | 不做摘要排版 |

## 4. 参数规则

### 4.1 `--workspace`

用于指定 workspace 根目录。脚本会自动推导默认 trace 文件路径：

```text
<workspace>/logs/teaching_trace.jsonl
```

如果不传，默认使用当前工作目录。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature
```

### 4.2 `--trace-file`

用于直接指定 trace 文件路径。

一旦提供这个参数，脚本不会再根据 `--workspace` 推导默认路径。

示例：

```powershell
uv run python scripts/teaching_trace.py --trace-file D:/Code/nanobot-local-feature/logs/teaching_trace.jsonl
```

### 4.3 `--last`

只保留最近 `N` 条有效 trace。

这里的“最近”按文件中的出现顺序判断，也就是 JSONL 文件最后几条有效记录。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --last 5
```

### 4.4 `--trace-id`

按 `trace_id` 精确匹配单条 trace。

如果没有命中，脚本会输出：

```text
trace_id not found: <trace_id>
```

并返回非零退出码。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --trace-id abc123def456
```

### 4.5 `--failed`

只保留包含 `failure` 字段的记录，适合快速排查异常或轮数耗尽场景。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --failed
```

### 4.6 `--teacher-branch-only`

只保留 `log_scope=teacher-branch` 的记录。

这个参数适合在 trace 文件中可能混入其他来源记录时，快速聚焦当前教学分支链路。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --teacher-branch-only
```

### 4.7 `--full`

将默认的人类摘要视图展开为详细视图。

展开后会额外展示：

- 每轮 `round_index`
- 每轮 `done`
- 每轮 `mount_requests`
- 每轮 `mount_results`
- 每轮 `teacher_messages`
- 每轮 `llm_attempts`
- 最终 `diagnosis`
- `proposed_state_updates`
- `proposed_plan_updates`

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --failed --full
```

### 4.8 `--json`

直接输出原始记录 JSON，不做摘要格式化，也不重命名字段，适合与其他脚本配合。

示例：

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --trace-id abc123def456 --json
```

## 5. 输出说明

### 5.1 默认摘要输出

默认模式输出一段面向人工排查的摘要，包含：

- `logged_at`
- `log_scope`
- `trace_id`
- `event_type`
- `learning_mode`
- `round_count`
- `response_type`
- `failed`
- `failure_kind` / `failure_message` 或 `response_preview`

如果读取时跳过了坏行，还会附带：

- `invalid_line_count`

### 5.2 详细输出

开启 `--full` 后，默认摘要下面会继续展开每轮内容和最终诊断字段。

### 5.3 JSON 输出

开启 `--json` 后，输出是一个 JSON 数组，每个元素对应一条 trace 记录。

这个模式不会做摘要截断，适合后续再加工。

## 6. 错误处理与退出码

### 6.1 trace 文件不存在

如果目标 trace 文件不存在，脚本会输出：

```text
teaching trace file not found: <path>
```

并返回退出码 `1`。

### 6.2 `trace_id` 未命中

如果使用了 `--trace-id` 且没有命中记录，脚本会输出：

```text
trace_id not found: <trace_id>
```

并返回退出码 `1`。

### 6.3 过滤结果为空

如果筛选条件合法，但没有匹配结果，例如：

- `--failed` 但当前没有失败记录
- `--teacher-branch-only` 但当前没有教学分支记录
- `--last 0`

脚本会输出：

```text
no matching trace records
```

并返回退出码 `0`。

### 6.4 JSONL 中存在坏行

如果 JSONL 文件中某些行不是合法 JSON，脚本会跳过这些坏行，不中断整个读取流程。

在默认摘要模式下，会用 `invalid_line_count` 标明跳过了多少坏行。

## 7. 常用命令示例

### 查看最近 5 条

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --last 5
```

### 只看教学分支记录

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --teacher-branch-only
```

### 查看最近失败回合

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --failed
```

### 查看某条 trace 的完整详情

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --trace-id abc123def456 --full
```

### 把教学分支失败 trace 作为 JSON 输出

```powershell
uv run python scripts/teaching_trace.py --workspace D:/Code/nanobot-local-feature --teacher-branch-only --failed --json
```

### 直接指定 trace 文件路径

```powershell
uv run python scripts/teaching_trace.py --trace-file D:/Code/nanobot-local-feature/logs/teaching_trace.jsonl --last 10
```

## 8. 适用场景

这个工具适合：

- 先按 `log_scope=teacher-branch` 快速确认这是教学分支产出的 trace。
- 查看某一轮教学 F1 到底经历了哪些挂载请求。
- 检查 Teacher Core 每轮收到的 `teacher_messages`。
- 检查 Teacher Core 的 `llm_attempts` 和 repair 过程。
- 统计最近是否频繁出现 `mount_round_limit`。
- 回看某条回复为什么进入 `clarify`。
- 把 trace 输出给其他脚本做进一步分析。

## 9. 当前边界

第一版工具只支持这些筛选能力：

- 最近 N 条
- 精确 trace_id
- 失败记录筛选
- `log_scope` 精确筛选

当前不支持：

- 按 `event_type` 筛选
- 按日期范围筛选
- 按 slot 名筛选
- 聚合统计报表
- 交互式查看器

这些能力如果后续需要，建议继续扩展 `nanobot/teaching/observation/reader.py`，而不是改动教学运行时。
