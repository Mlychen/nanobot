#!/usr/bin/env python3
"""
每日待办自动提醒包装脚本
运行 check_today_tasks.py 检查任务，如有任务则通过 message 工具发送飞书提醒
"""

import subprocess
import sys
import os

SCRIPT_PATH = "/root/.nanobot/workspace/scripts/check_today_tasks.py"

def main():
    # 运行检查脚本
    result = subprocess.run(
        [sys.executable, SCRIPT_PATH],
        capture_output=True,
        text=True,
        encoding='utf-8'
    )
    
    output = result.stdout
    exit_code = result.returncode
    
    # 检查是否需要发送消息
    if "SKIP:" in output or "NO_TASKS:" in output or "ERROR:" in output:
        print(output.strip())
        return
    
    # 解析输出
    if "---DATA---" in output:
        parts = output.split("---DATA---")
        message_content = parts[0].strip()
        data_part = parts[1].strip()
        
        # 解析用户信息
        user_id = None
        channel = None
        task_count = 0
        
        for line in data_part.split('\n'):
            if line.startswith("USER_ID:"):
                user_id = line.split(":")[1]
            elif line.startswith("CHANNEL:"):
                channel = line.split(":")[1]
            elif line.startswith("TASK_COUNT:"):
                task_count = int(line.split(":")[1])
        
        if user_id and channel and message_content:
            # 输出特殊标记，供外部调用 message 工具
            print(f"[MESSAGE_REQUEST]")
            print(f"channel: {channel}")
            print(f"chat_id: {user_id}")
            print(f"content: {message_content}")
            print(f"[MESSAGE_REQUEST_END]")
            print(f"\n[INFO] 已准备发送 {task_count} 项任务的提醒")
        else:
            print(f"ERROR: 无法解析用户信息")
            print(output)
    else:
        print(output)

if __name__ == "__main__":
    main()
