# -*- coding: utf-8 -*-
# Copyright (c) 2026 ZXJ@DEVS. Author: QQ 1817694478 | Q-Group: 972156177
# Skill: flow-immersion | Version: 3.2.2
"""
Flow Immersion Mode - ADHD陪伴核心模块
基于 adhd-body-doubling 改造（去除了DataStorage循环依赖）
"""
import json
import sys
import time
import threading
from datetime import datetime
from pathlib import Path

# 编码兼容
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

SKILL_DIR = Path(__file__).parent.parent
CONFIG_FILE = SKILL_DIR / "config.json"
DEFAULT_CONFIG = SKILL_DIR / "assets" / "default_config.json"

# 多巴胺菜单选项
DOPAMINE_MENU = [
    {"id": "physical",   "name": "身体活动",   "description": "伸展、跳跃、走动",     "duration": "2-5分钟"},
    {"id": "sensory",   "name": "感官切换",   "description": "换个环境、换音乐",     "duration": "1-2分钟"},
    {"id": "micro_win", "name": "小胜利",     "description": "完成一个小任务",       "duration": "2-5分钟"},
    {"id": "external",  "name": "外部输入",   "description": "1分钟励志内容",        "duration": "1分钟"},
    {"id": "brain_dump","name": "大脑清空",   "description": "写下脑中所有想法",      "duration": "2分钟"},
    {"id": "hydrate",   "name": "补水",       "description": "喝水、洗把脸",         "duration": "1-2分钟"},
    {"id": "permission","name": "允许休息",   "description": "5分钟什么都不做",       "duration": "5分钟"},
]

