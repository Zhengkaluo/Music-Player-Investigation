"""同步本地歌单到 QQ 音乐.

用法:
    python qq_sync.py                    # 同步今天的歌单
    python qq_sync.py --date 2026-04-22  # 同步指定日期
    python qq_sync.py --dry-run          # 只预览不实际创建
    python qq_sync.py --list             # 列出已创建的歌单
"""

import asyncio
import json
import sys
import time
from datetime import date
from pathlib import Path

# ── 路径 ──────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
PLAYLISTS_DIR = Path(__file__).parent / "playlists"
CREDENTIAL_FILE = DATA_DIR / "qq_credential.json"
SONG_ID_CACHE_FILE = DATA_DIR / "song_id_cache.json"

# ── song_id 缓存 ─────────────────────────────
def load_song_id_cache() -> dict:
    """加载 album_mid -> [{song_id, song_type, name, interval}, ...] 的缓存."""
    if SONG_ID_CACHE_FILE.exists():
        return json.loads(SONG_ID_CACHE_FILE.read_text(encoding="utf-8"))
    return {}

def save_song_id_cache(cache: dict):
    """保存 song_id 缓存."""
    SONG_ID_CACHE_FILE.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


async def fetch_song_ids_for_album(client, album_mid: str) -> list[dict]:
    """通过 album_mid 获取专辑所有歌曲的 song_id.
    
    Returns:
        [{"song_id": int, "song_type": int, "name": str, "interval": int}, ...]
    """
    resp = await client.album.get_song(album_mid, num=100)
    songs = []
    for song in resp.song_list:
        songs.append({
            "song_id": song.id,
            "song_type": song.type,
            "name": song.name,
            "interval": song.interval,
        })
    return songs


def load_albums_db() -> dict[str, dict]:
    """加载专辑数据库，按名称索引."""
    albums = json.loads((DATA_DIR / "albums.json").read_text(encoding="utf-8"))
    return {a["name"]: a for a in albums}


async def ensure_all_song_ids(client, playlist_data: dict, albums_db: dict) -> dict[str, list[dict]]:
    """确保歌单中所有专辑的 song_id 都已缓存.
    
    Returns:
        album_mid -> song list 的映射
    """
    cache = load_song_id_cache()
    
    # 收集歌单中所有 album_mid（通过名称从数据库反查）
    needed_mids = set()
    name_to_mid = {}
    for slot in playlist_data["slots"]:
        for album in slot["albums"]:
            name = album["name"]
            db_entry = albums_db.get(name, {})
            mid = db_entry.get("qq_music_album_mid", "")
            if mid:
                needed_mids.add(mid)
                name_to_mid[name] = mid
    
    # 检查哪些还没缓存
    missing = [mid for mid in needed_mids if mid not in cache]
    
    if missing:
        print(f"  需要获取 {len(missing)} 张专辑的歌曲 ID...")
        for i, mid in enumerate(missing, 1):
            print(f"    [{i}/{len(missing)}] 获取 {mid}...")
            try:
                songs = await fetch_song_ids_for_album(client, mid)
                cache[mid] = songs
                print(f"      ✅ {len(songs)} 首歌")
                if i < len(missing):
                    await asyncio.sleep(0.3)
            except Exception as e:
                print(f"      ❌ 获取失败: {e}")
                cache[mid] = []
        
        save_song_id_cache(cache)
        print(f"  歌曲 ID 缓存已更新")
    else:
        print(f"  ✅ 所有 {len(needed_mids)} 张专辑的歌曲 ID 已缓存")
    
    return {mid: cache.get(mid, []) for mid in needed_mids}, name_to_mid


def build_song_list_for_playlist(playlist_data: dict, song_id_map: dict, name_to_mid: dict) -> list[tuple[int, int]]:
    """按歌单顺序构建 (song_id, song_type) 列表.
    
    按时段顺序遍历，每个专辑的所有歌曲按原始顺序加入。
    """
    song_list = []
    seen = set()  # 去重（同一首歌可能在不同时段出现）
    
    for slot in playlist_data["slots"]:
        for album in slot["albums"]:
            mid = name_to_mid.get(album["name"], "")
            if not mid or mid not in song_id_map:
                continue
            
            for song in song_id_map[mid]:
                key = (song["song_id"], song["song_type"])
                if key not in seen:
                    song_list.append(key)
                    seen.add(key)
    
    return song_list


