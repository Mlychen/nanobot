#!/usr/bin/env python3
"""
自动检查今日待办事项脚本（支持动态免打扰）
读取 todo.txt，筛选出今天及未来 2-3 小时内的任务
检查 HISTORY.md 避免重复提醒
支持默认免打扰时间和临时免打扰时间

提醒策略：
- 所有任务提前 30 分钟提醒
- 每天第一次检查时提醒当天所有剩余任务
- 中午 12 点提醒当天所有剩余任务
"""

import os
import re
import json
from datetime import datetime, timedelta

# =============================================================================
# 基础配置
# =============================================================================
WORKSPACE = "/root/.nanobot/workspace"
TODO_FILE = os.path.join(WORKSPACE, "todo.txt")
HISTORY_FILE = os.path.join(WORKSPACE, "memory", "HISTORY.md")
CONFIG_FILE = os.path.join(WORKSPACE, "config", "do_not_disturb.json")
USER_ID = "ou_320526746bf0a46e4a7f7978c0d9d0f6"
CHANNEL = "feishu"

# =============================================================================
# 提醒策略配置（可独立修改）
# =============================================================================
ADVANCE_MINUTES = 30  # 所有任务提前提醒时间（分钟）
NOON_CHECK_HOUR = 12  # 中午提醒时间（小时）
NOON_CHECK_MINUTE = 0  # 中午提醒时间（分钟）
MORNING_CHECK_END_HOUR = 9  # 早晨首次检查的截止时间（9 点前算第一次）


# =============================================================================
# 免打扰配置管理
# =============================================================================
def load_dnd_config():
    """读取免打扰配置文件"""
    default_config = {
        "default": {"start": "22:30", "end": "07:00"},
        "temporary": None
    }
    
    if not os.path.exists(CONFIG_FILE):
        return default_config
    
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
        return config
    except Exception as e:
        print(f"WARNING: 无法读取免打扰配置 - {e}")
        return default_config


def save_dnd_config(config):
    """保存免打扰配置文件"""
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"WARNING: 无法保存免打扰配置 - {e}")
        return False


def cleanup_expired_temporary(config):
    """清理过期的临时免打扰配置"""
    if config.get("temporary") is None:
        return config
    
    today = datetime.now().strftime("%Y-%m-%d")
    temp_date = config["temporary"].get("date", "")
    
    if temp_date < today:
        config["temporary"] = None
        save_dnd_config(config)
    
    return config


# =============================================================================
# 时间工具函数
# =============================================================================
def get_current_datetime():
    """获取当前日期时间"""
    return datetime.now()


def parse_time(time_str):
    """解析时间字符串 HH:MM 为 (hour, minute)"""
    try:
        parts = time_str.split(":")
        return int(parts[0]), int(parts[1])
    except:
        return None, None


def is_time_in_range(current, start, end):
    """判断当前时间是否在 [start, end] 范围内（支持跨天）"""
    curr_h, curr_m = parse_time(current)
    start_h, start_m = parse_time(start)
    end_h, end_m = parse_time(end)
    
    if curr_h is None or start_h is None or end_h is None:
        return False
    
    curr_minutes = curr_h * 60 + curr_m
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    
    if start_minutes > end_minutes:
        return curr_minutes >= start_minutes or curr_minutes < end_minutes
    else:
        return start_minutes <= curr_minutes < end_minutes


def is_in_dnd_period(config, now):
    """判断当前时间是否在免打扰时段内"""
    current_time = now.strftime("%H:%M")
    
    if config.get("temporary") is not None:
        temp = config["temporary"]
        start = temp.get("start", "22:30")
        end = temp.get("end", "07:00")
        
        if is_time_in_range(current_time, start, end):
            return True, "temporary"
    
    default = config.get("default", {"start": "22:30", "end": "07:00"})
    start = default.get("start", "22:30")
    end = default.get("end", "07:00")
    
    if is_time_in_range(current_time, start, end):
        return True, "default"
    
    return False, None


# =============================================================================
# 提醒策略函数（独立模块，方便修改）
# =============================================================================
def get_advance_minutes_for_task(task_dt):
    """
    计算任务的提前提醒时间（分钟）
    当前策略：所有任务统一提前 30 分钟
    后期可在此添加分时段逻辑
    """
    return ADVANCE_MINUTES


