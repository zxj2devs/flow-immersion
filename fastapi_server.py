# -*- coding: utf-8 -*-
# Copyright (c) 2026 ZXJ@DEVS. Author: QQ 1817694478 | Q-Group: 972156177
# Skill: flow-immersion | Version: 3.2.5
"""
FlowImmersion FastAPI Server v3.2.5
Pomodoro + ADHD Companion + Desktop Control + Data Tracking
Self-monitoring & auto-repair on startup and periodic scan
"""
import sys
import os
import json
import uuid
import struct
import subprocess
import ctypes
import traceback
import threading
import time
import atexit
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

# 编码兼容
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

# ============= 配置路径 =============
API_PORT = 8765
SKILL_DIR = Path(__file__).parent
WEB_DIR = SKILL_DIR / "web"
CONFIG_FILE = SKILL_DIR / "config.json"
DATA_DIR = SKILL_DIR / "data"
SESSIONS_DIR = DATA_DIR / "sessions"
STATS_FILE = DATA_DIR / "stats.json"
WIZARD_FILE = DATA_DIR / "wizard_history.json"

DATA_DIR.mkdir(exist_ok=True)
SESSIONS_DIR.mkdir(exist_ok=True)
WEB_DIR.mkdir(exist_ok=True)

# ============= 错误日志 + 自修复系统 =============
ERROR_LOG_FILE = DATA_DIR / "error_logs.json"
AUTO_FIX_LOG = DATA_DIR / "auto_fixes.json"
BACKUP_DIR = DATA_DIR / "backups"
REPAIR_QUEUE_FILE = DATA_DIR / "repair_queue.json"
PLANS_DIR = DATA_DIR / "plans"
PLANS_DIR.mkdir(exist_ok=True)
ENERGY_FILE = DATA_DIR / "energy.json"
REMINDERS_FILE = DATA_DIR / "reminders.json"