async def sync_playlist(target_date: str, dry_run: bool = False):
    """同步指定日期的歌单到 QQ 音乐."""
    from qqmusic_api import Client
    from qqmusic_api.models.request import Credential

    # 1. 加载凭证
    if not CREDENTIAL_FILE.exists():
        print("❌ 未找到凭证文件，请先运行 python qq_login.py 登录")
        return
    
    cred_data = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    credential = Credential(**cred_data)
    client = Client(credential=credential)
    
    # 检查凭证
    expired = await client.login.check_expired()
    if expired:
        print("❌ 凭证已过期，请重新运行 python qq_login.py 登录")
        return
    print("✅ 凭证有效")
    
    # 2. 加载本地歌单
    playlist_file = PLAYLISTS_DIR / f"{target_date}.json"
    if not playlist_file.exists():
        print(f"❌ 未找到 {target_date} 的歌单文件")
        print(f"   请先运行: python cafe_playlist.py generate --date {target_date}")
        return
    
    playlist_data = json.loads(playlist_file.read_text(encoding="utf-8"))
    summary = playlist_data["summary"]
    print(f"\n📋 歌单: {target_date}")
    print(f"   专辑数: {summary['total_albums']}")
    print(f"   时长:   {summary['actual_duration_display']}")
    
    # 加载专辑数据库
    albums_db = load_albums_db()
    
    # 3. 获取所有歌曲 ID
    print(f"\n🔍 获取歌曲 ID...")
    song_id_map, name_to_mid = await ensure_all_song_ids(client, playlist_data, albums_db)
    
    # 4. 构建歌曲列表
    song_list = build_song_list_for_playlist(playlist_data, song_id_map, name_to_mid)
    print(f"\n📝 歌曲列表: {len(song_list)} 首")
    
    # 显示预览
    print(f"\n{'='*50}")
    print(f"歌单预览:")
    print(f"{'='*50}")
    song_idx = 0
    for slot in playlist_data["slots"]:
        print(f"\n⏰ {slot['start']}-{slot['end']} ({slot['slot_name']})")
        for album in slot["albums"]:
            mid = name_to_mid.get(album["name"], "")
            songs = song_id_map.get(mid, [])
            db_entry = albums_db.get(album["name"], {})
            artist = db_entry.get("artist", "Unknown")
            print(f"   💿 {album['name']} - {artist} ({len(songs)} 首)")
            for s in songs:
                song_idx += 1
                print(f"      {song_idx:3d}. {s['name']} ({s['interval']}s) [id:{s['song_id']}]")
    
    if dry_run:
        print(f"\n🏷️  [DRY RUN] 不会实际创建歌单")
        return
    
    # 5. 创建 QQ 音乐歌单
    playlist_name = f"☕ 咖啡店 {target_date}"
    print(f"\n🎵 正在创建歌单: {playlist_name}")
    
    try:
        result = await client.songlist.create(playlist_name)
        dirid = result.dirid
        tid = result.id
        print(f"   ✅ 歌单创建成功!")
        print(f"   dirid: {dirid}")
        print(f"   tid:   {tid}")
        print(f"   name:  {result.name}")
    except Exception as e:
        print(f"   ❌ 创建歌单失败: {e}")
        return
    
    # 6. 批量添加歌曲（每批最多 50 首，避免请求过大）
    BATCH_SIZE = 50
    total = len(song_list)
    success_count = 0
    
    for i in range(0, total, BATCH_SIZE):
        batch = song_list[i:i+BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (total + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"   添加歌曲 [{batch_num}/{total_batches}] ({len(batch)} 首)...")
        
        try:
            ok = await client.songlist.add_songs(dirid, batch, tid=tid)
            if ok:
                success_count += len(batch)
                print(f"      ✅ 成功")
            else:
                print(f"      ⚠️ 部分失败")
        except Exception as e:
            print(f"      ❌ 失败: {e}")
        
        if i + BATCH_SIZE < total:
            await asyncio.sleep(0.5)
    
    # 7. 完成
    print(f"\n{'='*50}")
    print(f"🎉 同步完成!")
    print(f"   歌单名称: {playlist_name}")
    print(f"   添加歌曲: {success_count}/{total}")
    print(f"   QQ 音乐歌单 ID: {tid}")
    print(f"{'='*50}")
    
    # 保存同步记录
    sync_record = {
        "date": target_date,
        "playlist_name": playlist_name,
        "dirid": dirid,
        "tid": tid,
        "total_songs": total,
        "success_songs": success_count,
        "synced_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    
    # 追加到同步记录文件
    sync_log_file = DATA_DIR / "sync_log.json"
    if sync_log_file.exists():
        sync_log = json.loads(sync_log_file.read_text(encoding="utf-8"))
    else:
        sync_log = []
    sync_log.append(sync_record)
    sync_log_file.write_text(json.dumps(sync_log, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    args = sys.argv[1:]
    
    dry_run = "--dry-run" in args
    
    # 确定日期
    target_date = None
    if "--date" in args:
        idx = args.index("--date")
        if idx + 1 < len(args):
            target_date = args[idx + 1]
    
    if not target_date:
        target_date = date.today().isoformat()
    
    print(f"🔄 同步歌单到 QQ 音乐")
    print(f"   日期: {target_date}")
    if dry_run:
        print(f"   模式: DRY RUN (不实际操作)")
    print()
    
    asyncio.run(sync_playlist(target_date, dry_run=dry_run))


if __name__ == "__main__":
    main()
