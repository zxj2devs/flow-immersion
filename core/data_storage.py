#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Copyright (c) 2026 ZXJ@DEVS. Author: QQ 1817694478 | Q-Group: 972156177
# Skill: flow-immersion | Version: 3.2.2
"""
Flow Immersion Mode - 数据存储模块
会话历史、统计数据管理
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
import uuid

# 编码兼容处理
try:
    if sys.stdout and sys.stdout.encoding != 'utf-8':
        sys.stdout = open(sys.stdout.fileno(), mode='w', encoding='utf-8', buffering=1)
    if sys.stderr and sys.stderr.encoding != 'utf-8':
        sys.stderr = open(sys.stderr.fileno(), mode='w', encoding='utf-8', buffering=1)
except Exception:
    pass

    sys._data_storage_utf8_set = True


class DataStorage:
    """数据存储管理器"""
    
    def __init__(self, storage_path=None):
        if storage_path:
            self.storage_path = Path(storage_path)
        else:
            self.storage_path = Path.home() / ".flow-immersion"
        
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.sessions_dir = self.storage_path / "sessions"
        self.sessions_dir.mkdir(exist_ok=True)
        
        self.stats_file = self.storage_path / "stats.json"
        self.session_template = self.storage_path / "template.json"
    
    def _get_session_file(self, session_id):
        """获取会话文件路径"""
        return self.sessions_dir / f"{session_id}.json"
    
    def create_session(self, task=None, planned_minutes=25):
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        
        session = {
            "session_id": session_id,
            "start_time": datetime.now().isoformat(),
            "end_time": None,
            "task": task,
            "planned_minutes": planned_minutes,
            "actual_minutes": 0,
            "completed": False,
            "status": "active",
            "checkins": [],
            "energy_before": 7,
            "energy_after": 5,
            "dopamine_breaks": 0,
            "autopsy": {
                "what_helped": "",
                "what_didnt": "",
                "next_time": ""
            }
        }
        
        # 保存会话
        self.save_session(session)
        
        return session
    
    def save_session(self, session):
        """保存会话"""
        session_id = session['session_id']
        file_path = self._get_session_file(session_id)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
    
    def get_session(self, session_id):
        """获取会话"""
        file_path = self._get_session_file(session_id)
        
        if not file_path.exists():
            return None
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_active_session(self):
        """获取当前活跃会话"""
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session = json.load(f)
                    if session.get('status') == 'active':
                        return session
            except Exception:
                continue
        
        return None
    
    def end_session(self, session_id, completed=True, actual_minutes=0):
        """结束会话"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        session['end_time'] = datetime.now().isoformat()
        session['status'] = 'completed' if completed else 'aborted'
        session['completed'] = completed
        session['actual_minutes'] = actual_minutes
        
        self.save_session(session)
        
        # 更新统计
        self._update_stats(session)
        
        return session
    
    def add_checkin(self, session_id, checkin_type="timer", notes=""):
        """添加检查点"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        checkin = {
            "time": datetime.now().isoformat(),
            "type": checkin_type,
            "notes": notes
        }
        
        session['checkins'].append(checkin)
        self.save_session(session)
        
        return session
    
    def add_dopamine_break(self, session_id, break_type="physical"):
        """记录多巴胺休息"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        session['dopamine_breaks'] += 1
        self.save_session(session)
        
        return session
    
    def set_autopsy(self, session_id, helped="", didnt="", next_time=""):
        """设置复盘内容"""
        session = self.get_session(session_id)
        
        if not session:
            return None
        
        session['autopsy'] = {
            "what_helped": helped,
            "what_didnt": didnt,
            "next_time": next_time
        }
        
        self.save_session(session)
        
        return session
    
    def get_recent_sessions(self, limit=10):
        """获取最近的会话"""
        sessions = []
        
        session_files = sorted(
            self.sessions_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )
        
        for session_file in session_files[:limit]:
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    sessions.append(json.load(f))
            except Exception:
                continue
        
        return sessions
    
    def _update_stats(self, session):
        """更新统计数据"""
        stats = self._load_stats()
        
        # 获取当前日期
        today = datetime.now().strftime('%Y-%m-%d')
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
        
        # 初始化今日和本周数据
        if 'daily' not in stats:
            stats['daily'] = {}
        
        if today not in stats['daily']:
            stats['daily'][today] = {
                'sessions': 0,
                'total_minutes': 0,
                'completed': 0
            }
        
        # 更新今日数据
        stats['daily'][today]['sessions'] += 1
        stats['daily'][today]['total_minutes'] += session.get('actual_minutes', 0)
        if session.get('completed'):
            stats['daily'][today]['completed'] += 1
        
        # 清理旧数据（保留30天）
        cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        stats['daily'] = {
            k: v for k, v in stats['daily'].items()
            if k >= cutoff
        }
        
        # 保存统计
        self._save_stats(stats)
    
    def _load_stats(self):
        """加载统计数据"""
        if not self.stats_file.exists():
            return {
                'daily': {},
                'weekly': {},
                'streak_days': 0,
                'patterns': {}
            }
        
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {
                'daily': {},
                'weekly': {},
                'streak_days': 0,
                'patterns': {}
            }
    
    def _save_stats(self, stats):
        """保存统计数据"""
        with open(self.stats_file, 'w', encoding='utf-8') as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    
    def get_stats(self):
        """获取统计数据"""
        stats = self._load_stats()
        
        today = datetime.now().strftime('%Y-%m-%d')
        week_start = (datetime.now() - timedelta(days=datetime.now().weekday())).strftime('%Y-%m-%d')
        
        # 今日统计
        today_data = stats.get('daily', {}).get(today, {})
        
        # 本周统计
        week_data = {'sessions': 0, 'total_minutes': 0, 'total_hours': 0}
        for date_str, data in stats.get('daily', {}).items():
            if date_str >= week_start:
                week_data['sessions'] += data.get('sessions', 0)
                week_data['total_minutes'] += data.get('total_minutes', 0)
        
        week_data['total_hours'] = week_data['total_minutes'] / 60
        
        # 计算完成率
        completion_rate = 0
        if today_data.get('sessions', 0) > 0:
            completion_rate = today_data.get('completed', 0) / today_data.get('sessions', 0)
        
        # 计算连续天数
        streak = self._calculate_streak(stats)
        
        return {
            'today': {
                'sessions': today_data.get('sessions', 0),
                'total_minutes': today_data.get('total_minutes', 0),
                'completion_rate': completion_rate
            },
            'week': week_data,
            'streak_days': streak
        }
    
    def _calculate_streak(self, stats):
        """计算连续专注天数"""
        streak = 0
        current_date = datetime.now()
        
        for i in range(365):
            check_date = (current_date - timedelta(days=i)).strftime('%Y-%m-%d')
            
            if stats.get('daily', {}).get(check_date, {}).get('sessions', 0) > 0:
                streak += 1
            else:
                if i > 0:  # 今天可以没有数据
                    break
        
        return streak
    
    def get_session_history(self, days=30):
        """获取历史会话"""
        sessions = []
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    session = json.load(f)
                    
                # 过滤日期
                start_date = session.get('start_time', '')[:10]
                if start_date >= cutoff:
                    sessions.append(session)
            except Exception:
                continue
        
        return sorted(sessions, key=lambda s: s.get('start_time', ''), reverse=True)


# 单元测试
if __name__ == "__main__":
    storage = DataStorage()
    
    # 测试创建会话
    session = storage.create_session(task="测试任务", planned_minutes=25)
    print(f"[OK] 创建会话: {session['session_id']}")
    
    # 测试添加检查点
    storage.add_checkin(session['session_id'], "timer", "第一个25分钟完成")
    print("[OK] 添加检查点")
    
    # 测试结束会话
    storage.end_session(session['session_id'], completed=True, actual_minutes=28)
    print("[OK] 结束会话")
    
    # 测试获取统计
    stats = storage.get_stats()
    print(f"\n统计数据: {stats}")
    
    # 测试获取最近会话
    sessions = storage.get_recent_sessions()
    print(f"\n最近会话数: {len(sessions)}")
