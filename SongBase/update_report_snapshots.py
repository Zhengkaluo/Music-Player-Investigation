#!/usr/bin/env python3
"""Refresh report statistics and pending-task handling from current SongBase data."""
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def load(name):
    return json.loads((ROOT / name).read_text(encoding="utf-8"))

def main():
    library = load("song_base_by_artist.json")
    unique = {}
    raw = []
    for singer in library["singers"]:
        for song in singer["songs"]:
            identity = "qq:" + re.search(r"/songDetail/([A-Za-z0-9]+)", song["qq_music"]).group(1)
            raw.append(song)
            unique.setdefault(identity, (singer["name"], song))
    n = len(unique)
    all_tags = load("song_tags.json")["tracks"]
    tags = {k: v for k, v in all_tags.items() if k in unique}
    candidates = set(load("song_tag_candidates.json")["tracks"]) & unique.keys() - tags.keys()
    genres = Counter(t["genre"] for t in tags.values())
    instrumental = Counter(t.get("instrumental") for t in tags.values())
    languages = Counter(t.get("language") for t in tags.values() if t.get("language"))
    seconds = sum(song.get("duration", 0) for _, song in unique.values())
    albums = {(artist, song.get("album", "")) for artist, song in unique.values()}
    youtube = sum(bool(song.get("youtube")) for _, song in unique.values())
    audio_files = [p for p in (ROOT / "SongResources").iterdir() if p.is_file() and p.suffix.lower() in {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac"} and p.stat().st_size]
    pending = load("待录制清单.json").get("summary", {})
    lines = [
        "# SongBase 曲库风格、曲风与语种报告", "",
        f"> 更新日期：{date.today().isoformat()}。以当前主库 QQ MID 去重，正式标签与候选严格分开。", "",
        "## 当前规模", "",
        "| 指标 | 数量 |", "|---|---:|",
        f"| 去重歌曲 | {n:,} |", f"| 原始歌曲记录 | {len(raw):,} |",
        f"| 主艺人分组 | {len(library['singers']):,} |", f"| 主艺人 + 专辑名 | {len(albums):,} |",
        f"| 去重后总时长 | {seconds // 3600} 小时 {seconds % 3600 // 60} 分 |",
        f"| 有 YouTube 链接 | {youtube:,}（{youtube / n:.1%}） |",
        f"| 本地非空音频文件 | {len(audio_files):,} |",
        f"| 按主库身份匹配的本地可播曲目 | {pending.get('local_playable_tracks', 0):,} |",
        f"| 缺本地音源（QQ 已下架） | {pending.get('unavailable_tracks', 0):,} |",
        f"| 待录制 / 待入库 | {pending.get('remaining_to_record', 0):,} / {pending.get('recorded_awaiting_import', 0):,} |", "",
        "音频文件数不等于唯一可播曲目数，可能含额外版本或未纳入主库的文件；逐曲身份与阻塞状态见联合缺口清单。", "",
        "## Tag 覆盖", "",
        "| 状态 | 首数 | 占全库 |", "|---|---:|---:|",
        f"| 正式人工标签 | {len(tags):,} | {len(tags) / n:.1%} |",
        f"| 待复核候选（不含正式） | {len(candidates):,} | {len(candidates) / n:.1%} |",
        f"| 无正式标签或候选 | {n - len(tags) - len(candidates):,} | {(n - len(tags) - len(candidates)) / n:.1%} |", "",
        "## 正式主风格", "",
        "每首只按一个正式主风格计数，未标注曲目不推断。", "",
        "| 主风格 | 首数 | 占正式标签 | 占全库 |", "|---|---:|---:|---:|",
    ]
    for genre, count in genres.most_common():
        lines.append(f"| {genre} | {count} | {count / len(tags):.1%} | {count / n:.1%} |")
    lines += ["", "## 器乐性与语种", "", "| 器乐性 | 首数 | 占正式标签 |", "|---|---:|---:|"]
    for value, label in [(True, "已确认纯音乐"), (False, "已确认非器乐"), (None, "尚未标注")]:
        count = instrumental[value]
        lines.append(f"| {label} | {count} | {count / len(tags):.1%} |")
    lines += ["", "| 已确认语种 | 首数 |", "|---|---:|"]
    for language, count in languages.most_common():
        lines.append(f"| {language} | {count} |")
    lines += ["", f"语种确认 {sum(languages.values())} 首，其余 {len(tags) - sum(languages.values())} 首正式标签为空或不适用。空值不代表中文、英文或纯音乐，也不根据艺人国籍或曲名推断。", "",
        "## 解读与限制", "",
        f"正式 Tag 覆盖 {len(tags) / n:.1%}，当前核心仍以氛围／现代古典、Hip-Hop / R&B、爵士／灵魂为主。风格分布只描述已确认部分，不能替代未标注歌曲的人工判断。", "",
        "ZMPD 人工标注、模型预测和直接衔接证据是不同数据层，不因已有 Tag 就视为已完成其他测试。待重录音源不进入可立即补标队列，待舍弃清单仅登记任务，不代表已执行归档。", "",
        "本报告仅统计正式标签中的显式器乐性和语种字段。所有数据来自本次本地快照，不代表未来最终覆盖。", ""]
    (ROOT / "曲库风格与语种报告.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"songbase": n, "formal_tags": len(tags), "candidates": len(candidates), "untagged": n - len(tags) - len(candidates)}, ensure_ascii=False))

if __name__ == "__main__":
    main()