# ---- 错误日志读写 ----
def _load_error_logs() -> list:
    if ERROR_LOG_FILE.exists():
        try:
            with open(ERROR_LOG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def _save_error_logs(logs: list):
    try:
        with open(ERROR_LOG_FILE, 'w', encoding='utf-8') as f:
            json.dump(logs[-500:], f, ensure_ascii=False, indent=2)
    except:
        pass

def log_error(err_type: str, error_msg: str, context: str = "", exc=None, auto_fixed: bool = False, fix_note: str = ""):
    """记录错误到日志文件，仅记录错误类日志（startup/shutdown/exit/info除外）"""
    # 非错误类仅打印不记录
    if err_type in ("startup", "shutdown", "exit", "info"):
        print(f"[{err_type.upper()}] {error_msg}")
        return
    logs = _load_error_logs()
    tb = ''.join(traceback.format_exception(type(exc), exc, exc.__traceback__)) if exc else ''
    entry = {
        "timestamp": datetime.now().isoformat(),
        "type": err_type,
        "error": str(error_msg),
        "traceback": tb,
        "context": context,
        "resolved": False,
        "auto_fixed": auto_fixed,
        "fix_note": fix_note or None,
    }
    logs.append(entry)
    _save_error_logs(logs)
    tag = " [AUTO-FIXED]" if auto_fixed else ""
    print(f"[ERROR] [{err_type}]{tag} {error_msg}")

# ---- 自修复日志 ----
def _load_auto_fixes() -> list:
    if AUTO_FIX_LOG.exists():
        try:
            with open(AUTO_FIX_LOG, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def _save_auto_fixes(fixes: list):
    try:
        with open(AUTO_FIX_LOG, 'w', encoding='utf-8') as f:
            json.dump(fixes[-100:], f, ensure_ascii=False, indent=2)
    except:
        pass

# ---- 备份机制（修复前自动备份，修复失败可恢复） ----
BACKUP_DIR.mkdir(exist_ok=True)

def _backup_file(file_path: Path) -> Path:
    """备份文件到 backups/ 目录，返回备份路径。同名备份覆盖"""
    bak_dir = BACKUP_DIR / file_path.stem
    bak_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak_path = bak_dir / f"{file_path.name}.bak_{ts}"
    try:
        import shutil
        shutil.copy2(str(file_path), str(bak_path))
        # 只保留每个文件最新3个备份
        existing = sorted(bak_dir.glob(f"{file_path.name}.bak_*"), reverse=True)
        for old in existing[3:]:
            try:
                old.unlink()
            except:
                pass
    except Exception as e:
        print(f"  [BACKUP] warning: failed to backup {file_path.name}: {e}")
    return bak_path

def _restore_from_backup(file_path: Path, bak_path: Path) -> bool:
    """从备份恢复文件"""
    try:
        import shutil
        shutil.copy2(str(bak_path), str(file_path))
        _record_fix("restore", str(file_path.name), f"restored_from_{bak_path.name}", "high", "repair failed, rollback")
        return True
    except Exception as e:
        print(f"  [BACKUP] CRITICAL: restore failed for {file_path.name}: {e}")
        return False

# ---- LLM修复队列（内置规则无法处理的问题，等待LLM修复） ----
def _load_repair_queue() -> list:
    if REPAIR_QUEUE_FILE.exists():
        try:
            with open(REPAIR_QUEUE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return []

def _save_repair_queue(queue: list):
    try:
        with open(REPAIR_QUEUE_FILE, 'w', encoding='utf-8') as f:
            json.dump(queue[-50:], f, ensure_ascii=False, indent=2)
    except:
        pass

def _add_to_repair_queue(err_type: str, error_msg: str, context: str, severity: str = "medium"):
    """将内置规则无法解决的错误加入LLM修复队列"""
    queue = _load_repair_queue()
    # 去重：同一err_type+context只保留最新一条
    queue = [q for q in queue if not (q.get("type") == err_type and q.get("context") == context)]
    queue.append({
        "id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now().isoformat(),
        "type": err_type,
        "error": str(error_msg)[:500],
        "context": context[:200],
        "severity": severity,
        "status": "pending",  # pending / llm_attempted / resolved
    })
    _save_repair_queue(queue)

def _record_fix(action: str, target: str, result: str, severity: str = "medium", detail: str = ""):
    """记录一次修复动作"""
    fixes = _load_auto_fixes()
    fixes.append({
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "target": target,
        "result": result,
        "severity": severity,
        "detail": detail,
    })
    _save_auto_fixes(fixes)
    print(f"  [AUTO-FIX] {action}: {target} -> {result}")

# ============= 自修复规则库（真正执行修复） =============

def _fix_corrupt_json_file(file_path: Path, default_data: dict, label: str) -> bool:
    """修复损坏的JSON配置文件：备份→校验→重写默认值→失败恢复"""
    if not file_path.exists():
        return False
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            return False  # 文件正常
    except Exception:
        pass
    # 文件损坏 → 先备份
    bak_path = _backup_file(file_path)
    # 重写默认值
    try:
        file_path.write_text(json.dumps(default_data, ensure_ascii=False, indent=2), encoding='utf-8')
        _record_fix("rewrite_json", str(file_path.name), "replaced_with_default", "high", f"corrupt, backup={bak_path.name}")
        return True
    except Exception as e:
        # 修复失败 → 从备份恢复
        if bak_path.exists():
            _restore_from_backup(file_path, bak_path)
        else:
            _record_fix("rewrite_json", str(file_path.name), f"failed_no_backup: {e}", "high")
        return False

def _fix_missing_data_dirs() -> bool:
    """确保所有必要的数据目录存在"""
    fixed = False
    dirs_to_check = [DATA_DIR, SESSIONS_DIR, PLANS_DIR, WEB_DIR]
    for d in dirs_to_check:
        if not d.exists():
            try:
                d.mkdir(parents=True, exist_ok=True)
                _record_fix("mkdir", str(d.name), "created", "high", "missing directory")
                fixed = True
            except Exception as e:
                _record_fix("mkdir", str(d.name), f"failed: {e}", "high")
    return fixed

def _fix_config_missing_keys() -> bool:
    """修复config.json缺少必要键（先备份再修改）"""
    if not CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2), encoding='utf-8')
            state.config = DEFAULT_CONFIG.copy()
            _record_fix("config_init", "config.json", "created_with_defaults", "high")
            return True
        except:
            return False
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    # 补全缺失的顶层键
    changed = False
    missing = [k for k in DEFAULT_CONFIG if k not in cfg]
    if missing:
        bak_path = _backup_file(CONFIG_FILE)
        for key in missing:
            cfg[key] = DEFAULT_CONFIG[key]
        changed = True
        try:
            save_config(cfg)
            _record_fix("config_patch", "config.json", "patched_missing_keys", "medium", f"added: {missing}, backup={bak_path.name}")
        except Exception as e:
            if bak_path.exists():
                _restore_from_backup(CONFIG_FILE, bak_path)
            else:
                _record_fix("config_patch", "config.json", f"failed: {e}", "high")
            changed = False
    return changed

def _fix_stale_plan_files() -> bool:
    """清理超过7天的计划文件"""
    if not PLANS_DIR.exists():
        return False
    cutoff = datetime.now() - timedelta(days=7)
    removed = 0
    for pf in PLANS_DIR.glob("*.json"):
        try:
            mtime = datetime.fromtimestamp(pf.stat().st_mtime)
            if mtime < cutoff:
                pf.unlink()
                removed += 1
        except:
            pass
    if removed > 0:
        _record_fix("cleanup_plans", f"plans/*.json", f"removed_{removed}_stale_files", "low", "older than 7 days")
        return True
    return False

def _fix_orphan_session_files() -> bool:
    """清理超过30天的会话文件"""
    if not SESSIONS_DIR.exists():
        return False
    cutoff = datetime.now() - timedelta(days=30)
    removed = 0
    for sf in SESSIONS_DIR.glob("*.json"):
        try:
            mtime = datetime.fromtimestamp(sf.stat().st_mtime)
            if mtime < cutoff:
                sf.unlink()
                removed += 1
        except:
            pass
    if removed > 0:
        _record_fix("cleanup_sessions", f"sessions/*.json", f"removed_{removed}_stale_files", "low", "older than 30 days")
        return True
    return False

def _fix_error_log_overflow() -> bool:
    """错误日志超过500条时压缩旧日志（先备份再压缩）"""
    logs = _load_error_logs()
    if len(logs) <= 500:
        return False
    _backup_file(ERROR_LOG_FILE)
    # 保留最近200条未解决 + 最近100条已解决
    unresolved = [l for l in logs if not l.get("resolved") and not l.get("auto_fixed")][-200:]
    resolved = [l for l in logs if l.get("resolved") or l.get("auto_fixed")][-100:]
    # 标记超过30天的未解决日志为resolved（已过期）
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    for l in unresolved:
        if l.get("timestamp", "") < cutoff:
            l["resolved"] = True
    merged = resolved + unresolved
    merged.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    _save_error_logs(merged)
    _record_fix("log_cleanup", "error_logs.json", f"trimmed_{len(logs)}_to_{len(merged)}", "low", "compressed stale entries")
    return True

def _fix_recurring_error(logs: list, err_type: str, count_threshold: int = 5, time_window_minutes: int = 60) -> bool:
    """检测短时间内同一类型错误高频出现，尝试智能修复；无法修复的加入LLM队列"""
    now = datetime.now()
    cutoff = (now - timedelta(minutes=time_window_minutes)).isoformat()
    recent = [l for l in logs if l.get("type") == err_type and l.get("timestamp", "") >= cutoff]
    if len(recent) < count_threshold:
        return False
    error_str = " ".join(l.get("error", "") + l.get("traceback", "") for l in recent).lower()
    fixed = False
    # JSON解析错误 → 修复相关文件
    if "jsondecodeerror" in error_str or "expecting value" in error_str:
        for fp, default in [(REMINDERS_FILE, {"enabled": False, "active_items": [], "custom_interval": 30, "custom_message": "", "custom_reminders": []}),
                            (ENERGY_FILE, {"entries": []}),
                            (STATS_FILE, {"total_sessions": 0, "total_focus_minutes": 0, "total_breaks": 0, "daily_stats": {}, "patterns": {"streak_days": 0}})]:
            if fp.name in error_str.replace("\\", "/").split("/")[-1] or str(fp) in error_str:
                fixed = _fix_corrupt_json_file(fp, default, fp.name) or fixed
    # 内置规则无法修复 → 加入LLM修复队列
    if not fixed:
        sample_error = recent[0].get("error", "")[:200]
        sample_context = recent[0].get("context", "")[:200]
        _add_to_repair_queue(err_type, f"recurring({len(recent)}x): {sample_error}", sample_context, "high")
        print(f"  [REPAIR-QUEUE] Added {err_type} to LLM repair queue ({len(recent)} occurrences)")
    return fixed

def run_self_repair() -> dict:
    """执行全量自修复扫描，返回修复报告"""
    report = {"checks": [], "total_fixed": 0}
    logs = _load_error_logs()

    # 1. 目录检查
    if _fix_missing_data_dirs():
        report["checks"].append({"check": "data_dirs", "status": "fixed"})
        report["total_fixed"] += 1
    else:
        report["checks"].append({"check": "data_dirs", "status": "ok"})

    # 2. JSON文件完整性检查
    json_files = [
        (CONFIG_FILE, DEFAULT_CONFIG, "config.json"),
        (STATS_FILE, {"total_sessions": 0, "total_focus_minutes": 0, "total_breaks": 0, "daily_stats": {}, "patterns": {"streak_days": 0}}, "stats.json"),
        (REMINDERS_FILE, {"enabled": False, "active_items": [], "custom_interval": 30, "custom_message": "", "custom_reminders": []}, "reminders.json"),
        (ENERGY_FILE, {"entries": []}, "energy.json"),
    ]
    for fp, default, label in json_files:
        if _fix_corrupt_json_file(fp, default, label):
            report["checks"].append({"check": f"json_{label}", "status": "fixed"})
            report["total_fixed"] += 1
        else:
            report["checks"].append({"check": f"json_{label}", "status": "ok"})

    # 3. 配置补全
    if _fix_config_missing_keys():
        report["checks"].append({"check": "config_keys", "status": "fixed"})
        report["total_fixed"] += 1
    else:
        report["checks"].append({"check": "config_keys", "status": "ok"})

    # 4. 过期文件清理
    if _fix_stale_plan_files():
        report["checks"].append({"check": "stale_plans", "status": "cleaned"})
        report["total_fixed"] += 1
    else:
        report["checks"].append({"check": "stale_plans", "status": "ok"})

    if _fix_orphan_session_files():
        report["checks"].append({"check": "stale_sessions", "status": "cleaned"})
        report["total_fixed"] += 1
    else:
        report["checks"].append({"check": "stale_sessions", "status": "ok"})

    # 5. 错误日志压缩
    if _fix_error_log_overflow():
        report["checks"].append({"check": "log_overflow", "status": "cleaned"})
        report["total_fixed"] += 1
    else:
        report["checks"].append({"check": "log_overflow", "status": "ok"})

    # 6. 高频错误智能修复
    error_types = set(l.get("type", "") for l in logs if l.get("type") not in ("startup", "shutdown", "exit", "info"))
    for et in error_types:
        if _fix_recurring_error(logs, et):
            report["checks"].append({"check": f"recurring_{et}", "status": "fixed"})
            report["total_fixed"] += 1

    # 7. 错误统计
    error_stats = {"total": len(logs), "unresolved": 0, "by_type": {}}
    for log in logs:
        t = log.get("type", "unknown")
        if not log.get("resolved") and not log.get("auto_fixed"):
            error_stats["unresolved"] += 1
        if t not in ("startup", "shutdown", "exit", "info"):
            error_stats["by_type"][t] = error_stats["by_type"].get(t, 0) + 1
    report["stats"] = error_stats
    report["recent_fixes"] = _load_auto_fixes()[-10:]

    return report

# ============= 请求监控中间件 =============
async def _monitor_middleware(request: Request, call_next):
    """监控每个请求：记录耗时、捕获异常"""
    start = time.time()
    method = request.method
    path = request.url.path
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception as e:
        tb = traceback.format_exc()
        elapsed = time.time() - start
        log_error("request_error", f"{method} {path} -> {status_code} ({elapsed:.1f}s)", f"{str(e)[:200]}", e)
        raise
    finally:
        elapsed = time.time() - start
        # 仅记录异常请求（4xx/5xx且非静态资源）
        if status_code >= 400 and not path.endswith(('.html', '.css', '.js', '.png', '.jpg', '.ico', '.svg')):
            log_error("http_error", f"{method} {path} -> {status_code} ({elapsed:.1f}s)",
                       f"status={status_code}")

def _print_startup_report(report: dict):
    """打印启动自检报告"""
    print()
    print("=" * 50)
    print("  FlowImmersion Startup Self-Check")
    print("=" * 50)
    stats = report.get("stats", {})
    print(f"  Error log: {stats.get('total', 0)} total, {stats.get('unresolved', 0)} unresolved")
    by_type = stats.get("by_type", {})
    if by_type:
        print("  Error breakdown:")
        for t, n in sorted(by_type.items(), key=lambda x: -x[1])[:8]:
            print(f"    - {t}: {n}x")
    checks = report.get("checks", [])
    fixed_count = sum(1 for c in checks if c.get("status") in ("fixed", "cleaned"))
    if fixed_count > 0:
        print(f"\n  Auto-repair: {fixed_count} issue(s) fixed")
        for c in checks:
            if c.get("status") in ("fixed", "cleaned"):
                print(f"    [FIXED] {c['check']}")
    else:
        print(f"\n  All {len(checks)} checks passed, no repair needed")
    recent = report.get("recent_fixes", [])
    if recent:
        print(f"\n  Recent auto-fixes ({len(recent)}):")
        for fx in recent[-5:]:
            print(f"    {fx.get('timestamp', '')[:16]} {fx.get('action', '')} {fx.get('target', '')}: {fx.get('result', '')}")
    print("=" * 50)

# ============= Windows API =============
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

WALLPAPER_PRESETS = {
    'ocean':    (0x66, 0x7e, 0xea),
    'forest':   (0x11, 0x99, 0x8e),
    'sunset':   (0xf0, 0x93, 0xfb),
    'night':    (0x0f, 0x0c, 0x29),
    'minimal':  (0x1a, 0x1a, 0x2e),
    'zen':      (0x13, 0x4e, 0x5e),
    'neon':     (0xfc, 0x46, 0x6b),
    'nature':   (0x56, 0xab, 0x2f),
}

# ============= pywin32 桌面控制 =============
try:
    import win32gui, win32con
    PYWIN32_AVAILABLE = True
except ImportError:
    PYWIN32_AVAILABLE = False


def _find_shell_def_view():
    hDesktop = win32gui.FindWindow("ProgMan", None)
    if hDesktop:
        h = win32gui.FindWindowEx(hDesktop, None, "SHELLDLL_DefView", None)
        if h:
            return h
    hwnd = None
    while True:
        hwnd = win32gui.FindWindowEx(None, hwnd, "WorkerW", None)
        if not hwnd:
            break
        h = win32gui.FindWindowEx(hwnd, None, "SHELLDLL_DefView", None)
        if h:
            return h
    return 0


def _find_listview():
    hShellDefView = _find_shell_def_view()
    if hShellDefView:
        return win32gui.FindWindowEx(hShellDefView, None, "SysListView32", "FolderView")
    return 0


def hide_icons():
    if not PYWIN32_AVAILABLE:
        return False
    h = _find_listview()
    if h:
        win32gui.ShowWindow(h, win32con.SW_HIDE)
        return True
    return False


def show_icons():
    if not PYWIN32_AVAILABLE:
        return False
    h = _find_listview()
    if h:
        win32gui.ShowWindow(h, win32con.SW_SHOW)
        return True
    return False


def is_icons_visible():
    if not PYWIN32_AVAILABLE:
        return True
    h = _find_listview()
    if h:
        return bool(win32gui.IsWindowVisible(h))


def _find_window_by_pid(pid):
    """根据进程ID找到对应的可见窗口句柄"""
    if not PYWIN32_AVAILABLE:
        return 0
    result = []

    def enum_cb(h, _):
        try:
            import win32process
            _, pid2 = win32process.GetWindowThreadProcessId(h)
            if pid2 == pid and win32gui.IsWindowVisible(h) and win32gui.IsWindowEnabled(h):
                rect = win32gui.GetWindowRect(h)
                w, h2 = rect[2] - rect[0], rect[3] - rect[1]
                if 50 < w < 3840 and 30 < h2 < 2160:
                    result.append(h)
        except:
            pass
        return True

    win32gui.EnumWindows(enum_cb, None)
    # 返回面积最大的那个（通常是主窗口）
    if result:
        return max(result, key=lambda h: (
            (win32gui.GetWindowRect(h)[2] - win32gui.GetWindowRect(h)[0]) *
            (win32gui.GetWindowRect(h)[3] - win32gui.GetWindowRect(h)[1])
        ))
    return 0


def _topmost_guardian(pid, x, y, w, h):
    """定期重新置顶：每10秒强制应用WS_EX_TOPMOST"""
    if not PYWIN32_AVAILABLE:
        return
    import time as _time, psutil

    # 先等待窗口创建
    handle = 0
    for _ in range(60):
        if not _is_pid_alive(pid):
            print(f"[FlowImmersion] 进程 {pid} 已退出，守护结束")
            return
        handle = _find_window_by_pid(pid)
        if handle:
            break
        _time.sleep(1)

    if not handle:
        print(f"[FlowImmersion] 未找到窗口句柄 (PID {pid})")
        return

    print(f"[FlowImmersion] 置顶守护已启动 (PID {pid}, HWND {handle})")
    _refresh_count = 0
    while True:
        try:
            if not _is_pid_alive(pid):
                print(f"[FlowImmersion] 进程 {pid} 退出，守护结束")
                return
            # 检查用户是否关闭了置顶
            if not _topmost_enabled:
                _time.sleep(3)
                continue
            # 每30秒重新查找窗口句柄（Chrome可能重建窗口）
            _refresh_count += 1
            if _refresh_count % 3 == 0:
                new_h = _find_window_by_pid(pid)
                if new_h:
                    handle = new_h
            if handle:
                exstyle = win32gui.GetWindowLong(handle, win32con.GWL_EXSTYLE)
                win32gui.SetWindowLong(handle, win32con.GWL_EXSTYLE, exstyle | 0x00000008)
                win32gui.SetWindowPos(handle, win32con.HWND_TOPMOST, x, y, w, h, win32con.SWP_SHOWWINDOW)
        except Exception:
            pass
        _time.sleep(3)
    return True


def _is_pid_alive(pid):
    """检查进程是否存活"""
    try:
        import psutil
        return psutil.pid_exists(pid)
    except:
        return False


# ============= 壁纸生成 =============
def _create_solid_bmp(path, color, width=1920, height=1080):
    row_size = (width * 3 + 3) & ~3
    image_size = row_size * height
    file_size = 54 + image_size
    r, g, b = color

    with open(path, 'wb') as f:
        f.write(b'BM')
        f.write(struct.pack('<I', file_size))
        f.write(struct.pack('<H', 0))
        f.write(struct.pack('<H', 0))
        f.write(struct.pack('<I', 54))
        f.write(struct.pack('<I', 40))
        f.write(struct.pack('<i', width))
        f.write(struct.pack('<i', -height))
        f.write(struct.pack('<H', 1))
        f.write(struct.pack('<H', 24))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', image_size))
        f.write(struct.pack('<i', 0))
        f.write(struct.pack('<i', 0))
        f.write(struct.pack('<I', 0))
        f.write(struct.pack('<I', 0))
        row = bytes([b, g, r] * width) + b'\x00' * (row_size - width * 3)
        for _ in range(height):
            f.write(row)


def set_wallpaper_by_preset(preset='minimal'):
    global _original_wallpaper
    # 首次修改壁纸前保存原始
    if _original_wallpaper is None:
        _original_wallpaper = get_current_wallpaper()
    color = WALLPAPER_PRESETS.get(preset, (0x1a, 0x1a, 0x2e))
    bmp_path = DATA_DIR / f"wallpaper_{preset}.bmp"
    _create_solid_bmp(bmp_path, color)
    try:
        abs_path = str(bmp_path.absolute())
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, abs_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        return result, abs_path
    except Exception as e:
        return False, str(e)


def set_wallpaper_by_path(path):
    if not os.path.exists(path):
        return False, f"文件不存在: {path}"
    try:
        abs_path = os.path.abspath(path)
        result = ctypes.windll.user32.SystemParametersInfoW(
            SPI_SETDESKWALLPAPER, 0, abs_path,
            SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
        )
        return result, abs_path
    except Exception as e:
        return False, str(e)


def get_current_wallpaper():
    try:
        result = subprocess.run(
            ['powershell', '-Command', '[SystemParametersInfo]::GetDesktopWallpaper()'],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


# ============= 默认配置 =============
DEFAULT_CONFIG = {
    "pomodoro": {
        "focus_duration": 25, "short_break": 5, "long_break": 15,
        "sessions_before_long_break": 4, "auto_start_break": False,
        "auto_start_focus": False
    },
    "adhd": {
        "check_in_interval": 15, "micro_step_enabled": True,
        "dopamine_menu_enabled": True, "emergency_reset_enabled": True
    },
    "immersion": {
        "hide_icons_on_start": True, "wallpaper_preset": "minimal",
        "music_enabled": False, "music_volume": 50,
        "music_dir": "", "music_mode": "loop"
    },
    "personalize": {
        "bg_id": "dark", "bg_color": "#080810", "text_color": "#dde4f0",
        "time_font": "Consolas", "time_size": "5rem", "brightness": "0.85",
        "accent1": "#6366f1", "accent2": "#a855f7"
    },
    "reminder": {
        "enabled": True, "active_items": ["water","eye","stretch","posture","breathe"],
        "custom_interval": 30, "custom_message": "", "custom_reminders": []
    },
    "tracking": {"track_sessions": True, "track_breaks": True,
                 "track_distractions": True, "daily_goal": 8},
    
}

# ============= 状态管理 =============
class State:
    config = None
    current_session = None
    stats = None

state = State()

# mini-mode 窗口状态（防止重复打开）
_mini_window_pid = None  # 当前mini窗口进程PID

# 置顶守护状态
_topmost_enabled = True   # 守护线程是否执行置顶操作
_main_window_pid = None   # 沉浸窗口PID（用于移动窗口）

# 原始壁纸（用于恢复）
_original_wallpaper = None  # 首次修改壁纸前保存原始路径

# ============= 桌面快捷方式 =============

# 默认能量数据
DEFAULT_ENERGY = [
    {"id": "breathe", "label": "深呼吸", "seconds": 60, "completed": False},
    {"id": "stretch", "label": "伸展", "seconds": 120, "completed": False},
    {"id": "water", "label": "喝水", "seconds": 60, "completed": False},
    {"id": "eye", "label": "护眼", "seconds": 60, "completed": False},
    {"id": "posture", "label": "调整姿势", "seconds": 60, "completed": False},
]
# 默认提醒数据
DEFAULT_REMINDERS = {
    "enabled": True,
    "active_items": ["water", "eye", "stretch", "posture", "breathe"],
    "custom_interval": 30,
    "custom_message": "",
    "custom_reminders": []
}


def _create_desktop_shortcut():
    """创建桌面快捷方式：心流时钟💗"""
    try:
        desktop = Path(os.path.expanduser("~/Desktop"))
        shortcut_path = desktop / "心流时钟.url"
        if shortcut_path.exists():
            return True, str(shortcut_path) + " (已存在，跳过)"
        url = f"http://localhost:{API_PORT}"
        content = f"""[InternetShortcut]
URL={url}
"""
        shortcut_path.write_text(content, encoding='utf-8')
        return True, str(shortcut_path)
    except Exception as e:
        return False, str(e)


def _create_startup_bat():
    """创建桌面启动脚本：心流时钟启动.bat"""
    try:
        desktop = Path(os.path.expanduser("~/Desktop"))
        bat_path = desktop / "心流时钟启动.bat"
        run_bat = str((SKILL_DIR / "run_server.bat").absolute()).replace('/', '\\')
        # 直接调用 run_server.bat，用户可见运行界面
        content = f'@"{run_bat}"\r\n'
        if bat_path.exists():
            existing = bat_path.read_text(encoding='gbk', errors='ignore')
            if existing.strip() == content.strip():
                return True, str(bat_path) + " (内容相同，跳过)"
            bat_path.unlink()
        bat_path.write_text(content, encoding='gbk')
        return True, str(bat_path)
    except Exception as e:
        return False, str(e)


def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    state.config = cfg
    return cfg


def load_stats():
    if STATS_FILE.exists():
        try:
            with open(STATS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {"total_sessions": 0, "total_focus_minutes": 0, "total_breaks": 0,
            "daily_stats": {}, "patterns": {"streak_days": 0}}


def save_stats(sts):
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(sts, f, ensure_ascii=False, indent=2)
    state.stats = sts
    return sts


# ============= 会话管理 =============
def create_session(task=None, planned_minutes=25, session_type="focus"):
    session = {
        "id": uuid.uuid4().hex[:12],
        "task": task or "专注工作",
        "start_time": datetime.now().isoformat(),
        "end_time": None,
        "planned_minutes": planned_minutes,
        "actual_minutes": 0,
        "type": session_type,
        "completed": False,
        "distractions": 0,
        "check_ins": [],
        "micro_steps": [],
        "dopamine_breaks": [],
        "autopsy": {}
    }
    state.current_session = session
    return session


def complete_session(completed=True):
    if not state.current_session:
        return None
    s = state.current_session
    s["end_time"] = datetime.now().isoformat()
    s["completed"] = completed

    # 保存会话文件
    session_file = SESSIONS_DIR / f"{s['id']}.json"
    with open(session_file, 'w', encoding='utf-8') as f:
        json.dump(s, f, ensure_ascii=False, indent=2)

    # 更新统计
    _update_stats(s)
    state.current_session = None
    return s


def _update_stats(session):
    stats = load_stats()
    today = datetime.now().strftime("%Y-%m-%d")

    if session["type"] == "focus":
        stats["total_sessions"] += 1
        stats["total_focus_minutes"] += session.get("actual_minutes", 0)
    else:
        stats["total_breaks"] += 1

    if today not in stats["daily_stats"]:
        stats["daily_stats"][today] = {"sessions": 0, "focus_minutes": 0, "breaks": 0, "distractions": 0}

    if session["type"] == "focus":
        stats["daily_stats"][today]["sessions"] += 1
        stats["daily_stats"][today]["focus_minutes"] += session.get("actual_minutes", 0)
        stats["daily_stats"][today]["distractions"] += session.get("distractions", 0)
    else:
        stats["daily_stats"][today]["breaks"] += 1

    # 计算连续天数
    stats["patterns"]["streak_days"] = _calc_streak(stats)
    save_stats(stats)


def _calc_streak(stats):
    streak = 0
    today = datetime.now()
    for i in range(365):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        if stats.get("daily_stats", {}).get(d, {}).get("sessions", 0) > 0:
            streak += 1
        elif i > 0:
            break
    return streak


# ============= FastAPI =============
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(
    title="FlowImmersion",
    version="3.0.0",
    docs_url=None,       # 禁用 API docs
    redoc_url=None,
    openapi_url=None,
)
# 生产环境配置示例
origins = [
    "https://gpt.cntaxs.com",
    "http://localhost:8765",  # 可保留本地调试地址
]

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,  # 指定白名单
#     allow_credentials=True,
#     allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
#     allow_headers=["Content-Type", "Authorization"],
# )
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============= 请求监控中间件 =============
from starlette.middleware.base import BaseHTTPMiddleware
app.add_middleware(BaseHTTPMiddleware, dispatch=_monitor_middleware)

# ============= 全局异常处理 =============
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log_error("runtime_error", str(exc), f"URL: {request.url.path}", exc)
    return {"detail": f"server error: {str(exc)[:100]}"}

@app.on_event("startup")
async def on_startup():
    log_error("startup", "service started", f"port={API_PORT}")

@app.on_event("shutdown")
async def on_shutdown():
    log_error("shutdown", "service stopped", f"port={API_PORT}")

# 线程异常捕获（守护线程崩溃不中断主进程）
def _thread_excepthook(args):
    log_error("thread_error", str(args.exc_value),
              f"线程 {args.thread.name} (daemon={args.thread.daemon})", args.exc_value)

threading.excepthook = _thread_excepthook

# atexit：进程退出时记录（被kill时也触发）
def _atexit_exit():
    log_error("exit", "进程退出", f"port={API_PORT}")
atexit.register(_atexit_exit)

# ============= 状态初始化 =============
state.config = load_config()
state.stats = load_stats()

# ============= 请求模型 =============
class ConfigUpdate(BaseModel):
    config: Optional[dict] = None
    pomodoro: Optional[dict] = None
    adhd: Optional[dict] = None
    immersion: Optional[dict] = None
    personalize: Optional[dict] = None
    reminder: Optional[dict] = None
    tracking: Optional[dict] = None

class SessionCreate(BaseModel):
    task: Optional[str] = None
    planned_minutes: Optional[int] = None

class WallpaperReq(BaseModel):
    path: Optional[str] = None
    preset: Optional[str] = None

class WizardResult(BaseModel):
    wizard_version: str = "1.0"
    answers: dict
    generated_config: dict

# ============= 静态文件 =============
@app.get("/")
@app.get("/index.html")
async def serve_index():
    html = WEB_DIR / "index.html"
    if html.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(html), media_type="text/html")
    return {"status": "ok", "service": "FlowImmersion v3.0"}

@app.get("/mini.html")
async def serve_mini():
    """极简迷你窗口页面"""
    html = WEB_DIR / "mini.html"
    if html.exists():
        from fastapi.responses import FileResponse
        return FileResponse(str(html), media_type="text/html")
    raise HTTPException(404, "mini.html not found")

# ============= 配置管理 =============
@app.get("/api/config")
async def get_config():
    return state.config

@app.post("/api/config")
async def update_config(u: ConfigUpdate):
    cur = (state.config or DEFAULT_CONFIG).copy()
    if u.config: cur.update(u.config)
    if u.pomodoro: cur.setdefault("pomodoro", {}).update(u.pomodoro)
    if u.adhd: cur.setdefault("adhd", {}).update(u.adhd)
    if u.immersion: cur.setdefault("immersion", {}).update(u.immersion)
    if u.personalize: cur.setdefault("personalize", {}).update(u.personalize)
    if u.reminder: cur.setdefault("reminder", {}).update(u.reminder)
    if u.tracking: cur.setdefault("tracking", {}).update(u.tracking)
    return {"success": True, "config": save_config(cur)}

@app.post("/api/config/wizard")
async def save_wizard(r: WizardResult):
    history = []
    if WIZARD_FILE.exists():
        try:
            history = json.loads(WIZARD_FILE.read_text('utf-8'))
        except:
            history = []
    history.append({"timestamp": datetime.now().isoformat(), **r.dict()})
    WIZARD_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding='utf-8')

    # 把问答配置写入今日任务规划
    gc = r.generated_config
    pomo = gc.get('pomodoro', {})
    focus_dur = pomo.get('focus_duration', 25)
    break_dur = pomo.get('short_break', 5)
    answers = r.answers or {}
    template_label = answers.get('template_label', '自定义模板')

    today = datetime.now().strftime("%Y-%m-%d")
    plan_file = PLANS_DIR / f"{today}.json"
    plan = {"date": today, "steps": [], "created_at": datetime.now().isoformat()}
    if plan_file.exists():
        try:
            plan = json.loads(plan_file.read_text('utf-8'))
        except:
            plan = {"date": today, "steps": []}

    # 移除旧 wizard 任务，追加新的
    wizard_steps = [
        {"description": f"【问答】{template_label}", "minutes": focus_dur, "source": "wizard"},
        {"description": f"【休息】{break_dur}分钟", "minutes": break_dur, "source": "wizard_break"}
    ]
    plan['steps'] = [s for s in plan.get('steps', []) if s.get('source') not in ('wizard', 'wizard_break')]
    plan['steps'].extend(wizard_steps)
    plan['updated_at'] = datetime.now().isoformat()
    plan_file.parent.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

    save_config(r.generated_config)
    return {"success": True, "plan": plan}


@app.get("/api/wizard/history")
async def get_wizard_history(limit: int = 10):
    """返回最近N条 skill Q&A 配置历史"""
    if not WIZARD_FILE.exists():
        return {"history": []}
    try:
        history = json.loads(WIZARD_FILE.read_text('utf-8'))
    except:
        history = []
    history = list(reversed(history))[-limit:]
    return {"history": history}


@app.get("/api/reminder-history")
async def get_reminder_history(limit: int = 10):
    """从 wizard_history 中提取提醒配置历史"""
    if not WIZARD_FILE.exists():
        return {"history": []}
    try:
        history = json.loads(WIZARD_FILE.read_text('utf-8'))
    except:
        history = []
    reminder_history = []
    for h in reversed(history):
        gc = h.get('generated_config', {}).get('reminder', {})
        if gc:
            reminder_history.append({
                "timestamp": h.get('timestamp', ''),
                "template": h.get('generated_config', {}).get('pomodoro', {}).get('focus_duration', 25),
                "interval": gc.get('custom_interval', 30),
                "active_items": gc.get('active_items', []),
                "custom_msg": gc.get('custom_message', ''),
                "custom_reminders": gc.get('custom_reminders', [])
            })
    return {"history": reminder_history[:limit]}


# ============= 番茄钟 =============
@app.post("/api/pomodoro/start")
async def start_pomodoro(data: SessionCreate):
    pomodoro = state.config.get("pomodoro", DEFAULT_CONFIG["pomodoro"])
    duration = data.planned_minutes or pomodoro.get("focus_duration", 25)
    session = create_session(data.task, duration, "focus")

    if state.config.get("immersion", {}).get("hide_icons_on_start", True):
        hide_icons()

    return {"success": True, "session": session}

@app.post("/api/pomodoro/complete")
async def complete_pomodoro():
    if state.current_session:
        state.current_session["actual_minutes"] = state.current_session["planned_minutes"]
        complete_session(True)
        if state.config.get("immersion", {}).get("hide_icons_on_start", True):
            show_icons()
        return {"success": True}
    return {"success": False, "error": "无进行中会话"}

@app.post("/api/pomodoro/abort")
async def abort_pomodoro():
    if state.current_session:
        complete_session(False)
        show_icons()
        return {"success": True}
    return {"success": False, "error": "无进行中会话"}

@app.get("/api/pomodoro/current")
async def get_current():
    return state.current_session or {"status": "no_session"}

@app.post("/api/pomodoro/check-in")
async def check_in(msg: str = ""):
    if state.current_session:
        state.current_session["check_ins"].append({
            "time": datetime.now().isoformat(), "message": msg
        })
    return {"success": True}

@app.post("/api/pomodoro/distraction")
async def record_distraction():
    if state.current_session:
        state.current_session["distractions"] += 1
    return {"success": True}

# ============= ADHD陪伴 =============
@app.get("/api/adhd/status")
async def adhd_status():
    from core.adhd_companion import ADHDCompanion
    c = ADHDCompanion()
    return c.get_status()

@app.get("/api/adhd/dopamine-menu")
async def dopamine_menu():
    from core.adhd_companion import DOPAMINE_MENU
    return {"options": DOPAMINE_MENU}

@app.post("/api/adhd/dopamine-reset")
async def dopamine_reset(option_id: str = ""):
    from core.adhd_companion import ADHDCompanion, DOPAMINE_MENU
    c = ADHDCompanion()
    option = next((o for o in DOPAMINE_MENU if o['id'] == option_id), None)
    if not option:
        raise HTTPException(400, "未知选项")
    if state.current_session:
        state.current_session["dopamine_breaks"].append({
            "time": datetime.now().isoformat(), "option_id": option_id
        })
    return {"success": True, "option": option}

@app.get("/api/adhd/emergency-reset")
async def emergency_protocol():
    from core.adhd_companion import EMERGENCY_RESET_PROTOCOL
    return {"protocol": EMERGENCY_RESET_PROTOCOL}

ENERGY_LOG_FILE = DATA_DIR / "energy.json"

@app.post("/api/energy/log")
async def log_energy(req: Request):
    """记录能量活动到 energy.json"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")
    ENERGY_LOG_FILE.parent.mkdir(exist_ok=True)
    logs = []
    if ENERGY_LOG_FILE.exists():
        try: logs = json.loads(ENERGY_LOG_FILE.read_text('utf-8'))
        except: pass
    logs.append(body)
    ENERGY_LOG_FILE.write_text(json.dumps(logs, ensure_ascii=False, indent=2), encoding='utf-8')
    return {"success": True}

@app.get("/api/energy/stats")
async def get_energy_stats():
    """获取能量活动统计"""
    if not ENERGY_LOG_FILE.exists():
        return {"total": 0, "by_type": {}}
    try:
        logs = json.loads(ENERGY_LOG_FILE.read_text('utf-8'))
        by_type = {}
        for log in logs:
            t = log.get('type', 'unknown')
            by_type[t] = by_type.get(t, 0) + 1
        return {"total": len(logs), "by_type": by_type, "logs": logs[-20:]}
    except:
        return {"total": 0, "by_type": {}}

@app.post("/api/adhd/emergency-reset")
async def apply_emergency():
    from core.adhd_companion import ADHDCompanion, EMERGENCY_RESET_PROTOCOL
    return {"success": True, "protocol": EMERGENCY_RESET_PROTOCOL}

@app.get("/api/adhd/tips")
async def get_tips():
    from core.adhd_companion import ADHDCompanion
    c = ADHDCompanion()
    return c.get_tips()

@app.post("/api/adhd/micro-step")
async def add_micro_step(step: str = ""):
    from core.adhd_companion import ADHDCompanion
    c = ADHDCompanion()
    if state.current_session:
        state.current_session["micro_steps"].append({
            "text": step, "completed": False, "added_at": datetime.now().isoformat()
        })
    return {"success": True}

@app.get("/api/adhd/autopsy")
async def get_autopsy():
    from core.adhd_companion import ADHDCompanion
    c = ADHDCompanion()
    return c.start_autopsy()

@app.post("/api/adhd/autopsy")
async def submit_autopsy(helped: str = "", didnt: str = "", next_time: str = ""):
    if state.current_session:
        state.current_session["autopsy"] = {
            "helped": helped, "didnt_work": didnt, "next_time": next_time
        }
    return {"success": True}

# ============= 桌面控制 =============
@app.get("/api/desktop/status")
async def desktop_status():
    return {
        "icons_visible": is_icons_visible(),
        "wallpaper": get_current_wallpaper(),
        "pywin32": PYWIN32_AVAILABLE
    }

@app.post("/api/window/topmost")
async def toggle_window_topmost():
    """将计时器窗口置顶/取消置顶"""
    if not PYWIN32_AVAILABLE:
        raise HTTPException(500, "pywin32 不可用")

    global _topmost_enabled

    target = 0
    # 优先用EnumWindows找到浏览器窗口（按标题关键词）
    def enum_cb(h, _):
        nonlocal target
        try:
            if not win32gui.IsWindowVisible(h): return True
            title = win32gui.GetWindowText(h)
            if not title: return True
            if any(c in title for c in ("FlowImmersion","FI","心流","番茄","localhost")):
                target = h; return False
            cls = win32gui.GetClassName(h)
            if cls in ("Chrome_WidgetWin_1","Chrome_WidgetWin_0"):
                target = h; return False
        except: pass
        return True
    win32gui.EnumWindows(enum_cb, None)

    # 如果找不到，用前景窗口（用户操作置顶时光标在浏览器上）
    if not target:
        fg_win = win32gui.GetForegroundWindow()
        try:
            if win32gui.IsWindowVisible(fg_win):
                fg_cls = win32gui.GetClassName(fg_win)
                if fg_cls not in {"ConsoleWindowClass","PuTTY","mintty","Cygwin"}:
                    target = fg_win
        except: pass

    if not target:
        raise HTTPException(404, "请将光标移到浏览器计时器窗口后重试")

    try:
        exstyle = win32gui.GetWindowLong(target, win32con.GWL_EXSTYLE)
        is_top = exstyle & 0x00000008
        if is_top:
            win32gui.SetWindowLong(target, win32con.GWL_EXSTYLE, exstyle & ~0x00000008)
            win32gui.SetWindowPos(target, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
            _topmost_enabled = False
            return {"success": True, "topmost": False}
        else:
            win32gui.SetWindowLong(target, win32con.GWL_EXSTYLE, exstyle | 0x00000008)
            win32gui.SetWindowPos(target, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER)
            _topmost_enabled = True
            return {"success": True, "topmost": True}
    except Exception as e:
        raise HTTPException(500, f"置顶操作失败: {e}")


@app.post("/api/window/topmost/guardian")
async def control_topmost_guardian(enabled: bool = True):
    """启用/禁用置顶守护线程（不影响当前窗口状态）"""
    global _topmost_enabled
    _topmost_enabled = enabled
    return {"success": True, "topmost_enabled": enabled}


@app.get("/api/window/topmost/status")
async def get_topmost_status():
    return {"topmost_enabled": _topmost_enabled, "main_pid": _main_window_pid}


@app.post("/api/window/move")
async def move_window(mode: str = "compact"):
    """移动窗口: 'centered'=居中不动 / 'mini'=顶部居中(320x52) / 'compact'=右上角(400x300) / 'expanded'=居中大窗(80%) / 'top-left'=左上角适中窗口"""
    if not PYWIN32_AVAILABLE:
        raise HTTPException(500, "pywin32 不可用")

    target = 0
    fg_win = win32gui.GetForegroundWindow()

    # 优先：前景窗口
    if fg_win and win32gui.IsWindowVisible(fg_win):
        fg_cls = win32gui.GetClassName(fg_win)
        if fg_cls not in {"Shell_TrayWnd","Progman","DV2ControlHost","Windows.UI.Core",
                           "WorkerW","ApplicationFrameWindow","MsgrIMEWindow","SysShadow",
                           "Button","Static","ToolTips","ConsoleWindowClass"}:
            target = fg_win

    # 其次：用EnumWindows搜索浏览器特征窗口
    if not target:
        def enum_cb(h, _):
            nonlocal target
            try:
                if not win32gui.IsWindowVisible(h): return True
                title = win32gui.GetWindowText(h)
                if not title: return True
                if any(c in title for c in ("FlowImmersion","FI","心流","番茄","localhost")):
                    target = h; return False
                cls = win32gui.GetClassName(h)
                if cls in ("Chrome_WidgetWin_1","Chrome_WidgetWin_0"):
                    target = h; return False
            except: pass
            return True
        win32gui.EnumWindows(enum_cb, None)

    if not target:
        raise HTTPException(404, "未找到浏览器窗口，请确认窗口处于活动状态")

    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)

    if mode == "centered":
        rect = win32gui.GetWindowRect(target)
        w, h = rect[2]-rect[0], rect[3]-rect[1]
        x, y = (sw - w) // 2, (sh - h) // 2
    elif mode == "mini":
        # 迷你模式：固定85像素高度，顶部居中
        x, y, w, h = (sw - 320) // 2, 28, 320, 85
    elif mode == "compact":
        x, y, w, h = sw - 420, 20, 400, 300
    elif mode == "top-left":
        x, y, w, h = 20, 40, int(sw * 0.65), int(sh * 0.75)
    else:  # expanded: 居中80%窗口
        w, h = int(sw * 0.8), int(sh * 0.85)
        x, y = (sw - w) // 2, (sh - h) // 2

    try:
        win32gui.SetWindowPos(target, win32con.HWND_TOPMOST, x, y, w, h,
            win32con.SWP_SHOWWINDOW)
        return {"success": True, "mode": mode, "x": x, "y": y, "w": w, "h": h}
    except Exception as e:
        raise HTTPException(500, f"移动失败: {e}")


@app.post("/api/immersive/launch")
async def launch_immersive():
    """重新启动沉浸窗口（--app=无边框模式）"""
    threading.Thread(target=open_immersive_window, daemon=True).start()
    return {"success": True, "message": "沉浸窗口启动中..."}


# ============= 任务规划 API =============


class StepItem(BaseModel):
    description: str
    minutes: int


@app.post("/api/planning/save")
async def save_plan(req: Request):
    """保存今日计划步骤（body为步骤数组）"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    today = datetime.now().strftime("%Y-%m-%d")
    plan_file = PLANS_DIR / f"{today}.json"
    valid_steps = []
    for s in body:
        if isinstance(s, dict) and 'description' in s and 'minutes' in s:
            valid_steps.append({
                "description": str(s['description']),
                "minutes": int(s['minutes'])
            })
    plan = {
        "date": today,
        "steps": valid_steps,
        "created_at": datetime.now().isoformat()
    }
    with open(plan_file, 'w', encoding='utf-8') as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    return {"success": True, "plan": plan}


@app.get("/api/planning/today")
async def get_today_plan():
    """获取今日计划"""
    today = datetime.now().strftime("%Y-%m-%d")
    plan_file = PLANS_DIR / f"{today}.json"
    if plan_file.exists():
        try:
            with open(plan_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {"date": today, "steps": []}


# ============= 提醒 API =============
# 默认健康提醒模板
DEFAULT_REMINDER_TEMPLATES = [
    {"id": "water", "label": "喝水", "message": "起身倒杯水，小口慢饮，给身体补充水分", "interval_minutes": 20},
    {"id": "eye", "label": "护眼", "message": "看看窗外远处，让眼睛休息20秒", "interval_minutes": 20},
    {"id": "stretch", "label": "拉伸", "message": "站起来伸展双臂，活动颈椎和腰部", "interval_minutes": 30},
    {"id": "posture", "label": "姿势", "message": "检查坐姿：背部挺直，肩膀放松", "interval_minutes": 25},
    {"id": "breathe", "label": "深呼吸", "message": "深呼吸3次：吸气4秒，屏住4秒，呼气6秒", "interval_minutes": 15},
]

# 专注模板定义
FOCUS_TEMPLATES = [
    {"id": "focus",    "label": "专注模板",   "focus_minutes": 40, "break_minutes": 5,  "remind_interval": 20, "remind_message": "喝水+伸展"},
    {"id": "short",   "label": "短任务模板", "focus_minutes": 25, "break_minutes": 3,  "remind_interval": 15, "remind_message": "眨眼+喝水"},
    {"id": "creative","label": "创意模板",   "focus_minutes": 90, "break_minutes": 10, "remind_interval": 30, "remind_message": "起身活动"},
    {"id": "study",   "label": "学习模板",   "focus_minutes": 50, "break_minutes": 10, "remind_interval": 25, "remind_message": "调整坐姿+喝水"},
]


@app.get("/api/reminders")
async def get_reminders():
    """获取当前提醒设置"""
    if REMINDERS_FILE.exists():
        try:
            with open(REMINDERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "enabled": False,
        "items": DEFAULT_REMINDER_TEMPLATES.copy(),
        "custom_interval": 30,
        "active_items": ["water", "eye"]
    }


@app.post("/api/reminders")
async def save_reminders(req: Request):
    """保存提醒设置"""
    try:
        body = await req.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")
    with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(body, f, ensure_ascii=False, indent=2)
    return {"success": True}


@app.get("/api/reminders/templates")
async def get_reminder_templates():
    """获取默认提醒模板"""
    return {"templates": DEFAULT_REMINDER_TEMPLATES}


@app.get("/api/focus-templates")
async def get_focus_templates():
    """获取专注模板列表"""
    return {"templates": FOCUS_TEMPLATES}


# ============= 背景音乐 API =============
MUSIC_DIR = SKILL_DIR / "music"


@app.get("/api/music/list")
async def list_music():
    """列出音乐目录中的音频文件（优先使用配置的自定义目录）"""
    music_dir = state.config.get("immersion", {}).get("music_dir", "")
    if music_dir:
        from pathlib import Path
        user_dir = Path(music_dir)
    else:
        user_dir = MUSIC_DIR
    if not user_dir.exists():
        user_dir.mkdir(exist_ok=True)
        return {"files": [], "built_in": get_built_in_music()}
    files = []
    for ext in ('*.mp3', '*.wav', '*.ogg', '*.m4a', '*.aac'):
        for f in user_dir.glob(ext):
            files.append({"name": f.stem, "file": f"/music/{f.name}"})
    return {"files": files, "built_in": get_built_in_music()}


def get_built_in_music():
    """内置生成音（不依赖外部文件）"""
    return [
        {"id": "sine_ambient", "name": "柔缓白噪音", "type": "generated"},
        {"id": "pink_ambient", "name": "粉噪音氛围", "type": "generated"},
        {"id": "rain", "name": "雨声", "type": "generated"},
    ]


@app.get("/music/{filename}")
async def serve_music(filename: str):
    """提供音乐文件（优先从自定义目录，其次skill目录）"""
    import mimetypes
    music_dir = state.config.get("immersion", {}).get("music_dir", "")
    if music_dir:
        from pathlib import Path
        path = Path(music_dir) / filename
    else:
        path = MUSIC_DIR / filename
    if not path.exists():
        raise HTTPException(404, "File not found")
    mt, _ = mimetypes.guess_type(str(path))
    from starlette.responses import FileResponse
    return FileResponse(str(path), media_type=mt or "audio/mpeg")


@app.get("/api/config/music-dir")
async def get_music_dir():
    """获取音乐目录路径"""
    music_dir = state.config.get("immersion", {}).get("music_dir", "")
    return {"path": music_dir, "exists": bool(music_dir)}


@app.post("/api/config/music-dir")
async def set_music_dir(req: Request):
    """保存音乐目录路径"""
    body = await req.json()
    path = body.get("path", "")
    cur = (state.config or DEFAULT_CONFIG).copy()
    cur.setdefault("immersion", {}).update({"music_dir": path})
    save_config(cur)
    return {"success": True, "path": path}


@app.post("/api/desktop/icons/hide")
async def api_hide_icons():
    ok = hide_icons()
    if not ok:
        raise HTTPException(500, "未找到桌面图标窗口")
    return {"success": True, "message": "桌面图标已隐藏"}

@app.post("/api/desktop/icons/show")
async def api_show_icons():
    ok = show_icons()
    if not ok:
        raise HTTPException(500, "未找到桌面图标窗口")
    return {"success": True, "message": "桌面图标已显示"}

@app.post("/api/desktop/icons/toggle")
async def api_toggle_icons():
    if is_icons_visible():
        ok = hide_icons()
    else:
        ok = show_icons()
    return {"success": True, "visible": is_icons_visible()}

@app.post("/api/desktop/wallpaper")
async def set_wallpaper(req: WallpaperReq):
    if req.preset:
        ok, result = set_wallpaper_by_preset(req.preset)
    else:
        ok, result = set_wallpaper_by_path(req.path)
    if not ok:
        raise HTTPException(400, result)
    return {"success": True, "path": result}

@app.post("/api/desktop/wallpaper/restore")
async def restore_wallpaper():
    """恢复原始桌面壁纸（同时恢复桌面图标可见性）"""
    global _original_wallpaper
    if _original_wallpaper:
        ok, result = set_wallpaper_by_path(_original_wallpaper)
        if not ok:
            raise HTTPException(400, f"恢复壁纸失败: {result}")
    else:
        _original_wallpaper = get_current_wallpaper()
    # 恢复桌面图标
    if is_icons_visible():
        pass  # 图标已在显示状态，无需操作
    else:
        show_icons()
    return {"success": True, "message": "已恢复默认壁纸和图标"}

@app.post("/api/config/reset")
async def reset_config():
    """清空全部配置数据（恢复默认），保留心流历史数据（sessions/ 和 stats.json）"""
    try:
        # 1. config.json → 默认
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
        state.config = DEFAULT_CONFIG.copy()
        # 2. energy.json → 默认
        with open(ENERGY_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_ENERGY, f, ensure_ascii=False, indent=2)
        # 3. reminders.json → 默认
        with open(REMINDERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_REMINDERS, f, ensure_ascii=False, indent=2)
        # 4. plans/ 目录 → 清空（保留目录本身）
        if PLANS_DIR.exists():
            for pf in PLANS_DIR.glob("*.json"):
                pf.unlink()
        return {"success": True, "message": "已清空全部配置（个性化/提醒/专注/能量/任务），心流历史已保留"}
    except Exception as e:
        raise HTTPException(500, f"重置配置失败: {e}")


# ============= 通用数据存储（双模式：localStorage + FastAPI JSON） =============
@app.get("/api/data/{key}")
async def get_data(key: str):
    """获取指定key的存储数据"""
    data_file = DATA_DIR / f"{key}.json"
    if data_file.exists():
        try:
            with open(data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}

@app.post("/api/data/{key}")
async def save_data(key: str, req: Request):
    """保存指定key的存储数据"""
    try:
        body = await req.json()
        data_file = DATA_DIR / f"{key}.json"
        with open(data_file, 'w', encoding='utf-8') as f:
            json.dump(body, f, ensure_ascii=False, indent=2)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/desktop/wallpaper/presets")
async def wallpaper_presets():
    return {
        "presets": [
            {"id": k, "name": k.capitalize(), "color": '#{:02x}{:02x}{:02x}'.format(*v)}
            for k, v in WALLPAPER_PRESETS.items()
        ]
    }

@app.post("/api/shortcut/create")
async def create_shortcut():
    """首次访问时创建桌面快捷方式 + 启动脚本"""
    s1_ok, s1_r = _create_desktop_shortcut()
    s2_ok, s2_r = _create_startup_bat()
    results = {"shortcut": s1_r, "bat": s2_r}
    if not (s1_ok or s2_ok):
        raise HTTPException(500, "创建失败")
    return {"success": True, "results": results}

# ============= 迷你沉浸模式 =============
@app.post("/api/mini-mode/launch")
async def launch_mini_window():
    """启动极简迷你进度条窗口（320x80px，顶部居中）"""
    import threading
    def _launch():
        import subprocess, ctypes, os, tempfile

        url = f"http://localhost:{API_PORT}/mini.html"
        tmp = os.path.join(tempfile.gettempdir(), "flow_mini_ud")
        os.makedirs(tmp, exist_ok=True)

        sw = ctypes.windll.user32.GetSystemMetrics(0)
        ww, wh = 320, 52
        wx = (sw - ww) // 2
        wy = 28

        # 查找浏览器：Chrome > QQBrowser > Edge
        candidates = [
            os.path.join(os.environ.get('LOCALAPPDATA', ''), r"Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            os.path.join(os.environ.get('PROGRAMFILES', ''), r"Tencent\QQBrowser\QQBrowser.exe"),
            os.path.join(os.environ.get('PROGRAMFILES(X86)', ''), r"Tencent\QQBrowser\QQBrowser.exe"),
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        ]
        exe = next((p for p in candidates if os.path.exists(p)), None)
        if not exe:
            print("[FlowImmersion] 未找到可用浏览器，跳过迷你窗口启动")
            return

        ps = f'''
$exe='{exe}'
$url='{url}'
$ud='{tmp}'
$hx={wx};$hy={wy};$hw={ww};$hh={wh}
# 禁用 captive portal
$capPath='HKCU:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Internet Settings\\CaptivePortal'
if(-not (Test-Path $capPath)){{New-Item -Path $capPath -Force | Out-Null}}
Set-ItemProperty -Path $capPath -Name 'DisableCaptivePortalDetection' -Value 1 -Type DWord -Force
Add-Type @'
using System;using System.Runtime.InteropServices;
class W{{
  [DllImport("user32.dll")]public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")]public static extern int GetWindowThreadProcessId(IntPtr h,out int pid);
  [DllImport("user32.dll")]public static extern int GetWindowLong(IntPtr h,int i);
  [DllImport("user32.dll")]public static extern int SetWindowLong(IntPtr h,int i,int v);
  [DllImport("user32.dll")]public static extern bool SetWindowPos(IntPtr h,IntPtr a,int x,int y,int cx,int cy,uint f);
  [DllImport("user32.dll")]public static extern bool MoveWindow(IntPtr h,int x,int y,int cx,int cy,bool r);
}}
'@
$args=@('--app='+$url,'--window-size='+$hw+','+$hh,'--no-first-run','--disable-extensions','--disable-infobars','--disable-gpu','--no-default-browser-check','--disable-background-networking','--disable-sync','--user-data-dir='+$ud)
$p=Start-Process -FilePath $exe -ArgumentList $args -PassThru -WindowStyle Hidden
Start-Sleep 3
$h=[IntPtr]::Zero
if($p -and -not $p.HasExited){{$h=$p.MainWindowHandle}}
if($h -eq [IntPtr]::Zero){{
    # 找不到句柄，通过进程枚举找Chrome窗口
    $chrome=$p.Id
    Add-Type @'
using System;using System.Collections.Generic;using System.Runtime.InteropServices;
class FW{{
  [DllImport("user32.dll")]public static extern IntPtr FindWindow(string cls,string title);
  [DllImport("user32.dll")]public static extern IntPtr FindWindowEx(IntPtr p,IntPtr c,string cls,string title);
  [DllImport("user32.dll")]public static extern bool EnumWindows(FW+Proc f,IntPtr d);
  [DllImport("user32.dll")]public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll")]public static extern int GetWindowThreadProcessId(IntPtr h,out int pid);
  public delegate bool Proc(IntPtr h,IntPtr d);
  public static List<IntPtr> GetAllWindows(){{
    var r=new List<IntPtr>();
    EnumWindows((h,d)=>{{r.Add(h);return true;}},IntPtr.Zero);
    return r;
  }}
}}
'@
    $chrome=$p.Id;$target=[IntPtr]::Zero
    foreach($wh in [FW]::GetAllWindows()){{
        $wpid=0;[FW]::GetWindowThreadProcessId($wh,[ref]$wpid)|Out-Null
        if($wpid -eq $chrome -and [FW]::IsWindowVisible($wh)){{$target=$wh;break}}
    }}
    $h=$target
}}
if($h -ne [IntPtr]::Zero){{
    $G=-16;$s=[W]::GetWindowLong($h,$G)
    [W]::SetWindowLong($h,$G,$s -band -bnot 0x00C00000)
    # 保留 WS_SIZEBOX(0x00040000) = 可拖拽边框
    $GE=-20;$se=[W]::GetWindowLong($h,$GE)
    [W]::SetWindowLong($h,$GE,$se -bor 0x00000008)
    $T=[IntPtr]::Zero
    [W]::SetWindowPos($h,$T,$hx,$hy,$hw,$hh,0x0001 -bor 0x0002)
    # 守护循环：每3秒重新置顶（拖拽窗口后快速恢复）
    while($p -and -not $p.HasExited){{
        Start-Sleep 3
        if($p.HasExited){{break}}
        $nh=[W]::GetForegroundWindow()
        if($nh -eq [IntPtr]::Zero){{
            # 重新找窗口
            $chrome=$p.Id;$target=[IntPtr]::Zero
            foreach($wh in [FW]::GetAllWindows()){{
                $wpid=0;[FW]::GetWindowThreadProcessId($wh,[ref]$wpid)|Out-Null
                if($wpid -eq $chrome -and [FW]::IsWindowVisible($wh)){{$target=$wh;break}}
            }}
            $nh=$target
        }}
        if($nh -ne [IntPtr]::Zero){{
            $GE2=-20;$se2=[W]::GetWindowLong($nh,$GE2)
            [W]::SetWindowLong($nh,$GE2,$se2 -bor 0x00000008)
            [W]::SetWindowPos($nh,[IntPtr]::Zero,$hx,$hy,$hw,$hh,0x0001)
        }}
    }}
}}
'''
        try:
            subprocess.Popen(
                ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', ps],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=0x08000000  # CREATE_NO_WINDOW
            )
        except:
            pass

    threading.Thread(target=_launch, daemon=True).start()
    return {"success": True, "message": "迷你窗口已启动"}


# ============= 数据统计 =============
@app.get("/api/stats")
async def get_stats():
    stats = load_stats()
    today = datetime.now().strftime("%Y-%m-%d")
    daily = stats.get("daily_stats", {}).get(today, {"sessions": 0, "focus_minutes": 0, "breaks": 0, "distractions": 0})
    today_sessions = daily.get("sessions", 0)
    today_distractions = daily.get("distractions", 0)
    focus_score = 100
    if today_sessions > 0 and today_distractions > 0:
        focus_score = max(0, 100 - today_distractions * 5)

    return {
        **stats,
        "today": daily,
        "adhd_focus_score": focus_score,
        "streak_days": stats.get("patterns", {}).get("streak_days", 0),
        "completion_rate": (
            daily.get("sessions", 0) / max(1, daily.get("focus_minutes", 1) // 25)
        )
    }

@app.get("/api/stats/daily")
async def get_daily(date: Optional[str] = None):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    stats = load_stats()
    daily = stats.get("daily_stats", {}).get(date, {"sessions": 0, "focus_minutes": 0, "breaks": 0, "distractions": 0})
    daily["date"] = date
    return daily

@app.get("/api/sessions")
async def get_sessions(limit: int = 10):
    sessions = []
    for f in sorted(SESSIONS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            sessions.append(json.loads(f.read_text('utf-8')))
        except:
            pass
    return sessions

# ============= 自修复系统 API =============

@app.get("/api/self-repair/status")
async def self_repair_status():
    """获取当前自修复系统状态：错误统计+修复历史+待修复队列"""
    return {
        "error_stats": {
            "total": len(_load_error_logs()),
            "fixes": len(_load_auto_fixes()),
            "backups": sum(1 for _ in BACKUP_DIR.rglob("*.bak_*")) if BACKUP_DIR.exists() else 0,
        },
        "recent_fixes": _load_auto_fixes()[-5:],
        "repair_queue": [q for q in _load_repair_queue() if q.get("status") == "pending"],
    }

@app.get("/api/self-repair/queue")
async def get_repair_queue():
    """获取LLM修复队列（等待大模型处理的错误）"""
    queue = _load_repair_queue()
    return {"queue": queue, "pending_count": sum(1 for q in queue if q.get("status") == "pending")}

@app.post("/api/self-repair/queue/{item_id}/resolve")
async def resolve_queue_item(item_id: str):
    """标记队列项为已修复（由LLM修复后调用）"""
    queue = _load_repair_queue()
    for q in queue:
        if q.get("id") == item_id:
            q["status"] = "resolved"
            q["resolved_at"] = datetime.now().isoformat()
            _save_repair_queue(queue)
            return {"success": True}
    return {"success": False, "error": "not found"}

@app.post("/api/self-repair/run")
async def trigger_self_repair():
    """手动触发一次全量自修复"""
    try:
        report = run_self_repair()
        return {"success": True, **report}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ============= 启动 =============
import uvicorn, time

def _find_browser():
    """查找可用的浏览器，按Chrome > QQBrowser > Edge > Playwright顺序
    所有找到的浏览器均使用 --app= 模式打开（无地址栏/无工具栏/无标题栏）
    """
    candidates = [
        # Playwright Chromium（优先级1，确保系统有可用浏览器）
        Path(os.environ.get('LOCALAPPDATA', '')) / r"ms-playwright\chromium-1219\chrome-win64\chrome.exe",
        Path(os.environ.get('LOCALAPPDATA', '')) / r"ms-playwright\chromium-1217\chrome-win64\chrome.exe",
        Path(os.environ.get('LOCALAPPDATA', '')) / r"ms-playwright\chromium-1208\chrome-win64\chrome.exe",
        # Chrome（优先级2）
        Path(os.environ.get('LOCALAPPDATA', '')) / r"Google\Chrome\Application\chrome.exe",
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        # QQBrowser（优先级3，支持Chromium内核的--app=）
        Path(os.environ.get('PROGRAMFILES', '')) / r"Tencent\QQBrowser\QQBrowser.exe",
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / r"Tencent\QQBrowser\QQBrowser.exe",
        Path(os.environ.get('LOCALAPPDATA', '')) / r"Tencent\QQBrowser\QQBrowser.exe",
        # Edge（优先级4兜底）
        Path(os.environ.get('PROGRAMFILES', '')) / r"Microsoft\Edge\Application\msedge.exe",
        Path(os.environ.get('PROGRAMFILES(X86)', '')) / r"Microsoft\Edge\Application\msedge.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return None


def _app_mode_url(exe_path):
    """判断使用 --app= 模式（无地址栏/无工具栏）
    支持：Chrome、QQBrowser（Chromium内核）、Edge
    """
    if exe_path:
        lower = exe_path.lower()
        if "chrome" in lower and "playwright" not in lower:
            return True
        if "qqbrowser" in lower:
            return True
        if "msedge" in lower:
            return True
    return False


def _launch_chrome_app(exe_path, url, wx, wy, ww, wh):
    """用 Python subprocess 直接启动 Chrome --app 模式（绕过 PowerShell 脚本问题）"""
    if not exe_path:
        return None
    tmp = os.environ.get('TEMP', '/tmp')
    ud = Path(tmp) / "flow_imm_usr"
    ud.mkdir(exist_ok=True)
    args = [
        exe_path,
        f'--app={url}',
        f'--window-size={ww},{wh}',
        '--always-on-top',
        '--no-first-run',
        '--disable-extensions',
        '--disable-infobars',
        '--disable-sync',
        '--disable-gpu',
        '--disable-gpu-compositing',
        '--disable-background-networking',
        '--no-default-browser-check',
        '--disable-translate',
        '--disable-features=ChromeUti,DownloadBubble,DownloadResumption',
        '--disable-browser-side-window',
        '--disable-default-apps',
        f'--user-data-dir={ud}',
    ]
    # CREATE_NO_WINDOW = 0x08000000
    p = subprocess.Popen(args, creationflags=0x08000000)
    return p.pid


def _style_window(hwnd, x, y, w, h):
    """用 win32gui 去掉标题栏 + 置顶 + 移动"""
    if not PYWIN32_AVAILABLE:
        return
    import win32gui, win32con
    GWL_STYLE = -16
    WS_CAPTION = 0x00C00000
    WS_SIZEBOX = 0x00040000
    try:
        style = win32gui.GetWindowLong(hwnd, GWL_STYLE)
        win32gui.SetWindowLong(hwnd, GWL_STYLE, style & ~WS_CAPTION | WS_SIZEBOX)
    except:
        pass
    try:
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, x, y, w, h, 0x0001 | 0x0002)
    except:
        pass


def _detect_available_url():
    """检测远程地址是否可用，返回可用URL"""
    import urllib.request
    remote_url = "https://gpt.cntaxs.com/stustar-api/zhx/flow-Im.html"
    try:
        req = urllib.request.Request(remote_url, method='HEAD')
        resp = urllib.request.urlopen(req, timeout=3)
        if resp.status == 200:
            print(f"[FlowImmersion] 远程地址可用: {remote_url}")
            return remote_url
    except Exception as e:
        print(f"[FlowImmersion] 远程地址不可用: {e}")
    fallback = f"http://localhost:{API_PORT}/"
    print(f"[FlowImmersion] 使用本地地址: {fallback}")
    return fallback

def open_immersive_window():
    """用 App 模式打开沉浸窗口：无地址栏/无标签/无菜单/无标题栏"""
    time.sleep(1.5)
    url = _detect_available_url()
    exe_path = _find_browser()

    sw = ctypes.windll.user32.GetSystemMetrics(0)
    sh = ctypes.windll.user32.GetSystemMetrics(1)
    ww, wh = 360, 500
    wx = (sw - ww) // 2
    wy = (sh - wh) // 2

    def launch():
        if not exe_path:
            print(f"[FlowImmersion] 未找到可用浏览器")
            return

        pid = _launch_chrome_app(exe_path, url, wx, wy, ww, wh)
        if not pid:
            print(f"[FlowImmersion] 浏览器启动失败")
            return

        print(f"[FlowImmersion] 浏览器已启动 (PID {pid})，等待窗口...")

        # 等待窗口出现，然后美化
        import win32gui, win32con
        hwnd = None
        for _ in range(20):  # 最多等10秒
            time.sleep(0.5)
            try:
                def enum(h, _):
                    nonlocal hwnd
                    try:
                        if not win32gui.IsWindowVisible(h):
                            return True
                        pid_now = win32gui.GetWindowThreadProcessId(h)
                        # FindWindow 的结果需要对比
                        t = win32gui.GetWindowText(h)
                        cls = win32gui.GetClassName(h)
                        if cls in ('Chrome_WidgetWin_1', 'Chrome_WidgetWin_0', 'OpWindow'):
                            hwnd = h; return False
                        if t and ('FlowImmersion' in t or 'localhost' in t):
                            hwnd = h; return False
                    except:
                        pass
                    return True
                hwnd = None
                win32gui.EnumWindows(enum, None)
                if hwnd:
                    break
            except Exception:
                pass

        if hwnd:
            print(f"[FlowImmersion] 找到窗口 Hwnd={hwnd}，美化中...")
            _style_window(hwnd, wx, wy, ww, wh)
            global _main_window_pid
            _main_window_pid = pid
            threading.Thread(target=_topmost_guardian, args=(pid, wx, wy, ww, wh), daemon=True).start()
        else:
            print(f"[FlowImmersion] 窗口未找到，但进程已启动 (PID {pid})")

    threading.Thread(target=launch, daemon=True).start()

# ============= 快照自追踪注册 =============
WORKBUDDY_SNAP = Path(os.path.expanduser('~/.workbuddy/hermes-agent/project-snapshot/flow-immersion.json'))
SNAPSHOT_LOCAL = SKILL_DIR / '.snapshot.json'

PY_PATTERNS = ('def ', 'async def ', 'class ')
JS_PATTERNS = ('function ', 'const ', 'let ', 'var ')

def _build_snapshot() -> dict:
    snap = {
        'version': '3.2.5',
        'basePath': str(SKILL_DIR),
        'runningInstance': {
            'pid': os.getpid(),
            'port': API_PORT,
            'processPath': sys.executable,
            'cwd': str(SKILL_DIR),
            'startedAt': datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
        },
        'fileSizes': {},
        'index': {},
        'updated': datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
    }
    for ext, patterns in [('*.py', PY_PATTERNS), ('*.html', JS_PATTERNS)]:
        for f in SKILL_DIR.rglob(ext):
            rel = f.relative_to(SKILL_DIR).as_posix()
            try:
                text = f.read_text(encoding='utf-8', errors='ignore')
            except:
                continue
            lines = text.split('\n')
            snap['fileSizes'][rel] = len(lines)
            idx = {}
            for i, line in enumerate(lines, 1):
                for p in patterns:
                    if line.strip().startswith(p):
                        name = line.strip().split('(')[0].replace(p, '').strip()
                        if name and len(name) < 60:
                            idx[name] = i
                            break
            if idx:
                snap['index'][rel] = idx
    return snap

def _register_snapshot():
    """将当前实例信息写入两份快照"""
    snap = _build_snapshot()
    snap_str = json.dumps(snap, ensure_ascii=False, indent=2)
    # 写 skill 内快照
    try:
        SNAPSHOT_LOCAL.write_text(snap_str, encoding='utf-8')
    except:
        pass
    # 同步写 workbuddy 快照
    try:
        WORKBUDDY_SNAP.parent.mkdir(parents=True, exist_ok=True)
        WORKBUDDY_SNAP.write_text(snap_str, encoding='utf-8')
    except:
        pass
    return snap

# ============= 静态文件挂载（必须放在所有路由之后） =============
# 让 style.css / app.js / flow-Im.html 等前端资源可通过相对路径正常加载
try:
    app.mount("/", StaticFiles(directory=str(WEB_DIR), html=True), name="web")
    print(f"[FlowImmersion] 静态文件已挂载: {WEB_DIR}")
except Exception as e:
    print(f"[FlowImmersion] 静态文件挂载失败（API仍可用）: {e}")

# ============= 启动 =============
if __name__ == "__main__":
    # 启动时注册快照
    _register_snapshot()

    # === 启动自检：分析历史错误 + 自动修复 ===
    try:
        report = run_self_repair()
    except Exception as e:
        report = {"checks": [], "stats": {"total": 0, "unresolved": 0, "by_type": {}}, "total_fixed": 0, "recent_fixes": []}

    print("=" * 50)
    print("  FlowImmersion v3.2.5")
    print("  Pomodoro + ADHD Companion + Desktop Control")
    print("=" * 50)
    print(f"  Local:    http://localhost:{API_PORT}")
    print(f"  Remote:   https://gpt.cntaxs.com/stustar-api/zhx/flow-Im.html")
    print(f"  pywin32:  {'available' if PYWIN32_AVAILABLE else 'not installed'}")
    print()
    _print_startup_report(report)

    # 启动后台定期自修复（每30分钟扫描一次错误日志）
    def _periodic_self_repair():
        while True:
            time.sleep(1800)  # 30 minutes
            try:
                r = run_self_repair()
                if r.get("total_fixed", 0) > 0:
                    print(f"  [PERIODIC CHECK] Fixed {r['total_fixed']} issue(s)")
            except Exception:
                pass

    threading.Thread(target=_periodic_self_repair, daemon=True, name="self_repair").start()

    # 启动时弹沉浸窗口（错误不中断主流程）
    try:
        threading.Thread(target=open_immersive_window, daemon=True).start()
    except Exception as e:
        log_error("startup", str(e), "open_immersive_window")

    # 捕获意外退出
    try:
        uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="warning")
    except KeyboardInterrupt:
        log_error("shutdown", "用户Ctrl+C中断", f"port={API_PORT}")
        print("\n  服务已关闭 (Ctrl+C)")
    except Exception as e:
        log_error("fatal", str(e), f"uvicorn main loop", e)
        raise
    finally:
        # 退出时记录
        try:
            log_error("exit", "进程退出", f"port={API_PORT}")
        except:
            pass
