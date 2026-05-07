# -*- coding: utf-8 -*-
# Copyright (c) 2026 ZXJ@DEVS. Author: QQ 1817694478 | Q-Group: 972156177
# Skill: flow-immersion | Version: 3.2.2
"""
Flow Immersion Mode - 沉浸环境控制模块
壁纸切换、桌面图标控制（音乐由H5 Web Audio API替代）
"""
import json
import os
import sys
import ctypes
import struct
import subprocess
from pathlib import Path

# 编码兼容
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except:
        pass

SKILL_DIR = Path(__file__).parent.parent
CONFIG_FILE = SKILL_DIR / "config.json"
DEFAULT_CONFIG = SKILL_DIR / "assets" / "default_config.json"
DATA_DIR = SKILL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# Windows API 常量
SPI_SETDESKWALLPAPER = 0x0014
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

# 预设壁纸颜色 (R, G, B)
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


class ImmersionEnv:
    """沉浸环境控制器 - 纯桌面控制，无音乐依赖"""

    def __init__(self):
        self.config = load_config()
        self.original_wallpaper = self._get_current_wallpaper()
        self.icons_hidden = False
        self.callbacks = []

    def add_callback(self, callback):
        self.callbacks.append(callback)

    def _notify(self, event, data=None):
        for cb in self.callbacks:
            try:
                cb(event, data)
            except Exception:
                pass

    def _get_current_wallpaper(self):
        """获取当前壁纸路径"""
        try:
            result = subprocess.run(
                ['powershell', '-Command',
                 '[SystemParametersInfo]::GetDesktopWallpaper()'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                return result.stdout.strip()
        except Exception:
            pass
        return None

    def set_wallpaper_by_preset(self, preset='minimal'):
        """生成预设纯色BMP并设置为壁纸"""
        color = WALLPAPER_PRESETS.get(preset, (0x1a, 0x1a, 0x2e))
        bmp_path = DATA_DIR / f"wallpaper_{preset}.bmp"

        try:
            self._create_solid_bmp(bmp_path, color)
            return self._apply_wallpaper(str(bmp_path))
        except Exception as e:
            return False, f"壁纸生成失败: {e}"

    def _create_solid_bmp(self, path, color):
        """创建纯色BMP图片"""
        # BMP 文件头 54字节 + 颜色数据
        width, height = 1920, 1080
        row_size = (width * 3 + 3) & ~3  # 每行4字节对齐
        image_size = row_size * height
        file_size = 54 + image_size

        with open(path, 'wb') as f:
            # BITMAPFILEHEADER (14 bytes)
            f.write(b'BM')
            f.write(struct.pack('<I', file_size))
            f.write(struct.pack('<H', 0))  # reserved
            f.write(struct.pack('<H', 0))  # reserved
            f.write(struct.pack('<I', 54))  # offset

            # BITMAPINFOHEADER (40 bytes)
            f.write(struct.pack('<I', 40))  # size
            f.write(struct.pack('<i', width))  # width
            f.write(struct.pack('<i', -height))  # height (negative = top-down)
            f.write(struct.pack('<H', 1))  # planes
            f.write(struct.pack('<H', 24))  # bits per pixel
            f.write(struct.pack('<I', 0))  # compression
            f.write(struct.pack('<I', image_size))
            f.write(struct.pack('<i', 0))  # x pixels per meter
            f.write(struct.pack('<i', 0))  # y pixels per meter
            f.write(struct.pack('<I', 0))  # colors used
            f.write(struct.pack('<I', 0))  # important colors

            # 颜色数据 (BGR format)
            r, g, b = color
            row = bytes([b, g, r] * width)
            pad = b'\x00' * (row_size - len(row))
            for _ in range(height):
                f.write(row + pad)

    def _apply_wallpaper(self, abs_path):
        """应用壁纸"""
        try:
            result = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER, 0, abs_path,
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE
            )
            if result:
                self._notify('wallpaper_changed', {'path': abs_path})
                return True, "壁纸已更换"
            return False, "壁纸设置失败"
        except Exception as e:
            return False, f"壁纸设置异常: {e}"

    def set_wallpaper(self, wallpaper_path=None):
        """设置壁纸（支持自定义路径）"""
        if not wallpaper_path:
            return self.set_wallpaper_by_preset('minimal')

        if not os.path.exists(wallpaper_path):
            return False, f"文件不存在: {wallpaper_path}"

        return self._apply_wallpaper(os.path.abspath(wallpaper_path))

    def restore_wallpaper(self):
        """恢复原始壁纸"""
        if self.original_wallpaper:
            return self._apply_wallpaper(self.original_wallpaper)
        return False, "无原始壁纸记录"

    def hide_desktop_icons(self):
        """隐藏桌面图标（pywin32）"""
        try:
            import win32gui, win32con

            def find_shell_def_view():
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

            hShellDefView = find_shell_def_view()
            if hShellDefView:
                hListView = win32gui.FindWindowEx(hShellDefView, None, "SysListView32", "FolderView")
                if hListView:
                    win32gui.ShowWindow(hListView, win32con.SW_HIDE)
                    self.icons_hidden = True
                    self._notify('icons_hidden', {})
                    return True, "桌面图标已隐藏"
            return False, "未找到桌面图标窗口"
        except ImportError:
            return False, "pywin32未安装"
        except Exception as e:
            return False, f"隐藏图标失败: {e}"

    def show_desktop_icons(self):
        """显示桌面图标（pywin32）"""
        try:
            import win32gui, win32con

            def find_shell_def_view():
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

            hShellDefView = find_shell_def_view()
            if hShellDefView:
                hListView = win32gui.FindWindowEx(hShellDefView, None, "SysListView32", "FolderView")
                if hListView:
                    win32gui.ShowWindow(hListView, win32con.SW_SHOW)
                    self.icons_hidden = False
                    self._notify('icons_shown', {})
                    return True, "桌面图标已显示"
            return False, "未找到桌面图标窗口"
        except ImportError:
            return False, "pywin32未安装"
        except Exception as e:
            return False, f"显示图标失败: {e}"

    def get_status(self):
        """获取当前状态"""
        return {
            'icons_hidden': self.icons_hidden,
            'wallpaper': self._get_current_wallpaper(),
        }

    def get_presets(self):
        """获取壁纸预设列表"""
        return {
            preset: '#{:02x}{:02x}{:02x}'.format(*color)
            for preset, color in WALLPAPER_PRESETS.items()
        }
