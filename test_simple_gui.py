"""最小化GUI测试"""
import tkinter as tk
import subprocess
import json
from pathlib import Path

def get_music():
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
            return json.loads(result.stdout)
        return None
    except Exception as e:
        print(f"错误: {e}")
        return None

def update_label():
    info = get_music()
    if info and info.get('status') == 'success':
        title = info.get('title', '未知')
        artist = info.get('artist', '未知')
        album = info.get('album_title', '未知')
        status = info.get('playback_status', '')
        
        text = f"""标题: {title}
艺术家: {artist}
专辑: {album}
状态: {status}"""
        
        label.config(text=text)
        print(f"更新成功: {title}")
    else:
        label.config(text="获取失败")
    
    # 2秒后再次更新
    root.after(2000, update_label)

root = tk.Tk()
root.title("测试")
root.geometry("400x200")

label = tk.Label(
    root,
    text="正在获取...",
    font=("Microsoft YaHei UI", 12),
    justify=tk.LEFT,
    anchor=tk.W,
    padx=20,
    pady=20
)
label.pack(fill=tk.BOTH, expand=True)

# 立即更新一次
update_label()

root.mainloop()