# 紧急重置协议
EMERGENCY_RESET_PROTOCOL = [
    "停止 (30秒) - 手离开键盘",
    "呼吸 (30秒) - 3次深呼吸",
    "提问 (1分钟) - '我正在逃避什么？'",
    "缩小 (1分钟) - 把任务缩小10倍",
    "承诺 (30秒) - '我只做5分钟'",
    "开始 - 从最小的任务开始",
]


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    try:
        with open(DEFAULT_CONFIG, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {"pomodoro": {}, "adhd": {}, "immersion": {}, "tracking": {}}


class ADHDCompanion:
    """ADHD陪伴核心 - 无DataStorage依赖"""

    def __init__(self):
        self.config = load_config()
        adhd_cfg = self.config.get('adhd', {})
        self.enabled = adhd_cfg.get('companion_enabled', True)
        self.checkin_interval = adhd_cfg.get('check_in_interval', 15)
        self.companion_type = adhd_cfg.get('companion_type', 'ambient')

        self.current_task = None
        self.micro_steps = []
        self.current_step_index = 0
        self.checkin_thread = None
        self.is_monitoring = False
        self.callbacks = []
        self.last_checkin_time = None
        self.dopamine_breaks_today = 0

    def add_callback(self, callback):
        self.callbacks.append(callback)

    def _notify(self, event, data=None):
        for cb in self.callbacks:
            try:
                cb(event, data)
            except Exception:
                pass

    def start_session(self, task_description):
        if not self.enabled:
            return {"success": False, "message": "ADHD陪伴功能已关闭"}

        self.current_task = task_description
        self.micro_steps = []
        self.current_step_index = 0
        self.last_checkin_time = datetime.now()
        self.dopamine_breaks_today = 0
        self._start_monitoring()

        self._notify('session_start', {'task': task_description})
        return {"success": True, "message": "ADHD陪伴已启动"}

    def _start_monitoring(self):
        self.is_monitoring = True
        self.checkin_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.checkin_thread.start()

    def _monitor_loop(self):
        while self.is_monitoring:
            time.sleep(10)
            if not self.enabled:
                continue
            if self.last_checkin_time:
                elapsed = (datetime.now() - self.last_checkin_time).seconds
                if elapsed >= self.checkin_interval * 60:
                    self.trigger_checkin()

    def trigger_checkin(self):
        self.last_checkin_time = datetime.now()
        self._notify('checkin', {
            'task': self.current_task,
            'current_step': self._get_current_step(),
            'elapsed_minutes': (datetime.now() - self.last_checkin_time).seconds // 60
        })

    def _get_current_step(self):
        if 0 <= self.current_step_index < len(self.micro_steps):
            return self.micro_steps[self.current_step_index]
        return None

    def _get_next_checkin_minutes(self):
        if not self.last_checkin_time:
            return self.checkin_interval
        elapsed = (datetime.now() - self.last_checkin_time).seconds // 60
        return max(0, self.checkin_interval - elapsed)

    def add_micro_step(self, step):
        if len(self.micro_steps) < 10:
            self.micro_steps.append({
                "text": step,
                "completed": False,
                "added_at": datetime.now().isoformat()
            })
            self._notify('micro_step_added', {'step': step, 'total_steps': len(self.micro_steps)})
            return True
        return False

    def complete_micro_step(self, index=None):
        if index is None:
            index = self.current_step_index
        if 0 <= index < len(self.micro_steps):
            self.micro_steps[index]['completed'] = True
            self.micro_steps[index]['completed_at'] = datetime.now().isoformat()
            self.current_step_index = index + 1
            self._notify('micro_step_completed', {
                'step_index': index,
                'step': self.micro_steps[index]['text']
            })
            return True
        return False

    def remove_micro_step(self, index):
        if 0 <= index < len(self.micro_steps):
            self.micro_steps.pop(index)
            if self.current_step_index > index:
                self.current_step_index -= 1
            return True
        return False

    def get_dopamine_menu(self):
        return DOPAMINE_MENU

    def apply_dopamine_reset(self, option_id):
        option = next((o for o in DOPAMINE_MENU if o['id'] == option_id), None)
        if option:
            self.dopamine_breaks_today += 1
            self._notify('dopamine_reset', {'option': option, 'task': self.current_task})
            return {"success": True, "option": option}
        return {"success": False, "message": "未知选项"}

    def get_emergency_reset_protocol(self):
        return EMERGENCY_RESET_PROTOCOL

    def apply_emergency_reset(self):
        self.last_checkin_time = datetime.now()
        self._notify('emergency_reset', {'protocol': EMERGENCY_RESET_PROTOCOL, 'task': self.current_task})
        return {"success": True, "protocol": EMERGENCY_RESET_PROTOCOL}

    def end_session(self):
        self.is_monitoring = False
        self.current_task = None
        self.micro_steps = []
        self.current_step_index = 0
        self._notify('session_end', {})

    def get_status(self):
        return {
            "enabled": self.enabled,
            "companion_type": self.companion_type,
            "checkin_interval": self.checkin_interval,
            "current_task": self.current_task,
            "micro_steps_count": len(self.micro_steps),
            "completed_steps": sum(1 for s in self.micro_steps if s.get('completed')),
            "dopamine_breaks_today": self.dopamine_breaks_today,
            "next_checkin_minutes": self._get_next_checkin_minutes(),
        }

    def get_tips(self):
        """获取上下文ADHD建议"""
        tips = [
            {"type": "micro_step",  "text": "把任务分解成2分钟以内的小步骤"},
            {"type": "dopamine",     "text": "完成一小步后给自己一个小奖励"},
            {"type": "body_double",  "text": "找一个安静的地方，减少干扰源"},
            {"type": "timer",        "text": "使用番茄钟，25分钟专注工作"},
            {"type": "break",        "text": "休息时站起来活动5分钟"},
            {"type": "sensory",      "text": "换个环境或切换背景音"},
            {"type": "brain_dump",   "text": "写下脑中所有想法，清空工作记忆"},
        ]
        if self.current_task and self.micro_steps:
            remaining = len(self.micro_steps) - sum(1 for s in self.micro_steps if s.get('completed'))
            if remaining > 0:
                tips.insert(0, {"type": "progress", "text": f"还有{remaining}个小步骤，继续加油！"})
        return tips

    def start_autopsy(self):
        return {
            "questions": [
                "今天什么帮助你专注了？",
                "今天什么破坏了你的专注？",
                "下次有什么改进？",
                "你实际完成了什么？"
            ]
        }