def is_morning_first_check(now):
    """
    判断是否是今天的第一次检查（早晨时段）
    策略：9 点前的检查视为早晨首次检查
    """
    return now.hour < MORNING_CHECK_END_HOUR


def is_noon_check(now):
    """
    判断是否是中午 12 点检查
    策略：12:00-12:29 之间的检查视为中午检查
    """
    return now.hour == NOON_CHECK_HOUR and now.minute < 30


def should_remind_all_today_tasks(now):
    """
    判断是否应该提醒今天所有剩余任务
    条件：早晨首次检查 或 中午 12 点检查
    """
    return is_morning_first_check(now) or is_noon_check(now)


def get_reminder_window(now):
    """
    获取当前检查的提醒时间窗口
    返回：(start_datetime, end_datetime, window_type)
    """
    if should_remind_all_today_tasks(now):
        # 早晨/中午检查：提醒今天所有未完成任务
        today_end = now.replace(hour=23, minute=59, second=59)
        return now, today_end, "all_today"
    else:
        # 常规检查：只提醒提前窗口内的任务
        window_start = now
        window_end = now + timedelta(minutes=ADVANCE_MINUTES)
        return window_start, window_end, "advance"


# =============================================================================
# 任务解析函数
# =============================================================================
def parse_task_time(task_content):
    """从任务内容中提取时间 (t:HH:MM)"""
    match = re.search(r't:(\d{2}):(\d{2})', task_content)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return hour, minute
    return None, None


