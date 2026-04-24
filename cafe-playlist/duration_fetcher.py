"""
QQ 音乐专辑时长抓取模块
- 从专辑 URL 解析 album mid
- 调用 QQ 音乐 API 获取曲目列表和时长
- 支持按专辑名搜索匹配
- 含请求限速和错误重试
"""

import json
import re
import time
import random
from typing import Optional
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

import album_db


# ─── QQ 音乐 API 端点 ───

# 专辑详情接口（无需登录）
ALBUM_DETAIL_URL = "https://c.y.qq.com/v8/fcg-bin/fcg_v8_album_detail_cp.fcg"

# 搜索接口
SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"

# 专辑信息接口（新版）
ALBUM_INFO_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"

# 通用请求头
HEADERS = {
    "Referer": "https://y.qq.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
}


def _check_requests():
    """检查 requests 库是否可用"""
    if not HAS_REQUESTS:
        raise RuntimeError(
            "需要安装 requests 库。请运行: pip install requests"
        )


def _random_delay(min_sec=1.0, max_sec=2.5):
    """随机延迟，防止请求过快被封"""
    time.sleep(random.uniform(min_sec, max_sec))


# ─── 专辑 MID 解析 ───


def extract_album_mid_from_url(url: str) -> Optional[str]:
    """
    从 QQ 音乐 URL 中提取 album mid。
    支持多种 URL 格式。
    """
    if not url:
        return None

    # https://y.qq.com/n/ryqq/albumDetail/003Ow85E3pnoqi
    m = re.search(r"albumDetail/(\w+)", url)
    if m:
        return m.group(1)

    # https://i.y.qq.com/v8/playsong.html?... &album_mid=XXX
    m = re.search(r"album_mid=(\w+)", url)
    if m:
        return m.group(1)

    # 短链接 c6.y.qq.com/base/... 需要跟随重定向
    if "c6.y.qq.com" in url or "c.y.qq.com" in url:
        return _resolve_short_url(url)

    return None


def _resolve_short_url(url: str) -> Optional[str]:
    """解析 QQ 音乐短链接，提取实际的 album mid"""
    _check_requests()
    try:
        # 确保 URL 有协议
        if not url.startswith("http"):
            url = "https://" + url
        resp = requests.head(url, headers=HEADERS, allow_redirects=True, timeout=10)
        final_url = resp.url
        m = re.search(r"albumDetail/(\w+)", final_url)
        if m:
            return m.group(1)
        m = re.search(r"album_mid=(\w+)", final_url)
        if m:
            return m.group(1)
    except Exception as e:
        print(f"  ⚠️ 解析短链接失败 {url}: {e}")
    return None


# ─── API 调用 ───


def fetch_album_detail_by_mid(album_mid: str) -> Optional[dict]:
    """
    通过 album mid 获取专辑详情（曲目列表和时长）。
    
    Returns:
        {
            "album_name": str,
            "singer": str,
            "total_tracks": int,
            "duration_seconds": int,
            "tracks": [{"name": str, "duration": int}, ...]
        }
        或 None（失败时）
    """
    _check_requests()
    
    # 方式 1：使用新版 musicu.fcg 接口
    result = _fetch_via_musicu(album_mid)
    if result:
        return result

    # 方式 2：使用旧版 fcg_v8_album_detail_cp 接口
    result = _fetch_via_legacy(album_mid)
    if result:
        return result

    return None


