"""
音乐播放信息可视化界面
- 自动获取当前播放的音乐信息
- 支持手动编辑
- 可调整布局、样式和位置
- 配置自动保存
"""

# Windows 高 DPI 支持 —— 必须在 tkinter 导入前设置
import ctypes
import sys
try:
    # PROCESS_PER_MONITOR_DPI_AWARE (最佳清晰度)
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        # 回退：PROCESS_SYSTEM_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

import tkinter as tk
from tkinter import ttk, messagebox, colorchooser
import json
import subprocess
import threading
import time
import base64
from io import BytesIO
from pathlib import Path

try:
    from PIL import Image, ImageTk
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    print("⚠️ 未安装 Pillow，封面显示功能不可用。请运行: pip install pillow")


class MusicDisplayGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("音乐播放信息显示")
        
        # 配置文件路径
        self.config_file = Path("music_display_config.json")
        
        # 默认配置
        self.config = {
            'window': {
                'width': 680,
                'height': 350,
                'x': 100,
                'y': 100,
                'topmost': True,
                'alpha': 0.95
            },
            'style': {
                'bg_color': '#1e1e1e',
                'text_color': '#ffffff',
                'accent_color': '#4a9eff',
                'font_family': 'Microsoft YaHei UI',
                'title_size': 24,
                'artist_size': 16,
                'album_size': 14
            },
            'auto_update': {
                'enabled': True,
                'interval': 2
            },
            'manual_data': {
                'title': '',
                'artist': '',
                'album': '',
                'status': ''
            },
            'thumbnail': {
                'size': 200,
                'show': True
            },
            'alignment': {
                'title': 'left',
                'artist': 'left',
                'album': 'left',
                'status': 'left'
            }
        }
        
        # 加载配置
        self.load_config()
        
        # 当前显示的信息
        self.current_info = {
            'title': '等待获取...',
            'artist': '',
            'album': '',
            'status': '',
            'mode': 'auto'  # auto 或 manual
        }
        
        # 封面相关状态
        self.current_cover_image = None  # 保持 ImageTk 引用，防止被 GC
        self.last_track_key = None  # 用于检测是否切歌
        self.thumbnail_size = self.config.get('thumbnail', {}).get('size', 150)
        self.show_thumbnail = self.config.get('thumbnail', {}).get('show', True) and HAS_PILLOW
        
        # 自动更新线程
        self.update_thread = None
        self.running = False
        
        # 初始化界面
        self.init_ui()
        
        # 应用配置
        self.apply_config()
        
        # 启动自动更新
        if self.config['auto_update']['enabled']:
            self.start_auto_update()
    
    def init_ui(self):
        """初始化用户界面"""
        # 设置窗口背景色
        self.root.configure(bg=self.config['style']['bg_color'])
        
        # 主容器
        main_frame = tk.Frame(self.root, bg=self.config['style']['bg_color'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 标题栏（显示模式和状态）
        header_frame = tk.Frame(main_frame, bg=self.config['style']['bg_color'])
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        self.mode_label = tk.Label(
            header_frame,
            text="🎵 自动模式",
            font=(self.config['style']['font_family'], 10),
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['accent_color']
        )
        self.mode_label.pack(side=tk.LEFT)
        
        self.status_indicator = tk.Label(
            header_frame,
            text="●",
            font=(self.config['style']['font_family'], 16),
            bg=self.config['style']['bg_color'],
            fg='#00ff00'
        )
        self.status_indicator.pack(side=tk.RIGHT)
        
        # 内容区域
        self.content_frame = tk.Frame(main_frame, bg=self.config['style']['bg_color'])
        self.content_frame.pack(fill=tk.BOTH, expand=True)
        
        # 右侧：封面显示区域（先 pack 右侧，左侧 expand 填满剩余空间）
        if self.show_thumbnail:
            cover_frame = tk.Frame(
                self.content_frame, 
                bg=self.config['style']['bg_color'],
                width=self.thumbnail_size,
                height=self.thumbnail_size
            )
            cover_frame.pack(side=tk.RIGHT, padx=(10, 0), anchor=tk.N)
            cover_frame.pack_propagate(False)  # 固定大小
            
            self.cover_label = tk.Label(
                cover_frame,
                text="🎵\n暂无封面",
                font=(self.config['style']['font_family'], 10),
                bg='#2d2d2d',
                fg='#666666',
                width=self.thumbnail_size,
                height=self.thumbnail_size
            )
            self.cover_label.pack(fill=tk.BOTH, expand=True)
        else:
            self.cover_label = None
        
        # 左侧：歌曲信息显示区域
        info_frame = tk.Frame(self.content_frame, bg=self.config['style']['bg_color'])
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 读取对齐配置
        align_cfg = self.config.get('alignment', {})
        title_anchor, title_justify = self._align_to_tk(align_cfg.get('title', 'left'))
        artist_anchor, artist_justify = self._align_to_tk(align_cfg.get('artist', 'left'))
        album_anchor, album_justify = self._align_to_tk(align_cfg.get('album', 'left'))
        status_anchor, status_justify = self._align_to_tk(align_cfg.get('status', 'left'))
        
        # wraplength 初始值设为 0（后面由 _update_wraplength 动态计算）
        # 歌曲标题
        self.title_label = tk.Label(
            info_frame,
            text="等待获取...",
            font=(self.config['style']['font_family'], 
                  self.config['style']['title_size'], 'bold'),
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['text_color'],
            wraplength=1,
            justify=title_justify,
            anchor=title_anchor
        )
        self.title_label.pack(pady=(0, 15), fill=tk.X)
        
        # 艺术家
        self.artist_label = tk.Label(
            info_frame,
            text="",
            font=(self.config['style']['font_family'], 
                  self.config['style']['artist_size']),
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['text_color'],
            wraplength=1,
            justify=artist_justify,
            anchor=artist_anchor
        )
        self.artist_label.pack(pady=(0, 10), fill=tk.X)
        
        # 专辑
        self.album_label = tk.Label(
            info_frame,
            text="",
            font=(self.config['style']['font_family'], 
                  self.config['style']['album_size']),
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['accent_color'],
            wraplength=1,
            justify=album_justify,
            anchor=album_anchor
        )
        self.album_label.pack(pady=(0, 10), fill=tk.X)
        
        # 播放状态
        self.playback_label = tk.Label(
            info_frame,
            text="",
            font=(self.config['style']['font_family'], 10),
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['accent_color'],
            anchor=status_anchor
        )
        self.playback_label.pack(fill=tk.X)
        
        # 绑定窗口大小变化事件，动态更新 wraplength
        self.root.bind("<Configure>", self._on_window_resize)
        self._resize_after_id = None
        
        # 控制按钮区域
        control_frame = tk.Frame(main_frame, bg=self.config['style']['bg_color'])
        control_frame.pack(fill=tk.X, pady=(20, 0))
        
        # 按钮样式
        button_style = {
            'font': (self.config['style']['font_family'], 9),
            'bg': self.config['style']['accent_color'],
            'fg': '#ffffff',
            'relief': tk.FLAT,
            'cursor': 'hand2',
            'padx': 10,
            'pady': 5
        }
        
        # 刷新按钮
        self.refresh_btn = tk.Button(
            control_frame,
            text="🔄 刷新",
            command=self.manual_refresh,
            **button_style
        )
        self.refresh_btn.pack(side=tk.LEFT, padx=(0, 5))
        
        # 手动编辑按钮
        edit_btn = tk.Button(
            control_frame,
            text="✏️ 编辑",
            command=self.open_edit_dialog,
            **button_style
        )
        edit_btn.pack(side=tk.LEFT, padx=5)
        
        # 设置按钮
        settings_btn = tk.Button(
            control_frame,
            text="⚙️ 设置",
            command=self.open_settings_dialog,
            **button_style
        )
        settings_btn.pack(side=tk.LEFT, padx=5)
        
        # 切换模式按钮
        self.toggle_btn = tk.Button(
            control_frame,
            text="📝 手动模式",
            command=self.toggle_mode,
            **button_style
        )
        self.toggle_btn.pack(side=tk.RIGHT)
        
        # 绑定窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 绑定右键菜单
        self.root.bind("<Button-3>", self.show_context_menu)
    
    def _align_to_tk(self, align_str):
        """将对齐字符串转换为 tkinter anchor 和 justify"""
        mapping = {
            'left':   (tk.W, tk.LEFT),
            'center': (tk.CENTER, tk.CENTER),
            'right':  (tk.E, tk.RIGHT),
        }
        return mapping.get(align_str, (tk.W, tk.LEFT))
    
    def _apply_alignment(self):
        """实时应用对齐配置到各信息标签"""
        align_cfg = self.config.get('alignment', {})
        
        label_map = {
            'title':  self.title_label,
            'artist': self.artist_label,
            'album':  self.album_label,
            'status': self.playback_label,
        }
        
        # 每个标签的默认 pack 参数
        pack_params = {
            'title':  {'pady': (0, 15), 'fill': tk.X},
            'artist': {'pady': (0, 10), 'fill': tk.X},
            'album':  {'pady': (0, 10), 'fill': tk.X},
            'status': {'fill': tk.X},
        }
        
        for key, label in label_map.items():
            anchor, justify = self._align_to_tk(align_cfg.get(key, 'left'))
            # anchor 控制文字在 Label 内部的位置（Label 用 fill=X 占满宽度）
            label.config(justify=justify, anchor=anchor)
            # 重新 pack
            label.pack_forget()
            label.pack(**pack_params[key])
    
    def apply_config(self):
        """应用配置到窗口"""
        # 窗口大小和位置
        w = self.config['window']['width']
        h = self.config['window']['height']
        x = self.config['window']['x']
        y = self.config['window']['y']
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        
        # 置顶
        self.root.attributes('-topmost', self.config['window']['topmost'])
        
        # 透明度
        self.root.attributes('-alpha', self.config['window']['alpha'])
        
        # 初始化后延迟计算一次 wraplength
        self.root.after(100, self._update_wraplength)
    
    def _on_window_resize(self, event):
        """窗口大小变化时触发（去抖动）"""
        # 只处理主窗口的 resize 事件
        if event.widget != self.root:
            return
        # 去抖动：取消前一次延迟调用，重新安排
        if self._resize_after_id is not None:
            self.root.after_cancel(self._resize_after_id)
        self._resize_after_id = self.root.after(50, self._update_wraplength)
    
    def _update_wraplength(self):
        """根据当前窗口宽度动态计算文字换行宽度"""
        self._resize_after_id = None
        try:
            # 获取 info_frame 实际可用宽度
            info_frame = self.title_label.master
            info_frame.update_idletasks()
            available_width = info_frame.winfo_width()
            
            # 如果还没布局完成（宽度为1），用窗口宽度估算
            if available_width <= 1:
                win_width = self.root.winfo_width()
                padding = 40 + 10  # main_frame padx(20*2) + cover_frame padx(10)
                cover_w = (self.thumbnail_size + 10) if self.show_thumbnail else 0
                available_width = max(100, win_width - padding - cover_w)
            
            # 留一点内边距
            wrap = max(100, available_width - 10)
            
            self.title_label.config(wraplength=wrap)
            self.artist_label.config(wraplength=wrap)
            self.album_label.config(wraplength=wrap)
        except Exception:
            pass
    
    def load_config(self):
        """从文件加载配置"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 深度合并配置
                    self.merge_config(self.config, loaded_config)
            except Exception as e:
                print(f"加载配置失败: {e}")
    
    def save_config(self):
        """保存配置到文件"""
        try:
            # 保存当前窗口位置和大小
            self.config['window']['x'] = self.root.winfo_x()
            self.config['window']['y'] = self.root.winfo_y()
            self.config['window']['width'] = self.root.winfo_width()
            self.config['window']['height'] = self.root.winfo_height()
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"保存配置失败: {e}")
    
    def merge_config(self, base, update):
        """递归合并配置字典"""
        for key, value in update.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                self.merge_config(base[key], value)
            else:
                base[key] = value
    
    def get_playing_music(self):
        """获取当前播放的音乐信息（不含封面）"""
        try:
            result = subprocess.run(
                ['python', 'get_music_powershell.py', '--json'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=10,
                cwd=Path(__file__).parent
            )
            
            if result.returncode == 0 and result.stdout.strip():
                info = json.loads(result.stdout)
                return info
            else:
                return {'status': 'error', 'message': '获取失败'}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
    
    def get_album_thumbnail(self):
        """单独获取专辑封面（带封面的完整查询）"""
        try:
            result = subprocess.run(
                ['python', 'get_music_powershell.py', '--json', '--thumbnail'],
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace',
                timeout=15,
                cwd=Path(__file__).parent
            )
            
            if result.returncode == 0 and result.stdout.strip():
                info = json.loads(result.stdout)
                return info.get('thumbnail_base64')
            return None
        except Exception as e:
            print(f"获取封面失败: {e}")
            return None
    
    def _make_track_key(self, info):
        """生成歌曲标识 key，用于判断是否切歌"""
        if info.get('status') != 'success':
            return None
        return f"{info.get('title', '')}|{info.get('artist', '')}|{info.get('album_title', '')}"
    
    def update_thumbnail(self, thumbnail_base64):
        """用 Base64 数据更新封面显示"""
        if not self.show_thumbnail or self.cover_label is None:
            return
        
        if not thumbnail_base64:
            self.clear_thumbnail()
            return
        
        try:
            img_bytes = base64.b64decode(thumbnail_base64)
            img = Image.open(BytesIO(img_bytes))
            
            # 等比例缩放到配置大小
            size = self.thumbnail_size
            img.thumbnail((size, size), Image.LANCZOS)
            
            # 创建正方形画布居中放置
            canvas = Image.new('RGBA', (size, size), (45, 45, 45, 255))  # #2d2d2d
            offset_x = (size - img.width) // 2
            offset_y = (size - img.height) // 2
            
            # 处理 RGBA 透明通道
            if img.mode == 'RGBA':
                canvas.paste(img, (offset_x, offset_y), img)
            else:
                canvas.paste(img, (offset_x, offset_y))
            
            photo = ImageTk.PhotoImage(canvas)
            
            # 必须保持引用，否则 Tkinter 会 GC 掉图片
            self.current_cover_image = photo
            self.cover_label.config(image=photo, text='')
            
        except Exception as e:
            print(f"封面显示失败: {e}")
            self.clear_thumbnail()
    
    def clear_thumbnail(self):
        """清空封面，显示占位"""
        if self.cover_label is not None:
            self.current_cover_image = None
            self.cover_label.config(
                image='',
                text="🎵\n暂无封面",
                font=(self.config['style']['font_family'], 10),
                fg='#666666'
            )
    
    def _rebuild_cover_area(self):
        """动态重建封面显示区域（尺寸或显示/隐藏变化时调用）"""
        # 销毁旧封面区域
        if self.cover_label is not None:
            cover_frame = self.cover_label.master
            cover_frame.destroy()
            self.cover_label = None
            self.current_cover_image = None
        
        if not self.show_thumbnail:
            # 不显示封面，触发 wraplength 重新计算
            self.root.after(50, self._update_wraplength)
            return
        
        # 获取 info_frame 引用，需要在它之前 pack 封面（RIGHT 侧）
        info_frame = self.title_label.master
        
        # 先把 info_frame 从布局中暂时移除，确保封面在右侧
        info_frame.pack_forget()
        
        # 创建新的封面区域
        size = self.thumbnail_size
        cover_frame = tk.Frame(
            self.content_frame,
            bg=self.config['style']['bg_color'],
            width=size,
            height=size
        )
        cover_frame.pack(side=tk.RIGHT, padx=(10, 0), anchor=tk.N)
        cover_frame.pack_propagate(False)
        
        self.cover_label = tk.Label(
            cover_frame,
            text="🎵\n暂无封面",
            font=(self.config['style']['font_family'], 10),
            bg='#2d2d2d',
            fg='#666666',
            width=size,
            height=size
        )
        self.cover_label.pack(fill=tk.BOTH, expand=True)
        
        # 把 info_frame 重新 pack 回来
        info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 触发 wraplength 重新计算
        self.root.after(50, self._update_wraplength)
    
    def update_display(self, info):
        """更新显示内容"""
        if info.get('status') == 'success':
            self.current_info['title'] = info.get('title', '未知')
            self.current_info['artist'] = info.get('artist', '未知')
            self.current_info['album'] = info.get('album_title', '未知')
            self.current_info['status'] = info.get('playback_status', '')
            
            # 更新标签
            self.title_label.config(text=self.current_info['title'])
            self.artist_label.config(text=f"🎤 {self.current_info['artist']}")
            self.album_label.config(text=f"💿 {self.current_info['album']}")
            
            # 播放状态图标
            status_icon = "▶️" if "播放" in self.current_info['status'] else "⏸️"
            self.playback_label.config(text=f"{status_icon} {self.current_info['status']}")
            
            # 更新状态指示器（绿色表示正常）
            self.status_indicator.config(fg='#00ff00')
            
        elif info.get('status') == 'no_media':
            self.title_label.config(text="暂无播放")
            self.artist_label.config(text="")
            self.album_label.config(text="")
            self.playback_label.config(text="⏹️ 未播放")
            self.status_indicator.config(fg='#ffaa00')
            
            # 清空封面
            self.last_track_key = None
            self.clear_thumbnail()
            
        else:
            # 错误状态
            if self.current_info['mode'] == 'auto':
                self.title_label.config(text="获取失败")
                self.artist_label.config(text="")
                self.album_label.config(text="")
                self.playback_label.config(text=f"❌ {info.get('message', '未知错误')}")
            self.status_indicator.config(fg='#ff0000')
    
    def auto_update_loop(self):
        """自动更新循环"""
        while self.running:
            if self.current_info['mode'] == 'auto':
                info = self.get_playing_music()
                
                # 检测是否切歌，只在切歌时获取封面
                track_key = self._make_track_key(info)
                need_cover = (track_key is not None and track_key != self.last_track_key)
                
                if need_cover and self.show_thumbnail:
                    # 歌曲变化了，获取封面
                    thumbnail_base64 = self.get_album_thumbnail()
                    self.last_track_key = track_key
                    self.root.after(0, lambda tb=thumbnail_base64: self.update_thumbnail(tb))
                elif track_key is None and self.last_track_key is not None:
                    # 从有歌变为无歌
                    self.last_track_key = None
                
                self.root.after(0, lambda i=info: self.update_display(i))
            
            time.sleep(self.config['auto_update']['interval'])
    
    def start_auto_update(self):
        """启动自动更新"""
        if not self.running:
            self.running = True
            self.update_thread = threading.Thread(target=self.auto_update_loop, daemon=True)
            self.update_thread.start()
    
    def stop_auto_update(self):
        """停止自动更新"""
        self.running = False
    
    def manual_refresh(self):
        """手动刷新"""
        info = self.get_playing_music()
        self.update_display(info)
        
        # 手动刷新时也检查是否需要更新封面
        if self.show_thumbnail:
            track_key = self._make_track_key(info)
            if track_key is not None and track_key != self.last_track_key:
                self.last_track_key = track_key
                # 在后台线程获取封面避免卡 UI
                def fetch_cover():
                    tb = self.get_album_thumbnail()
                    self.root.after(0, lambda: self.update_thumbnail(tb))
                threading.Thread(target=fetch_cover, daemon=True).start()
            elif track_key is None:
                self.last_track_key = None
                self.clear_thumbnail()
    
    def toggle_mode(self):
        """切换自动/手动模式"""
        if self.current_info['mode'] == 'auto':
            self.current_info['mode'] = 'manual'
            self.mode_label.config(text="📝 手动模式")
            self.toggle_btn.config(text="🔄 自动模式")
            
            # 保存当前显示的内容到手动数据
            self.config['manual_data']['title'] = self.current_info['title']
            self.config['manual_data']['artist'] = self.current_info['artist']
            self.config['manual_data']['album'] = self.current_info['album']
            self.config['manual_data']['status'] = self.current_info['status']
            
            # 手动模式下清空封面
            self.clear_thumbnail()
            
        else:
            self.current_info['mode'] = 'auto'
            self.mode_label.config(text="🎵 自动模式")
            self.toggle_btn.config(text="📝 手动模式")
            # 切回自动时重置 track_key 以强制刷新封面
            self.last_track_key = None
            # 立即刷新
            self.manual_refresh()
    
    def open_edit_dialog(self):
        """打开编辑对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("编辑歌曲信息")
        dialog.geometry("400x300")
        dialog.configure(bg=self.config['style']['bg_color'])
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        frame = tk.Frame(dialog, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 标签样式
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        # 输入框样式
        entry_style = {
            'font': (self.config['style']['font_family'], 11),
            'bg': '#2d2d2d',
            'fg': self.config['style']['text_color'],
            'insertbackground': self.config['style']['text_color'],
            'relief': tk.FLAT
        }
        
        # 歌曲标题
        tk.Label(frame, text="歌曲标题:", **label_style).pack(anchor=tk.W, pady=(0, 5))
        title_entry = tk.Entry(frame, **entry_style)
        title_entry.insert(0, self.current_info['title'])
        title_entry.pack(fill=tk.X, pady=(0, 15))
        
        # 艺术家
        tk.Label(frame, text="艺术家:", **label_style).pack(anchor=tk.W, pady=(0, 5))
        artist_entry = tk.Entry(frame, **entry_style)
        artist_entry.insert(0, self.current_info['artist'])
        artist_entry.pack(fill=tk.X, pady=(0, 15))
        
        # 专辑
        tk.Label(frame, text="专辑:", **label_style).pack(anchor=tk.W, pady=(0, 5))
        album_entry = tk.Entry(frame, **entry_style)
        album_entry.insert(0, self.current_info['album'])
        album_entry.pack(fill=tk.X, pady=(0, 15))
        
        # 播放状态
        tk.Label(frame, text="状态:", **label_style).pack(anchor=tk.W, pady=(0, 5))
        status_var = tk.StringVar(value=self.current_info['status'])
        status_combo = ttk.Combobox(
            frame,
            textvariable=status_var,
            values=['正在播放', '已暂停', '已停止'],
            state='readonly',
            font=(self.config['style']['font_family'], 11)
        )
        status_combo.pack(fill=tk.X, pady=(0, 20))
        
        # 按钮
        button_frame = tk.Frame(frame, bg=self.config['style']['bg_color'])
        button_frame.pack(fill=tk.X)
        
        def save_changes():
            self.current_info['title'] = title_entry.get()
            self.current_info['artist'] = artist_entry.get()
            self.current_info['album'] = album_entry.get()
            self.current_info['status'] = status_var.get()
            self.current_info['mode'] = 'manual'
            
            # 保存到配置
            self.config['manual_data']['title'] = self.current_info['title']
            self.config['manual_data']['artist'] = self.current_info['artist']
            self.config['manual_data']['album'] = self.current_info['album']
            self.config['manual_data']['status'] = self.current_info['status']
            
            # 更新显示
            self.update_display({'status': 'success', **self.current_info})
            
            # 切换到手动模式
            self.mode_label.config(text="📝 手动模式")
            self.toggle_btn.config(text="🔄 自动模式")
            
            dialog.destroy()
        
        tk.Button(
            button_frame,
            text="保存",
            command=save_changes,
            bg=self.config['style']['accent_color'],
            fg='#ffffff',
            font=(self.config['style']['font_family'], 10),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=5
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        tk.Button(
            button_frame,
            text="取消",
            command=dialog.destroy,
            bg='#444444',
            fg='#ffffff',
            font=(self.config['style']['font_family'], 10),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=5
        ).pack(side=tk.LEFT)
    
    def open_settings_dialog(self):
        """打开设置对话框"""
        dialog = tk.Toplevel(self.root)
        dialog.title("设置")
        dialog.geometry("450x500")
        dialog.configure(bg=self.config['style']['bg_color'])
        dialog.transient(self.root)
        dialog.grab_set()
        
        # 居中显示
        dialog.update_idletasks()
        x = self.root.winfo_x() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_y() + (self.root.winfo_height() - dialog.winfo_height()) // 2
        dialog.geometry(f"+{x}+{y}")
        
        # 创建笔记本标签页
        notebook = ttk.Notebook(dialog)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 样式标签页
        style_frame = tk.Frame(notebook, bg=self.config['style']['bg_color'])
        notebook.add(style_frame, text="外观")
        
        # 窗口标签页
        window_frame = tk.Frame(notebook, bg=self.config['style']['bg_color'])
        notebook.add(window_frame, text="窗口")
        
        # 封面标签页
        cover_frame = tk.Frame(notebook, bg=self.config['style']['bg_color'])
        notebook.add(cover_frame, text="封面")
        
        # 对齐标签页
        align_frame = tk.Frame(notebook, bg=self.config['style']['bg_color'])
        notebook.add(align_frame, text="对齐")
        
        # 更新标签页
        update_frame = tk.Frame(notebook, bg=self.config['style']['bg_color'])
        notebook.add(update_frame, text="更新")
        
        # === 外观设置 ===
        self.create_style_settings(style_frame)
        
        # === 窗口设置 ===
        self.create_window_settings(window_frame)
        
        # === 封面设置 ===
        self.create_cover_settings(cover_frame)
        
        # === 对齐设置 ===
        self.create_alignment_settings(align_frame)
        
        # === 更新设置 ===
        self.create_update_settings(update_frame)
        
        # 底部按钮
        button_frame = tk.Frame(dialog, bg=self.config['style']['bg_color'])
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        tk.Button(
            button_frame,
            text="应用",
            command=lambda: self.apply_settings(dialog),
            bg=self.config['style']['accent_color'],
            fg='#ffffff',
            font=(self.config['style']['font_family'], 10),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=5
        ).pack(side=tk.RIGHT, padx=(5, 0))
        
        tk.Button(
            button_frame,
            text="关闭",
            command=dialog.destroy,
            bg='#444444',
            fg='#ffffff',
            font=(self.config['style']['font_family'], 10),
            relief=tk.FLAT,
            cursor='hand2',
            padx=20,
            pady=5
        ).pack(side=tk.RIGHT)
    
    def create_style_settings(self, parent):
        """创建样式设置界面"""
        frame = tk.Frame(parent, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        # 背景颜色
        tk.Label(frame, text="背景颜色:", **label_style).grid(row=0, column=0, sticky=tk.W, pady=5)
        self.bg_color_btn = tk.Button(
            frame,
            text="  ",
            bg=self.config['style']['bg_color'],
            width=3,
            command=lambda: self.choose_color('bg_color')
        )
        self.bg_color_btn.grid(row=0, column=1, sticky=tk.W, padx=10)
        
        # 文字颜色
        tk.Label(frame, text="文字颜色:", **label_style).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.text_color_btn = tk.Button(
            frame,
            text="  ",
            bg=self.config['style']['text_color'],
            width=3,
            command=lambda: self.choose_color('text_color')
        )
        self.text_color_btn.grid(row=1, column=1, sticky=tk.W, padx=10)
        
        # 强调色
        tk.Label(frame, text="强调色:", **label_style).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.accent_color_btn = tk.Button(
            frame,
            text="  ",
            bg=self.config['style']['accent_color'],
            width=3,
            command=lambda: self.choose_color('accent_color')
        )
        self.accent_color_btn.grid(row=2, column=1, sticky=tk.W, padx=10)
        
        # 字体大小
        tk.Label(frame, text="标题大小:", **label_style).grid(row=3, column=0, sticky=tk.W, pady=5)
        self.title_size_var = tk.IntVar(value=self.config['style']['title_size'])
        tk.Spinbox(
            frame,
            from_=12, to=48,
            textvariable=self.title_size_var,
            width=8,
            font=(self.config['style']['font_family'], 10)
        ).grid(row=3, column=1, sticky=tk.W, padx=10)
        
        tk.Label(frame, text="艺术家大小:", **label_style).grid(row=4, column=0, sticky=tk.W, pady=5)
        self.artist_size_var = tk.IntVar(value=self.config['style']['artist_size'])
        tk.Spinbox(
            frame,
            from_=10, to=32,
            textvariable=self.artist_size_var,
            width=8,
            font=(self.config['style']['font_family'], 10)
        ).grid(row=4, column=1, sticky=tk.W, padx=10)
    
    def create_window_settings(self, parent):
        """创建窗口设置界面"""
        frame = tk.Frame(parent, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        # 窗口置顶
        self.topmost_var = tk.BooleanVar(value=self.config['window']['topmost'])
        tk.Checkbutton(
            frame,
            text="窗口置顶",
            variable=self.topmost_var,
            **label_style,
            selectcolor='#444444'
        ).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        # 透明度
        tk.Label(frame, text="透明度:", **label_style).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.alpha_var = tk.DoubleVar(value=self.config['window']['alpha'])
        tk.Scale(
            frame,
            from_=0.3, to=1.0,
            resolution=0.05,
            orient=tk.HORIZONTAL,
            variable=self.alpha_var,
            length=200,
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['text_color'],
            troughcolor='#444444',
            highlightthickness=0
        ).grid(row=1, column=1, sticky=tk.W, padx=10)
        
        # 窗口宽度
        tk.Label(frame, text="窗口宽度 (px):", **label_style).grid(row=2, column=0, sticky=tk.W, pady=5)
        self.win_width_var = tk.IntVar(value=self.root.winfo_width())
        tk.Spinbox(
            frame,
            from_=300, to=3000,
            increment=10,
            textvariable=self.win_width_var,
            width=8,
            font=(self.config['style']['font_family'], 10)
        ).grid(row=2, column=1, sticky=tk.W, padx=10)
        
        # 窗口高度
        tk.Label(frame, text="窗口高度 (px):", **label_style).grid(row=3, column=0, sticky=tk.W, pady=5)
        self.win_height_var = tk.IntVar(value=self.root.winfo_height())
        tk.Spinbox(
            frame,
            from_=200, to=2000,
            increment=10,
            textvariable=self.win_height_var,
            width=8,
            font=(self.config['style']['font_family'], 10)
        ).grid(row=3, column=1, sticky=tk.W, padx=10)
        
        # 提示
        tk.Label(
            frame,
            text="💡 也可以直接拖拽窗口边缘调整大小\n"
                 "    信息栏宽度会自动适配窗口",
            justify=tk.LEFT,
            **label_style
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(15, 0))
    
    def create_update_settings(self, parent):
        """创建更新设置界面"""
        frame = tk.Frame(parent, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        # 自动更新
        self.auto_update_var = tk.BooleanVar(value=self.config['auto_update']['enabled'])
        tk.Checkbutton(
            frame,
            text="启用自动更新",
            variable=self.auto_update_var,
            **label_style,
            selectcolor='#444444'
        ).grid(row=0, column=0, sticky=tk.W, pady=5)
        
        # 更新间隔
        tk.Label(frame, text="更新间隔(秒):", **label_style).grid(row=1, column=0, sticky=tk.W, pady=5)
        self.interval_var = tk.IntVar(value=self.config['auto_update']['interval'])
        tk.Spinbox(
            frame,
            from_=1, to=60,
            textvariable=self.interval_var,
            width=8,
            font=(self.config['style']['font_family'], 10)
        ).grid(row=1, column=1, sticky=tk.W, padx=10)
    
    def create_cover_settings(self, parent):
        """创建封面设置界面"""
        frame = tk.Frame(parent, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        # 显示封面开关
        self.show_cover_var = tk.BooleanVar(value=self.config.get('thumbnail', {}).get('show', True))
        tk.Checkbutton(
            frame,
            text="显示专辑封面",
            variable=self.show_cover_var,
            **label_style,
            selectcolor='#444444'
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 15))
        
        # 封面尺寸
        tk.Label(frame, text="封面尺寸 (px):", **label_style).grid(row=1, column=0, sticky=tk.W, pady=5)
        
        current_size = self.config.get('thumbnail', {}).get('size', 150)
        self.cover_size_var = tk.IntVar(value=current_size)
        
        # 尺寸滑块
        size_scale = tk.Scale(
            frame,
            from_=50, to=500,
            resolution=10,
            orient=tk.HORIZONTAL,
            variable=self.cover_size_var,
            length=250,
            bg=self.config['style']['bg_color'],
            fg=self.config['style']['text_color'],
            troughcolor='#444444',
            highlightthickness=0,
            font=(self.config['style']['font_family'], 9)
        )
        size_scale.grid(row=1, column=1, sticky=tk.W, padx=10)
        
        # 实时预览尺寸数值
        self.cover_size_preview = tk.Label(
            frame,
            text=f"当前: {current_size} × {current_size}",
            **label_style
        )
        self.cover_size_preview.grid(row=2, column=0, columnspan=2, sticky=tk.W, pady=(5, 15))
        
        # 绑定滑块变化事件
        def on_size_change(val):
            v = int(float(val))
            self.cover_size_preview.config(text=f"当前: {v} × {v}")
        size_scale.config(command=on_size_change)
        
        # 提示
        tk.Label(
            frame,
            text="💡 修改封面尺寸后点击「应用」即可生效\n"
                 "    较大的封面尺寸会让细节更清晰",
            justify=tk.LEFT,
            **label_style
        ).grid(row=3, column=0, columnspan=2, sticky=tk.W, pady=(10, 0))
    
    def create_alignment_settings(self, parent):
        """创建对齐设置界面"""
        frame = tk.Frame(parent, bg=self.config['style']['bg_color'])
        frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        label_style = {
            'font': (self.config['style']['font_family'], 10),
            'bg': self.config['style']['bg_color'],
            'fg': self.config['style']['text_color']
        }
        
        align_cfg = self.config.get('alignment', {})
        align_options = ['left', 'center', 'right']
        align_display = {'left': '靠左', 'center': '居中', 'right': '靠右'}
        
        # 标题对齐
        tk.Label(frame, text="歌曲标题:", **label_style).grid(row=0, column=0, sticky=tk.W, pady=8)
        self.align_title_var = tk.StringVar(value=align_cfg.get('title', 'left'))
        title_align_frame = tk.Frame(frame, bg=self.config['style']['bg_color'])
        title_align_frame.grid(row=0, column=1, sticky=tk.W, padx=10)
        for opt in align_options:
            tk.Radiobutton(
                title_align_frame, text=align_display[opt], value=opt,
                variable=self.align_title_var,
                bg=self.config['style']['bg_color'],
                fg=self.config['style']['text_color'],
                selectcolor='#444444',
                font=(self.config['style']['font_family'], 9)
            ).pack(side=tk.LEFT, padx=5)
        
        # 艺术家对齐
        tk.Label(frame, text="艺术家:", **label_style).grid(row=1, column=0, sticky=tk.W, pady=8)
        self.align_artist_var = tk.StringVar(value=align_cfg.get('artist', 'left'))
        artist_align_frame = tk.Frame(frame, bg=self.config['style']['bg_color'])
        artist_align_frame.grid(row=1, column=1, sticky=tk.W, padx=10)
        for opt in align_options:
            tk.Radiobutton(
                artist_align_frame, text=align_display[opt], value=opt,
                variable=self.align_artist_var,
                bg=self.config['style']['bg_color'],
                fg=self.config['style']['text_color'],
                selectcolor='#444444',
                font=(self.config['style']['font_family'], 9)
            ).pack(side=tk.LEFT, padx=5)
        
        # 专辑对齐
        tk.Label(frame, text="专辑:", **label_style).grid(row=2, column=0, sticky=tk.W, pady=8)
        self.align_album_var = tk.StringVar(value=align_cfg.get('album', 'left'))
        album_align_frame = tk.Frame(frame, bg=self.config['style']['bg_color'])
        album_align_frame.grid(row=2, column=1, sticky=tk.W, padx=10)
        for opt in align_options:
            tk.Radiobutton(
                album_align_frame, text=align_display[opt], value=opt,
                variable=self.align_album_var,
                bg=self.config['style']['bg_color'],
                fg=self.config['style']['text_color'],
                selectcolor='#444444',
                font=(self.config['style']['font_family'], 9)
            ).pack(side=tk.LEFT, padx=5)
        
        # 播放状态对齐
        tk.Label(frame, text="播放状态:", **label_style).grid(row=3, column=0, sticky=tk.W, pady=8)
        self.align_status_var = tk.StringVar(value=align_cfg.get('status', 'left'))
        status_align_frame = tk.Frame(frame, bg=self.config['style']['bg_color'])
        status_align_frame.grid(row=3, column=1, sticky=tk.W, padx=10)
        for opt in align_options:
            tk.Radiobutton(
                status_align_frame, text=align_display[opt], value=opt,
                variable=self.align_status_var,
                bg=self.config['style']['bg_color'],
                fg=self.config['style']['text_color'],
                selectcolor='#444444',
                font=(self.config['style']['font_family'], 9)
            ).pack(side=tk.LEFT, padx=5)
        
        # 提示
        tk.Label(
            frame,
            text="💡 调整各信息栏的文字对齐方式\n"
                 "    点击「应用」即可实时生效",
            justify=tk.LEFT,
            **label_style
        ).grid(row=4, column=0, columnspan=2, sticky=tk.W, pady=(15, 0))
    
    def choose_color(self, color_key):
        """选择颜色"""
        current_color = self.config['style'][color_key]
        color = colorchooser.askcolor(color=current_color)
        if color[1]:
            self.config['style'][color_key] = color[1]
            # 更新按钮颜色
            if color_key == 'bg_color':
                self.bg_color_btn.config(bg=color[1])
            elif color_key == 'text_color':
                self.text_color_btn.config(bg=color[1])
            elif color_key == 'accent_color':
                self.accent_color_btn.config(bg=color[1])
    
    def apply_settings(self, dialog):
        """应用设置"""
        # 更新配置
        self.config['style']['title_size'] = self.title_size_var.get()
        self.config['style']['artist_size'] = self.artist_size_var.get()
        self.config['window']['topmost'] = self.topmost_var.get()
        self.config['window']['alpha'] = self.alpha_var.get()
        self.config['auto_update']['enabled'] = self.auto_update_var.get()
        self.config['auto_update']['interval'] = self.interval_var.get()
        
        # 窗口大小
        new_w = self.win_width_var.get()
        new_h = self.win_height_var.get()
        self.config['window']['width'] = new_w
        self.config['window']['height'] = new_h
        
        # 封面设置
        old_cover_size = self.thumbnail_size
        old_show = self.show_thumbnail
        
        new_cover_size = self.cover_size_var.get()
        new_show = self.show_cover_var.get() and HAS_PILLOW
        
        self.config['thumbnail']['size'] = new_cover_size
        self.config['thumbnail']['show'] = self.show_cover_var.get()
        
        # 对齐设置
        self.config['alignment'] = {
            'title':  self.align_title_var.get(),
            'artist': self.align_artist_var.get(),
            'album':  self.align_album_var.get(),
            'status': self.align_status_var.get(),
        }
        self._apply_alignment()
        
        # 应用到窗口
        self.root.attributes('-topmost', self.config['window']['topmost'])
        self.root.attributes('-alpha', self.config['window']['alpha'])
        
        # 应用窗口大小
        cur_x = self.root.winfo_x()
        cur_y = self.root.winfo_y()
        self.root.geometry(f"{new_w}x{new_h}+{cur_x}+{cur_y}")
        
        # 如果封面设置有变化，实时重建封面区域
        cover_changed = (new_cover_size != old_cover_size or new_show != old_show)
        if cover_changed:
            self.thumbnail_size = new_cover_size
            self.show_thumbnail = new_show
            self._rebuild_cover_area()
            # 强制重新获取封面
            self.last_track_key = None
            if self.current_info['mode'] == 'auto':
                self.root.after(100, self.manual_refresh)
        
        # 保存配置
        self.save_config()
        
        # 提示
        messagebox.showinfo("提示", "设置已应用！\n部分外观设置（字体大小等）需重启生效。", parent=dialog)
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="刷新", command=self.manual_refresh)
        menu.add_command(label="编辑", command=self.open_edit_dialog)
        menu.add_separator()
        menu.add_command(label="设置", command=self.open_settings_dialog)
        menu.add_separator()
        menu.add_command(label="退出", command=self.on_closing)
        menu.post(event.x_root, event.y_root)
    
    def on_closing(self):
        """关闭窗口"""
        self.stop_auto_update()
        self.save_config()
        self.root.destroy()
    
    def run(self):
        """运行程序"""
        self.root.mainloop()


def main():
    app = MusicDisplayGUI()
    app.run()


if __name__ == "__main__":
    main()
