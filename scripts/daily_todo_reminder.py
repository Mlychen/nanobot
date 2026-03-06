#!/usr/bin/env python3
"""
每日待办自动提醒脚本
检查今日任务，如有任务则发送飞书提醒，并在 HISTORY.md 记录避免重复发送
"""

import os
from datetime import datetime
import re

WORKSPACE = "/root/.nanobot/workspace"
TODO_FILE = os.path.join(WORKSPACE, "todo.txt")
HISTORY_FILE = os.path.join(WORKSPACE, "memory", "HISTORY.md")

# 用户信息（从 MEMORY.md 获取）
FEISHU_CHANNEL = "feishu"
FEISHU_CHAT_ID = "ou_320526746bf0a46e4a7f7978c0d9d0f6"

def get_today_tasks():
    """获取今日任务"""
    today = datetime.now().strftime("%Y-%m-%d")
    tasks = []
    
    if not os.path.exists(TODO_FILE):
        return tasks
    
    with open(TODO_FILE, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 检查是否包含今日日期
            if today in line:
                # 提取任务描述（去掉优先级和日期）
                match = re.search(r'\)\s*(\d{4}-\d{2}-\d{2})\s+(.+)', line)
                if match:
                    task_desc = match.group(2)
                    # 提取时间
                    time_match = re.search(r't:(\d{2}:\d{2})', task_desc)
                    time_str = time_match.group(1) if time_match else ""
                    tasks.append({
                        'raw': line,
                        'desc': task_desc.replace(f' t:{time_str}', '').strip() if time_str else task_desc.strip(),
                        'time': time_str
                    })
    
    return tasks

def check_already_notified(today):
    """检查今日是否已发送过提醒"""
    if not os.path.exists(HISTORY_FILE):
        return False
    
    today_marker = f"[{today} 待办提醒已发送]"
    with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
        content = f.read()
        return today_marker in content

def mark_notified(today):
    """在 HISTORY.md 标记今日已发送提醒"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    marker = f"[{today} 待办提醒已发送]"
    entry = f"[{timestamp}] {marker}\n"
    
    with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
        f.write(entry)

def send_feishu_notification(tasks):
    """发送飞书通知"""
    # 构建消息内容
    today = datetime.now().strftime("%Y-%m-%d")
    weekday_map = {
        0: "周一", 1: "周二", 2: "周三", 3: "周四", 
        4: "周五", 5: "周六", 6: "周日"
    }
    weekday = weekday_map[datetime.now().weekday()]
    
    message = f"📅 今日待办提醒 ({today} {weekday})\n\n"
    
    for i, task in enumerate(tasks, 1):
        time_prefix = f"⏰ {task['time']} " if task['time'] else ""
        message += f"{i}. {time_prefix}{task['desc']}\n"
    
    message += f"\n共 {len(tasks)} 项任务"
    
    # 使用 nanobot message 工具发送（通过 exec 调用）
    # 由于这是在脚本中，我们需要调用 nanobot 的 message 功能
    # 这里我们输出消息内容，由调用者处理
    print(message)
    return message

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 检查是否已发送过今日提醒
    if check_already_notified(today):
        print(f"[{today}] 今日已发送过提醒，跳过")
        return
    
    # 获取今日任务
    tasks = get_today_tasks()
    
    if not tasks:
        print(f"[{today}] 无今日任务")
        return
    
    # 发送通知
    message = send_feishu_notification(tasks)
    
    # 标记已发送
    mark_notified(today)
    
    print(f"\n[INFO] 已记录今日提醒，避免重复发送")
    
    # 输出特殊标记以便调用者识别需要发送消息
    print(f"\n[SEND_MESSAGE_START]")
    print(f"CHANNEL: {FEISHU_CHANNEL}")
    print(f"CHAT_ID: {FEISHU_CHAT_ID}")
    print(f"CONTENT: {message}")
    print(f"[SEND_MESSAGE_END]")

if __name__ == "__main__":
    main()
