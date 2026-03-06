# WP06：Scheduler Agent

## 一、工作目标

实现第一个真正可运行的 domain agent：`scheduler_agent`。

它负责学习节奏，不负责知识讲解。

第一阶段要实现：

1. 日计划生成
2. 定时提醒
3. 基础复盘提醒
4. 恢复协议建议

---

## 二、边界与非目标

本包负责：

1. 学习计划与提醒
2. 与 cron/heartbeat 的协作
3. 基础恢复建议

本包不负责：

1. RAG 或知识库检索
2. 公考专项讲解
3. 复杂学习画像

---

## 三、前置条件

1. `WP04` 完成
2. `WP05` 完成

建议联调：

1. `WP03`

---

## 四、现有架构接点

可复用：

1. `CronService`
2. `HeartbeatService`
3. `AgentLoop.process_direct()` 作为底层执行能力

---

## 五、新增内容

### 1. scheduler_agent

必须支持：

1. `sync`
   - 生成日计划
2. `async`
   - 触发定时提醒
3. `event`
   - 响应 heartbeat/cron 事件

### 2. 领域记忆

第一阶段至少记录：

1. 当前计划
2. 待提醒任务
3. 最近复盘节点

---

## 六、实现流程

### Step 1：定义职责与输入输出

要求：

1. 接受学习目标、时间块、优先级等输入
2. 产出结构化计划或提醒结果

### Step 2：实现 sync 路径

目标：

1. 主 agent 可当前回合内请求“生成今天计划”

### Step 3：实现 event 路径

目标：

1. heartbeat 可触发日内检查
2. cron 可触发定时提醒

### Step 4：实现 async 回推

目标：

1. 计划提醒和复盘提醒可以在用户不主动发消息时推送

---

## 七、关键细节与失败模式

### 1. 避免重复提醒

要求：

1. 同一提醒任务不应多次重复发送

### 2. 没有通知目标时不能硬发

要求：

1. 必须回退到可解释状态

### 3. 计划与知识讲解分层

要求：

1. scheduler 只管“学什么、何时学、何时提醒”
2. 不负责回答知识内容

---

## 八、测试流程

### 1. 单元测试

覆盖：

1. 计划生成
2. 提醒状态机
3. 恢复协议生成

### 2. 集成测试

覆盖：

1. 主 agent -> scheduler_agent -> 主 agent 回复
2. cron -> scheduler_agent -> 通知路由
3. heartbeat -> scheduler_agent -> 复盘提醒

### 3. 回归测试

确认：

1. cron 和 heartbeat 原有主流程不被破坏

---

## 九、验收标准

1. 能为用户生成当日学习计划
2. 能按时间触发学习提醒
3. 能推送简单复盘提醒
4. 异步提醒能稳定送达主渠道

---

## 十、上游兼容注意事项

1. 尽量作为新增 domain agent 落地
2. 不改 cron/heartbeat 基础服务职责
3. 提醒状态逻辑尽量自包含，不扩散到主循环

---

## 十一、当前实现落点（2026-03-06）

已落地：

1. `nanobot/agent/domain/scheduler_agent.py`
   - 新增真实 `scheduler` domain agent
   - 支持 `sync/async/event` 三类调用
2. `nanobot/agent/domain/scheduler_store.py`
   - 状态文件固定落到 `workspace/domain_agents/scheduler/state.json`
   - 以 person-scope context key 持久化 `current_plan/pending_reminders/review_nodes/last_recovery_protocol/last_generated_at`
3. `nanobot/cli/commands.py`
   - `_make_primary_orchestrator(workspace)` 已支持注册 workspace-backed `scheduler`
   - heartbeat 路径会优先把 `person:*:direct` 会话解析回主渠道绑定，再把 `person_id/session_key/surface_id` 传给 `scheduler event`
4. `tests/test_scheduler_agent.py`
   - 覆盖 store 空文件/坏文件、sync 落盘、async 提醒、event 去重与恢复协议推断
5. `tests/test_scheduler_integration.py`
   - 覆盖 orchestrator sync、async 通知路由、heartbeat event 单次提醒闭环

本版范围：

1. `sync`
   - 生成当日学习计划
   - 写入学习提醒与复盘提醒节点
2. `async`
   - 生成一次性主动提醒文案，复用既有通知路由回推
3. `event`
   - 由 heartbeat 扫描到期提醒并单次发送
   - 无到期任务时返回静默 `SKIPPED`
4. 恢复协议
   - 支持显式 `fatigue_level=low/medium/high`
   - 未显式指定时，可按多条逾期任务推断保守恢复建议

本版未做：

1. 不在 `WP06` 内创建 cron job
2. 不扩写 cron/heartbeat 基础服务职责
3. 不引入知识讲解、RAG 或专项教学逻辑

已验证：

1. `uv run pytest -q tests/test_scheduler_agent.py tests/test_scheduler_integration.py tests/test_gate_b_integration.py tests/test_domain_protocols.py tests/test_primary_orchestrator.py tests/test_notification_router.py`
2. `uv run python -m ruff check nanobot/agent/domain/scheduler_agent.py nanobot/agent/domain/scheduler_store.py nanobot/cli/commands.py tests/test_scheduler_agent.py tests/test_scheduler_integration.py tests/test_gate_b_integration.py`

当前状态判断：

1. `WP06` 代码、测试、文档已补齐，可记为 `代码完成`
2. 后续进入 Gate C 时，需要与 `WP07` 一起验证完整第一阶段闭环
