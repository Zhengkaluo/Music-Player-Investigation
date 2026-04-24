"""测试GUI调用方式"""
import subprocess
import json
from pathlib import Path

def test_get_music():
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
        
        print(f"returncode: {result.returncode}")
        print(f"stdout length: {len(result.stdout)}")
        print(f"stdout[:200]: {repr(result.stdout[:200])}")
        
        if result.returncode == 0 and result.stdout.strip():
            info = json.loads(result.stdout)
            print(f"\n解析成功:")
            print(f"  标题: {info.get('title')}")
            print(f"  艺术家: {info.get('artist')}")
            print(f"  专辑: {info.get('album_title')}")
            print(f"  状态: {info.get('playback_status')}")
            return info
        else:
            print("获取失败")
            return None
    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    print("=" * 60)
    print("测试 GUI 调用方式")
    print("=" * 60)
    test_get_music()
