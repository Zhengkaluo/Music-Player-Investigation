"""
补全 albums.json 中不完整的专辑曲目。

对每张有 qq_music_album_mid 的专辑，调用 AlbumApi 拉取完整歌曲列表，
替换现有的 tracks 并更新 duration_seconds。

用法:
    python fill_album_tracks.py              # 补全所有不完整的
    python fill_album_tracks.py --all        # 强制重新拉取全部
    python fill_album_tracks.py --dry-run    # 只预览不写入
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path

# ── 路径 ──────────────────────────────────────
DATA_DIR = Path(__file__).parent / "data"
ALBUMS_FILE = DATA_DIR / "albums.json"
CREDENTIAL_FILE = DATA_DIR / "qq_credential.json"


async def fetch_album_songs(client, album_mid: str, page_size: int = 100):
    """获取专辑完整歌曲列表"""
    all_songs = []
    page = 1

    while True:
        resp = await client.album.get_song(album_mid, num=page_size, page=page)
        songs = resp.song_list
        total = resp.total_num
        all_songs.extend(songs)

        if len(all_songs) >= total or len(songs) == 0:
            break
        page += 1

    return all_songs, total


async def main():
    parser = argparse.ArgumentParser(description="补全 albums.json 中的专辑曲目")
    parser.add_argument("--all", action="store_true", help="强制重新拉取全部专辑")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写入")
    parser.add_argument("--delay", type=float, default=0.3, help="请求间隔秒数 (默认 0.3)")
    args = parser.parse_args()

    # 加载凭证
    from qqmusic_api import Client
    from qqmusic_api.models.request import Credential

    if not CREDENTIAL_FILE.exists():
        print("❌ 未找到凭证文件，请先运行 python qq_login.py 登录")
        sys.exit(1)

    cred_data = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    credential = Credential(**cred_data)
    client = Client(credential=credential)

    # 验证凭证
    expired = await client.login.check_expired()
    if expired:
        print("❌ 凭证已过期，请重新运行 python qq_login.py 登录")
        sys.exit(1)
    print("✅ 凭证有效\n")

    # 加载数据
    albums = json.loads(ALBUMS_FILE.read_text(encoding="utf-8"))
    print(f"📀 专辑库共 {len(albums)} 张专辑\n")

    # 筛选需要补全的
    to_fill = []
    for i, album in enumerate(albums):
        mid = album.get("qq_music_album_mid")
        if not mid:
            continue
        to_fill.append((i, album))

    print(f"🔍 需要检查的专辑: {len(to_fill)} 张\n")

    updated = 0
    skipped = 0
    failed = 0

    for idx, (album_idx, album) in enumerate(to_fill):
        mid = album["qq_music_album_mid"]
        name = album["name"]
        artist = album["artist"]
        old_track_count = len(album.get("tracks", []))

        try:
            songs, total = await fetch_album_songs(client, mid)

            if not args.all and len(songs) == old_track_count:
                skipped += 1
                continue

            # 构建新的 tracks
            new_tracks = []
            total_duration = 0
            for s in songs:
                # Song model 的时长字段
                duration = 0
                for attr in ("time_length", "duration", "interval"):
                    if hasattr(s, attr):
                        d = getattr(s, attr)
                        if d and d > 0:
                            duration = d
                            break

                track_name = s.name if hasattr(s, "name") else (s.title if hasattr(s, "title") else "Unknown")
                new_tracks.append({
                    "name": str(track_name),
                    "duration": duration
                })
                total_duration += duration

            old_duration = album.get("duration_seconds", 0)

            # 拉回 0 首的保留原数据
            if len(new_tracks) == 0:
                print(f"  [{idx+1}/{len(to_fill)}] ⚠️  {name} - {artist}: API 返回 0 首，保留原数据")
                skipped += 1
                continue

            print(f"  [{idx+1}/{len(to_fill)}] {name} - {artist}")
            print(f"    曲目: {old_track_count} → {len(new_tracks)}  |  时长: {old_duration//60:.0f}分 → {total_duration//60:.0f}分")

            # 更新
            albums[album_idx]["tracks"] = new_tracks
            albums[album_idx]["duration_seconds"] = total_duration
            updated += 1

        except Exception as e:
            print(f"  [{idx+1}/{len(to_fill)}] ❌ {name} - {artist}: {e}")
            failed += 1

        # 请求间隔
        if idx < len(to_fill) - 1:
            await asyncio.sleep(args.delay)

    print(f"\n{'='*60}")
    print(f"补全完成:")
    print(f"  更新: {updated} 张")
    print(f"  已完整跳过: {skipped} 张")
    print(f"  失败: {failed} 张")
    print(f"{'='*60}")

    if args.dry_run:
        print("\n🏷️  [DRY RUN] 不实际写入")
    elif updated > 0:
        ALBUMS_FILE.write_text(
            json.dumps(albums, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\n✅ 已保存到 albums.json")
    else:
        print("\n📌 无需更新")


if __name__ == "__main__":
    asyncio.run(main())
