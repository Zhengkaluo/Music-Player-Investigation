#!/usr/bin/env python3
"""从 QQ 音乐歌单批量导入专辑到 albums.json.

用法:
    python import_from_songlist.py <歌单ID>
    python import_from_songlist.py <歌单ID> --dry-run     # 只预览不写入
    python import_from_songlist.py <歌单ID> --page-size 50 # 自定义每页数量
"""

import asyncio
import json
import sys
from pathlib import Path
from collections import OrderedDict

# ── 路径 ──────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
ALBUMS_FILE = DATA_DIR / "albums.json"
CREDENTIAL_FILE = DATA_DIR / "qq_credential.json"


def load_albums() -> list[dict]:
    """加载现有专辑数据库."""
    if ALBUMS_FILE.exists():
        return json.loads(ALBUMS_FILE.read_text(encoding="utf-8"))
    return []


def save_albums(albums: list[dict]):
    """保存专辑数据库."""
    ALBUMS_FILE.write_text(
        json.dumps(albums, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def get_existing_album_mids(albums: list[dict]) -> set[str]:
    """获取已有专辑的 album_mid 集合."""
    mids = set()
    for a in albums:
        mid = a.get("qq_music_album_mid", "")
        if mid:
            mids.add(mid)
    return mids


def get_existing_album_names(albums: list[dict]) -> set[str]:
    """获取已有专辑名称集合 (小写比对)."""
    return {a["name"].lower() for a in albums}


async def fetch_songlist(songlist_id: int, page_size: int = 100) -> list:
    """分页获取歌单的所有歌曲.

    Returns:
        Song 对象列表
    """
    from qqmusic_api import Client
    from qqmusic_api.models.request import Credential

    # 加载凭证
    if not CREDENTIAL_FILE.exists():
        print("❌ 未找到凭证文件，请先运行 python qq_login.py 登录")
        sys.exit(1)

    cred_data = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    credential = Credential(**cred_data)
    client = Client(credential=credential)

    # 检查凭证
    expired = await client.login.check_expired()
    if expired:
        print("❌ 凭证已过期，请重新运行 python qq_login.py 登录")
        sys.exit(1)
    print("✅ 凭证有效")

    # 先获取第一页，得到歌单信息和总数
    print(f"\n🔍 获取歌单 {songlist_id} ...")
    resp = await client.songlist.get_detail(songlist_id, num=page_size, page=1)
    
    total = resp.total
    songs = list(resp.songs)
    songlist_name = resp.info.title
    
    print(f"   歌单名: {songlist_name}")
    print(f"   总歌曲: {total}")
    print(f"   第 1 页: 获取 {len(songs)} 首")

    # 分页获取剩余
    page = 2
    while len(songs) < total:
        await asyncio.sleep(0.3)
        resp = await client.songlist.get_detail(songlist_id, num=page_size, page=page)
        batch = resp.songs
        if not batch:
            break
        songs.extend(batch)
        print(f"   第 {page} 页: 获取 {len(batch)} 首 (累计 {len(songs)}/{total})")
        page += 1

    print(f"\n✅ 共获取 {len(songs)} 首歌曲")
    return songs, songlist_name


def group_by_album(songs) -> dict:
    """将歌曲按专辑分组.

    Returns:
        OrderedDict: album_mid -> {
            "album_name": str,
            "album_mid": str,
            "artist": str,
            "tracks": [{"name": str, "duration": int}, ...],
            "total_duration": int,
        }
    """
    albums = OrderedDict()

    for song in songs:
        album_mid = song.album.mid
        album_name = song.album.name

        # 跳过没有专辑信息的歌曲
        if not album_mid or not album_name:
            continue

        if album_mid not in albums:
            # 取第一个歌手名
            artist = song.singer[0].name if song.singer else "Unknown"
            albums[album_mid] = {
                "album_name": album_name,
                "album_mid": album_mid,
                "artist": artist,
                "tracks": [],
                "total_duration": 0,
            }

        albums[album_mid]["tracks"].append({
            "name": song.name,
            "duration": song.interval,
        })
        albums[album_mid]["total_duration"] += song.interval

    return albums


def build_album_entry(album_data: dict) -> dict:
    """构建 albums.json 格式的条目."""
    return {
        "name": album_data["album_name"],
        "artist": album_data["artist"],
        "genres": [],       # 待后续标注
        "region": "未知",    # 待后续标注
        "noise_level": None, # 待后续标注
        "noise_source": "pending",
        "swing_rate": None,
        "burden_level": None,
        "last_played": None,
        "qq_music_url": f"https://y.qq.com/n/ryqq/albumDetail/{album_data['album_mid']}",
        "qq_music_album_mid": album_data["album_mid"],
        "duration_seconds": album_data["total_duration"],
        "tracks": album_data["tracks"],
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser(description="从 QQ 音乐歌单导入专辑")
    parser.add_argument("songlist_id", type=int, help="QQ 音乐歌单 ID")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    parser.add_argument("--page-size", type=int, default=100, help="每页获取数量")
    args = parser.parse_args()

    # 1. 获取歌单
    songs, songlist_name = await fetch_songlist(args.songlist_id, args.page_size)

    # 2. 按专辑分组
    album_groups = group_by_album(songs)
    print(f"\n📀 共发现 {len(album_groups)} 张专辑:")

    # 3. 加载已有数据，过滤
    existing = load_albums()
    existing_mids = get_existing_album_mids(existing)
    existing_names = get_existing_album_names(existing)

    new_albums = []
    skipped_albums = []

    for mid, data in album_groups.items():
        name = data["album_name"]
        artist = data["artist"]
        tracks = len(data["tracks"])
        duration_min = data["total_duration"] / 60

        if mid in existing_mids:
            skipped_albums.append((name, artist, "mid 已存在"))
        elif name.lower() in existing_names:
            skipped_albums.append((name, artist, "名称已存在"))
        else:
            new_albums.append(data)
            print(f"   🆕 {name} - {artist} ({tracks} 首, {duration_min:.1f}分)")

    if skipped_albums:
        print(f"\n⏭️  跳过 {len(skipped_albums)} 张已有专辑:")
        for name, artist, reason in skipped_albums:
            print(f"   ➖ {name} - {artist} ({reason})")

    if not new_albums:
        print("\n✅ 没有新专辑需要导入")
        return

    # 4. 构建条目并追加
    print(f"\n📝 将导入 {len(new_albums)} 张新专辑")

    if args.dry_run:
        print("\n🏷️  [DRY RUN] 不实际写入")
        return

    new_entries = [build_album_entry(a) for a in new_albums]
    existing.extend(new_entries)
    save_albums(existing)

    print(f"\n✅ 已追加 {len(new_entries)} 张专辑到 albums.json")
    print(f"   当前专辑库总数: {len(existing)}")

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"导入摘要:")
    print(f"{'='*60}")
    print(f"   歌单:     {songlist_name} (ID: {args.songlist_id})")
    print(f"   发现专辑: {len(album_groups)}")
    print(f"   已有跳过: {len(skipped_albums)}")
    print(f"   新增导入: {len(new_entries)}")
    print(f"{'='*60}")

    # 列出需要后续标注的字段
    print(f"\n⚠️  以下新增专辑需要后续标注 genres / region / noise_level:")
    for entry in new_entries:
        print(f"   • {entry['name']} - {entry['artist']}")


if __name__ == "__main__":
    asyncio.run(main())