def task_datetime(task_date, task_content):
    """将任务日期和时间转换为 datetime 对象"""
    hour, minute = parse_task_time(task_content)
    if hour is None:
        return None
    
    try:
        return datetime.strptime(f"{task_date} {hour:02d}:{minute:02d}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def get_all_today_tasks():
    """获取今天所有未提醒的任务"""
    now = get_current_datetime()
    today = now.strftime("%Y-%m-%d")
    
    today_tasks = []
    
    if not os.path.exists(TODO_FILE):
        return None, "待办文件不存在"
    
    try:
        with open(TODO_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            match = re.match(r'\([A-Z]\)\s+(\d{4}-\d{2}-\d{2})\s+(.+)', line)
            if match:
                task_date = match.group(1)
                task_content = match.group(2)
                
                if task_date != today:
                    continue
                
                task_dt = task_datetime(task_date, task_content)
                if task_dt is None:
                    continue
                
                # 只处理当前时间之后的任务
                if task_dt < now:
                    continue
                
                task_key = f"{task_date}_{task_content.strip()}"
                if check_already_reminded(task_key):
                    today_tasks.append({
                        'date': task_date,
                        'content': task_content,
                        'datetime': task_dt,
                        'raw': line,
                        'task_key': task_key
                    })
        
        today_tasks.sort(key=lambda x: x['datetime'])
        return today_tasks, None
    
    except Exception as e:
        return None, str(e)


def get_tasks_in_window(start_dt, end_dt, window_type):
    """
    获取指定时间窗口内的任务
    window_type: "all_today" 或 "advance"
    """
    tasks, error = get_all_today_tasks()
    
    if error:
        return None, error
    
    if window_type == "all_today":
        # 返回所有任务
        return tasks, None
    else:
        # 返回窗口内的任务（考虑提前时间）
        window_tasks = []
        for task in tasks:
            # 任务的提醒时间 = 任务时间 - 提前时间
            reminder_time = task['datetime'] - timedelta(minutes=ADVANCE_MINUTES)
            
            # 如果提醒时间在当前窗口内，则需要提醒
            if start_dt <= reminder_time <= end_dt:
                # 同时检查是否已提醒过
                if check_already_reminded(task['task_key']):
                    window_tasks.append(task)
        
        return window_tasks, None


# =============================================================================
# 历史记录管理
# =============================================================================
def check_already_reminded(task_key):
    """检查特定任务是否已发送过提醒"""
    if not os.path.exists(HISTORY_FILE):
        return True
    
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if f"待办提醒：{task_key}" in content:
            return False
        
        return True
    except Exception:
        return True


def record_reminder(task_key):
    """在 HISTORY.md 中记录已发送提醒"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    record = f"[{now}] 待办提醒：{task_key}\n"
    
    try:
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            f.write(record)
        return True
    except Exception as e:
        print(f"WARNING: 无法记录提醒历史 - {e}")
        return False


# =============================================================================
# 免打扰动态更新
# =============================================================================
def update_temporary_dnd(config, task_datetime):
    """更新临时免打扰时间为任务开始前"""
    today = datetime.now().strftime("%Y-%m-%d")
    task_time_str = task_datetime.strftime("%H:%M")
    current_time = datetime.now().strftime("%H:%M")
    
    config["temporary"] = {
        "date": today,
        "start": current_time,
        "end": task_time_str,
        "reason": f"检测到任务 {task_time_str}"
    }
    
    save_dnd_config(config)
    return config


# =============================================================================
# 输出格式化
# =============================================================================
def format_tasks(tasks, now, window_type):
    """格式化任务列表为可读文本"""
    if not tasks:
        return None
    
    output = []
    
    if window_type == "all_today":
        output.append(f"📅 **今日待办**（{len(tasks)} 项）")
    else:
        output.append(f"📅 **近期待办**")
    
    output.append("")
    
    for i, task in enumerate(tasks, 1):
        delta = task['datetime'] - now
        minutes = int(delta.total_seconds() / 60)
        
        if minutes < 60:
            time_desc = f"{minutes} 分钟后"
        else:
            hours = minutes // 60
            mins = minutes % 60
            time_desc = f"{hours} 小时 {mins} 分钟后" if mins > 0 else f"{hours} 小时后"
        
        time_match = re.search(r't:(\d{2}:\d{2})', task['content'])
        task_time = time_match.group(1) if time_match else '全天'
        
        content = re.sub(r'\s+t:\d{2}:\d{2}', '', task['content'])
        content = re.sub(r'\s+@\w+', '', content)
        content = re.sub(r'^\d{2}:\d{2}\s+', '', content)
        content = content.strip()
        
        output.append(f"{i}. ⏰ {task_time} | {content} ({time_desc})")
    
    return "\n".join(output)


# =============================================================================
# 主程序
# =============================================================================
if __name__ == "__main__":
    now = get_current_datetime()
    
    # 1. 加载并清理免打扰配置
    config = load_dnd_config()
    config = cleanup_expired_temporary(config)
    
    # 2. 获取提醒窗口
    window_start, window_end, window_type = get_reminder_window(now)
    
    # 3. 获取窗口内的任务
    tasks, error = get_tasks_in_window(window_start, window_end, window_type)
    
    if error:
        print(f"ERROR: {error}")
        exit(1)
    
    # 4. 判断是否在免打扰时段
    in_dnd, dnd_type = is_in_dnd_period(config, now)
    
    if in_dnd:
        if not tasks:
            print(f"NO_TASKS: 免打扰时段 ({dnd_type})，无待办事项")
            exit(0)
        else:
            # 免打扰时段 + 有任务 = 发送提醒并更新临时免打扰
            earliest_task = tasks[0]['datetime']
            config = update_temporary_dnd(config, earliest_task)
            
            formatted = format_tasks(tasks, now, window_type)
            print(formatted)
            print(f"\n---DATA---")
            print(f"USER_ID:{USER_ID}")
            print(f"CHANNEL:{CHANNEL}")
            print(f"DND_UPDATED: 临时免打扰更新到 {earliest_task.strftime('%H:%M')}")
            print(f"WINDOW_TYPE: {window_type}")
            
            for task in tasks:
                record_reminder(task['task_key'])
            exit(0)
    
    # 5. 不在免打扰时段 = 正常发送提醒
    if not tasks:
        if window_type == "all_today":
            print(f"NO_TASKS: 今天没有待办事项")
        else:
            print(f"NO_TASKS: 未来 {ADVANCE_MINUTES} 分钟内没有待办事项")
        exit(0)
    
    formatted = format_tasks(tasks, now, window_type)
    print(formatted)
    print(f"\n---DATA---")
    print(f"USER_ID:{USER_ID}")
    print(f"CHANNEL:{CHANNEL}")
    print(f"WINDOW_TYPE: {window_type}")
    
    for task in tasks:
        record_reminder(task['task_key'])
