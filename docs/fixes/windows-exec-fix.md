# Windows Exec 工具修复记录

## 问题概述

**问题**: Windows 上 `exec` 工具无法执行任何外部命令（如 `python`, `git`, `node` 等），提示 `command not found` 或 `WinError 2`。

**影响时间**: 2026-04-05 至 2026-04-07

**根本原因**: PR #2831 引入的安全修复导致 Windows 平台 exec 工具失效。

---

## 时间线

| 日期 | 事件 | Commit/PR |
|------|------|-----------|
| 2026-02-22 | 最早的 Windows exec 问题报告（Issue #989） | - |
| 2026-04-05 | 安全修复 PR #2831 提交 | `be6063a` |
| 2026-04-05 22:21 | 安全修复合并到 main | `be6063a` |
| 2026-04-06 16:43 | 用户报告 Windows exec 被破坏（Issue #2868） | - |
| 2026-04-07 08:24 | Windows 修复 PR #2893 提交 | `99f49f5` |
| 2026-04-07 09:56 | CI 测试通过，等待 review | - |
| 2026-04-07 | 本地 cherry-pick 应用修复 | `a6966c4` |

---

## 问题根因分析

### PR #2831 安全修复背景

**目的**: 防止 LLM 通过 `printenv` 等命令窃取 API keys 等敏感环境变量。

**修复方式**:
```python
# 修复前（不安全）
env = os.environ.copy()  # ❌ 泄露所有环境变量
subprocess_shell(command)  # ❌ 继承完整环境

# 修复后（安全但不兼容 Windows）
env = {"HOME": ..., "LANG": ..., "TERM": ...}  # ✅ 不泄露 secrets
bash -l -c command  # ❌ Windows 上无法工作
```

**副作用**: 
- Unix: `bash -l` 会读取 `~/.profile` 重建 PATH，工作正常
- Windows: Git Bash 的 `-l` 不会正确设置 PATH，导致外部命令找不到

### 为什么 Windows 失效

1. Windows 没有真正的 login shell 机制
2. `bash -l` 在 Windows 上不会从系统 profile 读取 PATH
3. 传递给 subprocess 的 env 只有 `{HOME, LANG, TERM}`，没有 PATH
4. bash 内部执行外部命令时，无法在 PATH 中找到

---

## PR #2893 修复方案

### 核心改动

**平台感知的 shell 选择** (`_spawn` 方法):
```python
if _IS_WINDOWS:
    # Windows 使用 cmd.exe
    comspec = env.get("COMSPEC", os.environ.get("COMSPEC", "cmd.exe"))
    return await asyncio.create_subprocess_exec(
        comspec, "/c", command, ...
    )
else:
    # Unix 使用 bash login shell
    bash = shutil.which("bash") or "/bin/bash"
    return await asyncio.create_subprocess_exec(
        bash, "-l", "-c", command, ...
    )
```

**平台感知的环境变量** (`_build_env` 方法):
```python
if _IS_WINDOWS:
    sr = os.environ.get("SYSTEMROOT", r"C:\Windows")
    return {
        "SYSTEMROOT": sr,
        "COMSPEC": os.environ.get("COMSPEC", f"{sr}\\system32\\cmd.exe"),
        "USERPROFILE": os.environ.get("USERPROFILE", ""),
        "HOMEDRIVE": os.environ.get("HOMEDRIVE", "C:"),
        "HOMEPATH": os.environ.get("HOMEPATH", "\\"),
        "TEMP": os.environ.get("TEMP", f"{sr}\\Temp"),
        "TMP": os.environ.get("TMP", f"{sr}\\Temp"),
        "PATHEXT": os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD"),
        "PATH": os.environ.get("PATH", f"{sr}\\system32;{sr}"),
    }
else:
    return {
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "TERM": os.environ.get("TERM", "dumb"),
    }
```

### 安全性验证

修复后传递的 Windows 环境变量（9 个）**均不包含敏感信息**：

| 变量 | 用途 | 敏感度 |
|------|------|--------|
| `SYSTEMROOT` | Windows 安装目录 | 公开 |
| `COMSPEC` | cmd.exe 路径 | 公开 |
| `USERPROFILE` | 用户目录 | 半公开（仅路径） |
| `HOMEDRIVE` | 家驱动器 | 公开 |
| `HOMEPATH` | 家目录路径 | 半公开 |
| `TEMP`/`TMP` | 临时目录 | 公开 |
| `PATHEXT` | 可执行扩展名 | 公开 |
| `PATH` | 可执行文件搜索路径 | 公开 |

**明确排除的敏感变量**:
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `NANOBOT_TOKEN`
- 所有其他 API keys、tokens、密码

**测试验证**:
```python
def test_secrets_excluded(self, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret")
    monkeypatch.setenv("NANOBOT_TOKEN", "tok-secret")
    env = ExecTool()._build_env()
    assert "OPENAI_API_KEY" not in env  # ✅ 验证不存在
    assert "NANOBOT_TOKEN" not in env   # ✅ 验证不存在
```

---

## 本地应用修复

### 操作步骤

```bash
# 1. 获取上游最新代码
git fetch upstream

# 2. Cherry-pick 修复 commit
git cherry-pick 99f49f5

# 3. 验证修复
git log -1 --stat
# 应显示：3 files changed, 335 insertions(+), 20 deletions(-)

# 4. 测试 exec 工具
.venv/Scripts/python.exe -c "
import asyncio
from nanobot.agent.tools.shell import ExecTool
async def test():
    tool = ExecTool(working_dir='.')
    print(await tool.execute('python --version'))
asyncio.run(test())
"
```

### 验证结果

```
--- python --version ---
Python 3.14.3
Exit code: 0

--- git --version ---
git version 2.53.0.windows.1
Exit code: 0

--- node --version ---
v24.13.1
Exit code: 0
```

✅ 修复成功！

---

## 日后同步策略

### 背景

由于使用了 cherry-pick，本地 `main` 分支比 `upstream/main` 多一个 commit `a6966c4`（内容等同于上游的 `99f49f5`）。

### 同步方案

**推荐：使用 `git merge`**
```bash
git fetch upstream
git merge upstream/main
```

**原因**:
- Git 会检测到变更内容相同，自动跳过重复 commit
- 不会产生冲突
- 历史清晰

**不推荐：`git rebase`**
```bash
# 可能导致 commit 重复或需要手动跳过
git rebase upstream/main
# 如有冲突：git rebase --skip
```

### 验证同步状态

```bash
# 检查是否有本地独有的 commit
git log --oneline --cherry-mark upstream/main..HEAD

# 如果输出为空，说明已完全同步
# 如果显示 +xxx，说明有本地 cherry-pick（正常）
```

---

## 相关文件

| 文件 | 变更 |
|------|------|
| `nanobot/agent/tools/shell.py` | +79 行，-20 行 |
| `tests/tools/test_exec_env.py` | +7 行 |
| `tests/tools/test_exec_platform.py` | +269 行（新增） |

---

## 参考链接

- [PR #2831 - 安全修复](https://github.com/HKUDS/nanobot/pull/2831)
- [PR #2893 - Windows 修复](https://github.com/HKUDS/nanobot/pull/2893)
- [Issue #2868 - 问题报告](https://github.com/HKUDS/nanobot/issues/2868)
- [Issue #989 - 早期 Windows 问题](https://github.com/HKUDS/nanobot/issues/989)

---

## 备注

- 此修复已在上游 nightly 分支验证（commit `ae27d69`）
- CI 测试：1220 个测试全部通过，0 回归
- 修复同时兼顾安全性和功能性
