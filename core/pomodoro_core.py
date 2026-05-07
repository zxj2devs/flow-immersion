#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 ZXJ@DEVS. Author: QQ 1817694478 | Q-Group: 972156177
# Skill: flow-immersion | Version: 3.2.2
"""
Flow Immersion Mode - 番茄钟核心模块
基于 cn-pomodoro-timer 改造，配置驱动
"""

import json
import os
import sys
import time
import threading
from datetime import datetime, timedelta
from pathlib import Path

# 编码兼容处理
if not getattr(sys, '_pomodoro_core_utf8_set', False):
    try:
        if sys.stdout and sys.stdout.encoding != 'utf-8':
            sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
        if sys.stderr and sys.stderr.encoding != 'utf-8':
            sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)
    except Exception:
        pass
    sys._pomodoro_core_utf8_set = True

# Skill根目录
SKILL_DIR = Path(__file__).parent.parent
CONFIG_FILE = SKILL_DIR / "config.json"
DEFAULT_CONFIG = SKILL_DIR / "assets" / "default_config.json"


def load_config():
    """加载配置"""
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    
    with open(DEFAULT_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)


class PomodoroCore:
    """番茄钟核心"""
    
    def __init__(self):
        self.config = load_config()
        self.work_minutes = self.config['timer']['work_minutes']
        self.break_minutes = self.config['timer']['break_minutes']
        self.long_break_minutes = self.config['timer']['long_break_minutes']
        self.rounds = self.config['timer']['rounds']
        
        self.current_session = None
        self.timer_thread = None
        self.is_running = False
        self.is_paused = False
        self.remaining_seconds = 0
        self.callbacks = []
    
    def add_callback(self, callback):
        """添加状态变化回调"""
        self.callbacks.append(callback)
    
    def _notify_callbacks(self, event, data=None):
        """通知所有回调"""
        for callback in self.callbacks:
            try:
                callback(event, data)
            except Exception:
                pass
    
    def start(self, task=None):
        """开始番茄钟"""
        if self.is_running:
            return False, "已有番茄钟在进行中"
        
        from core.data_storage import DataStorage
        storage = DataStorage()
        
        # 创建会话
        session = storage.create_session(
            task=task,
            planned_minutes=self.work_minutes
        )
        
        self.current_session = {
            'session_id': session['session_id'],
            'start_time': datetime.now(),
            'type': 'work',
            'planned_minutes': self.work_minutes,
            'paused_duration': 0,
            'pause_start': None
        }
        
        self.is_running = True
        self.is_paused = False
        self.remaining_seconds = self.work_minutes * 60
        
        # 启动计时线程
        self.timer_thread = threading.Thread(target=self._timer_loop, daemon=True)
        self.timer_thread.start()
        
        self._notify_callbacks('start', self.current_session)
        
        return True, f"番茄钟已开始，专注{self.work_minutes}分钟"
    
    def pause(self):
        """暂停番茄钟"""
        if not self.is_running:
            return False, "当前没有进行中的番茄钟"
        
        if self.is_paused:
            return False, "番茄钟已处于暂停状态"
        
        self.is_paused = True
        self.current_session['pause_start'] = datetime.now()
        
        self._notify_callbacks('pause', self.current_session)
        
        return True, "番茄钟已暂停"
    
    def resume(self):
        """继续番茄钟"""
        if not self.is_running:
            return False, "当前没有进行中的番茄钟"
        
        if not self.is_paused:
            return False, "番茄钟未在暂停状态"
        
        # 计算暂停时长
        pause_start = self.current_session['pause_start']
        pause_duration = (datetime.now() - pause_start).seconds
        self.current_session['paused_duration'] += pause_duration
        self.current_session['pause_start'] = None
        
        self.is_paused = False
        
        self._notify_callbacks('resume', self.current_session)
        
        return True, "番茄钟已继续"
    
    def stop(self, completed=False):
        """停止番茄钟"""
        if not self.is_running:
            return False, "当前没有进行中的番茄钟"
        
        # 计算实际时长
        start_time = self.current_session['start_time']
        total_seconds = (datetime.now() - start_time).seconds
        paused = self.current_session['paused_duration']
        
        if self.is_paused and self.current_session.get('pause_start'):
            paused += (datetime.now() - self.current_session['pause_start']).seconds
        
        actual_minutes = (total_seconds - paused) // 60
        
        # 结束会话
        from core.data_storage import DataStorage
        storage = DataStorage()
        storage.end_session(
            self.current_session['session_id'],
            completed=completed,
            actual_minutes=actual_minutes
        )
        
        self.is_running = False
        self.is_paused = False
        self.current_session = None
        
        self._notify_callbacks('stop', {'completed': completed, 'minutes': actual_minutes})
        
        return True, f"番茄钟已结束，专注了{actual_minutes}分钟"
    
    def _timer_loop(self):
        """计时循环"""
        while self.is_running and self.remaining_seconds > 0:
            if not self.is_paused:
                time.sleep(1)
                self.remaining_seconds -= 1
                
                # 每分钟通知一次
                if self.remaining_seconds % 60 == 0:
                    self._notify_callbacks('tick', {
                        'remaining': self.remaining_seconds,
                        'minutes': self.remaining_seconds // 60
                    })
            else:
                time.sleep(0.1)  # 暂停时更频繁地检查
        
        if self.is_running and self.remaining_seconds <= 0:
            self._on_timer_complete()
    
    def _on_timer_complete(self):
        """计时完成"""
        session_type = self.current_session['type']
        
        if session_type == 'work':
            # 工作时段结束
            self._notify_callbacks('work_complete', self.current_session)
            
            # 自动开始休息
            self.start_break()
        elif session_type == 'break':
            # 休息结束
            self._notify_callbacks('break_complete', self.current_session)
            self.stop(completed=True)
    
    def start_break(self, is_long=False):
        """开始休息"""
        break_minutes = self.long_break_minutes if is_long else self.break_minutes
        
        self.current_session = {
            'session_id': self.current_session['session_id'],
            'start_time': datetime.now(),
            'type': 'break',
            'planned_minutes': break_minutes,
            'paused_duration': 0,
            'pause_start': None
        }
        
        self.is_running = True
        self.is_paused = False
        self.remaining_seconds = break_minutes * 60
        
        self._notify_callbacks('break_start', {'minutes': break_minutes, 'is_long': is_long})
    
    def get_status(self):
        """获取当前状态"""
        if not self.is_running:
            return {
                'status': 'idle',
                'message': '当前没有进行中的番茄钟'
            }
        
        if self.is_paused:
            elapsed = self._calculate_elapsed()
            remaining = self.current_session['planned_minutes'] * 60 - elapsed
            
            return {
                'status': 'paused',
                'type': self.current_session['type'],
                'elapsed_seconds': elapsed,
                'remaining_seconds': max(0, remaining),
                'message': f'已暂停，剩余 {remaining // 60} 分 {remaining % 60} 秒'
            }
        
        return {
            'status': 'running',
            'type': self.current_session['type'],
            'remaining_seconds': self.remaining_seconds,
            'message': self._format_time(self.remaining_seconds)
        }
    
    def _calculate_elapsed(self):
        """计算已用时间"""
        if not self.current_session:
            return 0
        
        start_time = self.current_session['start_time']
        total_seconds = (datetime.now() - start_time).seconds
        paused = self.current_session['paused_duration']
        
        if self.is_paused and self.current_session.get('pause_start'):
            paused += (datetime.now() - self.current_session['pause_start']).seconds
        
        return total_seconds - paused
    
    def _format_time(self, seconds):
        """格式化时间"""
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"
    
    def get_config(self):
        """获取配置"""
        return self.config['timer']
    
    def update_config(self, **kwargs):
        """更新配置"""
        self.work_minutes = kwargs.get('work_minutes', self.work_minutes)
        self.break_minutes = kwargs.get('break_minutes', self.break_minutes)
        self.long_break_minutes = kwargs.get('long_break_minutes', self.long_break_minutes)
        self.rounds = kwargs.get('rounds', self.rounds)
        
        # 更新配置文件
        config = load_config()
        config['timer']['work_minutes'] = self.work_minutes
        config['timer']['break_minutes'] = self.break_minutes
        config['timer']['long_break_minutes'] = self.long_break_minutes
        config['timer']['rounds'] = self.rounds
        
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        
        return True


# 单元测试
if __name__ == "__main__":
    pomodoro = PomodoroCore()
    
    # 测试配置
    config = pomodoro.get_config()
    print(f"[OK] 配置: {config}")
    
    # 测试开始
    success, message = pomodoro.start("测试专注任务")
    print(f"[OK] 开始: {message}")
    
    # 测试状态
    for i in range(3):
        time.sleep(1)
        status = pomodoro.get_status()
        print(f"[OK] 状态: {status['message']}")
    
    # 测试暂停
    success, message = pomodoro.pause()
    print(f"[OK] 暂停: {message}")
    
    time.sleep(2)
    
    # 测试继续
    success, message = pomodoro.resume()
    print(f"[OK] 继续: {message}")
    
    # 测试停止
    success, message = pomodoro.stop(completed=True)
    print(f"[OK] 停止: {message}")
