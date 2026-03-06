# 自动待办提醒脚本

## 文件说明

- `check_today_tasks.py` - 主脚本，检查今日待办事项
- `README.md` - 本说明文档

## 功能

1. **自动获取日期**：根据系统时间自动判断今天日期
2. **筛选今日任务**：从 todo.txt 中筛选出今天的任务
3. **避免重复提醒**：检查 HISTORY.md，今天已提醒过则跳过
4. **格式化输出**：输出易读的任务列表
5. **记录提醒历史**：发送提醒后自动记录到 HISTORY.md

## 使用方法

### 手动执行
```bash
python3 /root/.nanobot/workspace/scripts/check_today_tasks.py
```

### 输出说明

| 输出类型 | 说明 |
|---------|------|
| `NO_TASKS` | 今天没有待办事项 |
| `SKIP: ALREADY_REMINDED` | 今天已发送过提醒，跳过 |
| `ERROR: xxx` | 发生错误 |
| 任务列表 + `---DATA---` | 有今日任务，需要发送提醒 |

### HEARTBEAT 集成

脚本已配置到 `HEARTBEAT.md`，nanobot 会每 30 分钟自动检查：

1. 执行脚本
2. 解析输出
3. 如果有任务且未提醒过，使用 `message` 工具发送飞书提醒
4. 脚本自动记录提醒到 HISTORY.md

## 输出格式示例

```
📅 **今日待办 (2 项)**

1. ⏰ 08:30 - 碰头会
2. ⏰ 17:00 - 写日报

---DATA---
USER_ID:ou_320526746bf0a46e4a7f7978c0d9d0f6
CHANNEL:feishu
TASK_COUNT:2
```

## 配置

- **工作目录**: `/root/.nanobot/workspace`
- **待办文件**: `todo.txt`
- **历史记录**: `memory/HISTORY.md`
- **检查频率**: 每 30 分钟（HEARTBEAT）
- **用户 ID**: `ou_320526746bf0a46e4a7f7978c0d9d0f6`
- **渠道**: 飞书 (feishu)