def _fetch_via_musicu(album_mid: str) -> Optional[dict]:
    """通过新版 musicu.fcg 接口获取专辑详情"""
    try:
        payload = {
            "albumSonglist": {
                "module": "music.musichallAlbum.AlbumSongList",
                "method": "GetAlbumSongList",
                "param": {
                    "albumMid": album_mid,
                    "begin": 0,
                    "num": 100,
                    "order": 2,
                }
            },
            "albumInfo": {
                "module": "music.musichallAlbum.AlbumInfoServer",
                "method": "GetAlbumDetail",
                "param": {
                    "albumMid": album_mid,
                }
            }
        }

        resp = requests.post(
            ALBUM_INFO_URL,
            json=payload,
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()

        # 提取专辑信息
        album_info = data.get("albumInfo", {}).get("data", {}).get("basicInfo", {})
        album_name = album_info.get("albumName", "")
        singer_name = album_info.get("singerName", "")

        # 提取曲目列表
        song_list_data = data.get("albumSonglist", {}).get("data", {})
        songs = song_list_data.get("songList", [])
        
        if not songs:
            return None

        tracks = []
        total_duration = 0
        for song_item in songs:
            song_info = song_item.get("songInfo", {})
            name = song_info.get("name", song_info.get("title", "未知"))
            interval = song_info.get("interval", 0)
            tracks.append({"name": name, "duration": interval})
            total_duration += interval

        return {
            "album_name": album_name,
            "singer": singer_name,
            "total_tracks": len(tracks),
            "duration_seconds": total_duration,
            "tracks": tracks,
        }

    except Exception as e:
        print(f"  ⚠️ musicu 接口请求失败: {e}")
        return None


def _fetch_via_legacy(album_mid: str) -> Optional[dict]:
    """通过旧版 fcg_v8_album_detail_cp 接口获取专辑详情"""
    try:
        params = {
            "albummid": album_mid,
            "g_tk": "5381",
            "jsonpCallback": "",
            "loginUin": "0",
            "hostUin": "0",
            "format": "json",
            "inCharset": "utf8",
            "outCharset": "utf-8",
            "notice": "0",
            "platform": "yqq.json",
            "needNewCode": "0",
        }

        resp = requests.get(
            ALBUM_DETAIL_URL,
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()

        if data.get("code") != 0:
            return None

        album_data = data.get("data", {})
        songs = album_data.get("list", [])
        
        if not songs:
            return None

        album_name = album_data.get("name", "")
        singer_info = album_data.get("singername", "")

        tracks = []
        total_duration = 0
        for song in songs:
            name = song.get("songname", "未知")
            interval = song.get("interval", 0)
            tracks.append({"name": name, "duration": interval})
            total_duration += interval

        return {
            "album_name": album_name,
            "singer": singer_info,
            "total_tracks": len(tracks),
            "duration_seconds": total_duration,
            "tracks": tracks,
        }

    except Exception as e:
        print(f"  ⚠️ legacy 接口请求失败: {e}")
        return None


def _normalize_for_compare(s: str) -> str:
    """标准化字符串用于比较：小写、去空格、去标点"""
    s = s.lower().strip()
    # 去掉常见标点和空格
    for ch in " -_.'\"!?()（）【】，。、":
        s = s.replace(ch, "")
    return s


def _album_name_matches(search_name: str, result_name: str) -> bool:
    """判断搜索结果的专辑名是否与期望匹配"""
    a = _normalize_for_compare(search_name)
    b = _normalize_for_compare(result_name)
    if not a or not b:
        return False
    # 精确匹配
    if a == b:
        return True
    # 包含匹配（短名字被包含在长名字中）
    if a in b or b in a:
        return True
    return False


def _artist_matches(search_artist: str, result_singer: str) -> bool:
    """判断搜索结果的艺人是否与期望匹配"""
    if not search_artist or not result_singer:
        return False
    a = _normalize_for_compare(search_artist)
    b = _normalize_for_compare(result_singer)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return False


def _pick_best_album(album_list: list, album_name: str, artist: str = "") -> Optional[str]:
    """
    从搜索结果列表中挑选最匹配的专辑。
    优先级：
    1. 专辑名 + 艺人名 都匹配
    2. 艺人名匹配（专辑名可能有差异）
    3. 专辑名匹配
    4. 都不匹配则返回 None
    """
    if not album_list:
        return None
    
    best_both = None      # 专辑名+艺人都匹配
    best_artist = None    # 只有艺人匹配
    best_name = None      # 只有专辑名匹配
    
    for item in album_list:
        mid = item.get("albumMid", item.get("album_mid", item.get("albumMID")))
        if not mid:
            continue
        
        result_name = item.get("albumName", item.get("album_name", ""))
        # 艺人可能在不同字段
        result_singer = ""
        singers = item.get("singer_list", item.get("singerList", []))
        if singers and isinstance(singers, list):
            result_singer = " ".join(s.get("name", s.get("singer_name", "")) for s in singers)
        if not result_singer:
            result_singer = item.get("singerName", item.get("singer_name", ""))
        
        name_ok = _album_name_matches(album_name, result_name)
        artist_ok = _artist_matches(artist, result_singer) if artist else False
        
        if name_ok and artist_ok and not best_both:
            best_both = mid
        elif artist_ok and not best_artist:
            best_artist = mid
        elif name_ok and not best_name:
            best_name = mid
    
    # 按优先级返回
    if best_both:
        return best_both
    if best_artist:
        return best_artist
    if best_name:
        return best_name
    
    return None


def search_album(album_name: str, artist: str = "") -> Optional[str]:
    """
    通过专辑名（+艺术家名）搜索 QQ 音乐，返回最匹配的 album mid。
    搜索策略：
    1. "专辑名 艺人名" 精确搜索
    2. 仅 "艺人名 专辑名" 搜索（换顺序）
    3. 仅 "专辑名" 搜索
    4. 旧版接口兜底
    5. 歌曲搜索兜底（从歌曲结果反查专辑）
    """
    _check_requests()
    
    # 策略1: 专辑名+艺人名
    if artist:
        mid = _search_album_new(album_name, artist, f"{album_name} {artist}")
        if mid:
            return mid
        # 策略2: 换顺序
        mid = _search_album_new(album_name, artist, f"{artist} {album_name}")
        if mid:
            return mid
    
    # 策略3: 仅专辑名
    mid = _search_album_new(album_name, artist, album_name)
    if mid:
        return mid
    
    # 策略4: 旧版接口
    mid = _search_album_legacy(album_name, artist)
    if mid:
        return mid
    
    # 策略5: 歌曲搜索兜底
    if artist:
        mid = _search_via_song(album_name, artist)
        if mid:
            return mid
    
    return None


def _search_via_song(album_name: str, artist: str) -> Optional[str]:
    """
    通过歌曲搜索找到匹配的专辑 mid。
    先搜艺人名，从结果中找到专辑名匹配的。
    """
    try:
        # 先搜 "艺人名"
        for query in [artist, f"{artist} {album_name}"]:
            payload = {
                "music.search.SearchCgiService": {
                    "method": "DoSearchForQQMusicDesktop",
                    "module": "music.search.SearchCgiService",
                    "param": {
                        "query": query,
                        "search_type": 0,  # 0 = 歌曲搜索
                        "num_per_page": 20,
                        "page_num": 1,
                    }
                }
            }
            
            resp = requests.post(
                ALBUM_INFO_URL,
                json=payload,
                headers=HEADERS,
                timeout=15,
            )
            data = resp.json()
            
            search_data = data.get("music.search.SearchCgiService", {}).get("data", {})
            song_list = search_data.get("body", {}).get("song", {}).get("list", [])
            
            if not song_list:
                continue
            
            # 从歌曲结果中找匹配的专辑
            for song in song_list:
                song_album = song.get("album", {})
                result_album_name = song_album.get("name", "")
                result_album_mid = song_album.get("mid", "")
                song_singers = [s.get("name", "") for s in song.get("singer", [])]
                result_singer = " ".join(song_singers)
                
                if not result_album_mid:
                    continue
                
                # 检查专辑名匹配
                if _album_name_matches(album_name, result_album_name):
                    # 再验证艺人
                    if _artist_matches(artist, result_singer):
                        return result_album_mid
            
            # 如果专辑名没精确匹配，但艺人匹配了，取第一个该艺人的专辑
            for song in song_list:
                song_album = song.get("album", {})
                result_album_name = song_album.get("name", "")
                result_album_mid = song_album.get("mid", "")
                song_singers = [s.get("name", "") for s in song.get("singer", [])]
                result_singer = " ".join(song_singers)
                
                if not result_album_mid:
                    continue
                
                if _artist_matches(artist, result_singer) and _album_name_matches(album_name, result_album_name):
                    return result_album_mid
            
            _random_delay(1.0, 2.0)
        
        return None
        
    except Exception as e:
        print(f"  ⚠️ 歌曲搜索失败: {e}")
        return None


def _search_album_new(album_name: str, artist: str, query: str) -> Optional[str]:
    """使用新版搜索接口搜索，并做智能匹配"""
    try:
        payload = {
            "music.search.SearchCgiService": {
                "method": "DoSearchForQQMusicDesktop",
                "module": "music.search.SearchCgiService",
                "param": {
                    "query": query,
                    "search_type": 8,  # 8 = 搜索专辑
                    "num_per_page": 10,
                    "page_num": 1,
                }
            }
        }

        resp = requests.post(
            ALBUM_INFO_URL,
            json=payload,
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()

        search_data = data.get("music.search.SearchCgiService", {}).get("data", {})
        album_list = search_data.get("body", {}).get("album", {}).get("list", [])

        if not album_list:
            return None

        return _pick_best_album(album_list, album_name, artist)

    except Exception as e:
        print(f"  ⚠️ 搜索接口失败: {e}")
        return None


def _search_album_legacy(album_name: str, artist: str = "") -> Optional[str]:
    """旧版搜索接口（兜底）"""
    try:
        query = album_name
        if artist:
            query = f"{album_name} {artist}"

        params = {
            "w": query,
            "format": "json",
            "p": 1,
            "n": 10,
            "t": 8,  # 搜索专辑
            "cr": 1,
            "g_tk": "5381",
        }

        resp = requests.get(
            SEARCH_URL,
            params=params,
            headers=HEADERS,
            timeout=15,
        )
        data = resp.json()

        albums = data.get("data", {}).get("album", {}).get("list", [])
        if not albums:
            return None

        # 也做智能匹配，不盲取第一个
        for item in albums:
            mid = item.get("albumMID")
            result_name = item.get("albumName", "")
            result_singer = item.get("singerName", item.get("singerName_hilight", ""))
            
            name_ok = _album_name_matches(album_name, result_name)
            artist_ok = _artist_matches(artist, result_singer) if artist else False
            
            if name_ok and artist_ok:
                return mid
            if artist_ok:
                return mid
            if name_ok:
                return mid
        
        return None

    except Exception as e:
        print(f"  ⚠️ 旧版搜索接口失败: {e}")
        return None


# ─── 批量抓取 ───


def fetch_all_durations(force: bool = False, verbose: bool = True):
    """
    批量抓取所有专辑的时长数据。
    
    Args:
        force: 强制重新抓取已有时长的专辑
        verbose: 是否打印详细进度
    
    Returns:
        (success_count, fail_count, skip_count)
    """
    _check_requests()
    
    albums = album_db.load_albums()
    if not albums:
        print("❌ 专辑库为空，请先导入数据")
        return 0, 0, 0
    
    success = 0
    fail = 0
    skip = 0
    total = len(albums)
    
    for i, album in enumerate(albums):
        name = album["name"]
        prefix = f"[{i+1}/{total}]"
        
        # 跳过已有时长的（除非 force）
        if album.get("duration_seconds") and not force:
            if verbose:
                dur_min = album["duration_seconds"] // 60
                print(f"  {prefix} ⏭️  {name} (已有时长 {dur_min}分钟)")
            skip += 1
            continue
        
        if verbose:
            print(f"  {prefix} 🔍 {name}...", end=" ", flush=True)
        
        # 1. 尝试从 URL 获取 album mid
        album_mid = album.get("qq_music_album_mid")
        
        if not album_mid and album.get("qq_music_url"):
            album_mid = extract_album_mid_from_url(album["qq_music_url"])
            if album_mid:
                album["qq_music_album_mid"] = album_mid
        
        # 2. 如果没有 mid，尝试搜索
        if not album_mid:
            if verbose:
                print("搜索中...", end=" ", flush=True)
            album_mid = search_album(name)
            if album_mid:
                album["qq_music_album_mid"] = album_mid
            _random_delay(1.0, 2.0)
        
        # 3. 如果有 mid，获取详情
        if album_mid:
            detail = fetch_album_detail_by_mid(album_mid)
            if detail and detail["duration_seconds"] > 0:
                album["duration_seconds"] = detail["duration_seconds"]
                album["tracks"] = detail["tracks"]
                dur_min = detail["duration_seconds"] // 60
                dur_sec = detail["duration_seconds"] % 60
                if verbose:
                    print(f"✅ {detail['total_tracks']}首 {dur_min}:{dur_sec:02d}")
                success += 1
            else:
                if verbose:
                    print("❌ 获取详情失败")
                fail += 1
        else:
            if verbose:
                print("❌ 找不到专辑")
            fail += 1
        
        _random_delay()
    
    # 保存更新后的数据
    album_db.save_albums(albums)
    
    return success, fail, skip


def fetch_single_duration(album_name: str, verbose: bool = True) -> bool:
    """
    抓取单张专辑的时长数据。
    
    Returns:
        是否成功
    """
    _check_requests()
    
    albums = album_db.load_albums()
    target = None
    target_idx = -1
    
    for i, a in enumerate(albums):
        if a["name"] == album_name:
            target = a
            target_idx = i
            break
    
    if target is None:
        print(f"❌ 找不到专辑: {album_name}")
        return False
    
    album_mid = target.get("qq_music_album_mid")
    
    if not album_mid and target.get("qq_music_url"):
        album_mid = extract_album_mid_from_url(target["qq_music_url"])
    
    if not album_mid:
        if verbose:
            print(f"  🔍 搜索 {album_name}...")
        album_mid = search_album(album_name)
    
    if not album_mid:
        print(f"  ❌ 找不到 QQ 音乐上的 {album_name}")
        return False
    
    detail = fetch_album_detail_by_mid(album_mid)
    if detail and detail["duration_seconds"] > 0:
        albums[target_idx]["duration_seconds"] = detail["duration_seconds"]
        albums[target_idx]["tracks"] = detail["tracks"]
        albums[target_idx]["qq_music_album_mid"] = album_mid
        album_db.save_albums(albums)
        
        dur_min = detail["duration_seconds"] // 60
        dur_sec = detail["duration_seconds"] % 60
        if verbose:
            print(f"  ✅ {album_name}: {detail['total_tracks']}首, 总时长 {dur_min}:{dur_sec:02d}")
        return True
    else:
        print(f"  ❌ 获取 {album_name} 详情失败")
        return False


def auto_fill_urls(verbose: bool = True, force: bool = False):
    """
    自动为专辑搜索并补全 QQ 音乐 URL + 时长。
    
    Args:
        verbose: 打印详细进度
        force: True 则重新搜索所有（包括已有URL的），False 则跳过已有的
    
    Returns:
        (found, not_found, skipped) — 找到的、没找到的、已有URL跳过的
    """
    _check_requests()
    
    albums = album_db.load_albums()
    if not albums:
        print("❌ 专辑库为空，请先导入数据")
        return 0, 0, 0
    
    found = 0
    not_found = 0
    skipped = 0
    not_found_names = []
    results_log = []  # 记录匹配详情
    total = len(albums)
    
    for i, album in enumerate(albums):
        name = album["name"]
        artist = album.get("artist", "")
        prefix = f"[{i+1}/{total}]"
        
        # 非 force 模式下跳过已有 URL 的
        if not force and album.get("qq_music_url"):
            if verbose:
                print(f"  {prefix} ⏭️  {name} (已有URL)")
            skipped += 1
            continue
        
        if verbose:
            search_hint = f"{name}"
            if artist:
                search_hint += f" - {artist}"
            print(f"  {prefix} 🔍 搜索 {search_hint}...", end=" ", flush=True)
        
        # 搜索专辑（传入艺人名）
        album_mid = search_album(name, artist)
        
        if album_mid:
            # 构建标准 URL
            url = f"https://y.qq.com/n/ryqq/albumDetail/{album_mid}"
            album["qq_music_url"] = url
            album["qq_music_album_mid"] = album_mid
            
            # 抓时长并验证
            detail = fetch_album_detail_by_mid(album_mid)
            if detail and detail["duration_seconds"] > 0:
                album["duration_seconds"] = detail["duration_seconds"]
                album["tracks"] = detail["tracks"]
                dur_min = detail["duration_seconds"] // 60
                dur_sec = detail["duration_seconds"] % 60
                matched_name = detail.get("album_name", "")
                matched_singer = detail.get("singer", "")
                if verbose:
                    print(f"✅ {matched_name} by {matched_singer} | {detail['total_tracks']}首 {dur_min}:{dur_sec:02d}")
                results_log.append({
                    "name": name, "artist": artist,
                    "matched_name": matched_name, "matched_singer": matched_singer,
                    "tracks": detail["total_tracks"], "duration": detail["duration_seconds"],
                })
            else:
                if verbose:
                    print(f"✅ URL已补全 (时长获取失败)")
                results_log.append({
                    "name": name, "artist": artist,
                    "matched_name": "?", "matched_singer": "?",
                    "tracks": 0, "duration": 0,
                })
            found += 1
        else:
            # 清空之前可能错误的 URL
            album["qq_music_url"] = None
            album["qq_music_album_mid"] = None
            album["duration_seconds"] = None
            album["tracks"] = None
            if verbose:
                print("❌ 未找到")
            not_found += 1
            not_found_names.append(f"{name} ({artist})" if artist else name)
        
        _random_delay(1.5, 3.0)
    
    # 保存
    album_db.save_albums(albums)
    
    if verbose and not_found_names:
        print(f"\n⚠️  以下专辑未在QQ音乐找到，需要手动处理:")
        for n in not_found_names:
            print(f"    - {n}")
    
    return found, not_found, skipped


if __name__ == "__main__":
    # 简单测试
    _check_requests()
    print("测试搜索: downt")
    mid = search_album("downt")
    if mid:
        print(f"  找到 mid: {mid}")
        detail = fetch_album_detail_by_mid(mid)
        if detail:
            print(f"  专辑: {detail['album_name']}")
            print(f"  曲目数: {detail['total_tracks']}")
            print(f"  总时长: {detail['duration_seconds'] // 60}分{detail['duration_seconds'] % 60}秒")
    else:
        print("  未找到")
