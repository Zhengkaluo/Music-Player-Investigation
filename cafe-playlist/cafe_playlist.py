#!/usr/bin/env python3
"""
☕ 咖啡店歌单自动编排系统 - CLI 主入口

用法:
    python cafe_playlist.py import --csv 数据.csv       导入 Notion CSV 数据
    python cafe_playlist.py import --json 数据.json     导入 JSON 数据
    python cafe_playlist.py auto-url                    自动搜索补全 QQ 音乐 URL + 时长
    python cafe_playlist.py fetch-duration              批量抓取专辑时长
    python cafe_playlist.py fetch-duration --name "xxx" 抓取单张专辑时长
    python cafe_playlist.py generate                    生成今日歌单
    python cafe_playlist.py generate --date 2026-04-23  生成指定日期歌单
    python cafe_playlist.py generate --prefer "R&B,jazz" 带风格偏好生成
    python cafe_playlist.py show                        显示今日歌单
    python cafe_playlist.py show --date 2026-04-23      显示指定日期歌单
    python cafe_playlist.py week                        生成本周歌单(周一到周五)
    python cafe_playlist.py stats                       显示专辑库统计
    python cafe_playlist.py config                      显示当前配置
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 确保模块路径
sys.path.insert(0, str(Path(__file__).parent))

import album_db
import scheduler_engine


def cmd_import(args):
    """导入专辑数据"""
    merge = not args.replace
    mode_label = "合并模式（保留已有URL/时长）" if merge else "替换模式（全部覆盖）"
    
    if args.csv:
        print(f"📥 从 CSV 导入: {args.csv}")
        print(f"   模式: {mode_label}")
        try:
            new, updated, removed = album_db.import_from_csv(args.csv, merge=merge)
        except Exception as e:
            print(f"❌ 导入失败: {e}")
            return 1
    
    elif args.json_file:
        print(f"📥 从 JSON 导入: {args.json_file}")
        print(f"   模式: {mode_label}")
        try:
            new, updated, removed = album_db.import_from_json(args.json_file, merge=merge)
        except Exception as e:
            print(f"❌ 导入失败: {e}")
            return 1
    
    else:
        print("❌ 请指定 --csv 或 --json 参数")
        return 1
    
    # 详细输出
    print(f"\n✅ 导入完成:")
    if merge:
        print(f"    ➕ 新增: {new}")
        print(f"    🔄 更新(保留URL/时长): {updated}")
        if removed > 0:
            print(f"    🗑️  CSV中已删除: {removed}")
    else:
        print(f"    📦 全量写入: {new}")
    
    # 显示统计
    stats = album_db.get_album_stats()
    print(f"\n📊 专辑库现有 {stats['total']} 张专辑, "
          f"{stats['genre_count']} 种风格, "
          f"{stats['with_duration']} 有时长, "
          f"{stats['with_qq_url']} 有URL")
    
    # 如果合并后有新增且没有URL，提醒跑 auto-url
    if new > 0:
        no_url = stats['total'] - stats['with_qq_url']
        if no_url > 0:
            print(f"\n💡 有 {no_url} 张新专辑需要补全URL，运行:")
            print(f"   python cafe_playlist.py auto-url")
    
    return 0


def cmd_fetch_duration(args):
    """抓取专辑时长"""
    import duration_fetcher
    
    if args.name:
        print(f"🔍 抓取单张专辑时长: {args.name}")
        success = duration_fetcher.fetch_single_duration(args.name)
        return 0 if success else 1
    
    print("🔍 批量抓取专辑时长...")
    print(f"   强制重新抓取: {'是' if args.force else '否'}")
    print()
    
    success, fail, skip = duration_fetcher.fetch_all_durations(
        force=args.force,
        verbose=True
    )
    
    print(f"\n📊 抓取完成: ✅ {success} 成功, ❌ {fail} 失败, ⏭️ {skip} 跳过")
    
    return 0


def cmd_auto_url(args):
    """自动搜索补全 QQ 音乐 URL"""
    import duration_fetcher
    
    force = getattr(args, 'force', False)
    mode = "强制重新搜索所有" if force else "仅搜索缺失URL的"
    print(f"🔗 自动补全 QQ 音乐 URL（{mode}，同时抓取时长）...")
    print()
    
    found, not_found, skipped = duration_fetcher.auto_fill_urls(verbose=True, force=force)
    
    print(f"\n{'='*50}")
    print(f"📊 补全完成:")
    print(f"    ✅ 找到并补全: {found}")
    print(f"    ❌ QQ音乐未收录: {not_found}")
    print(f"    ⏭️  已有URL跳过: {skipped}")
    print(f"{'='*50}")
    
    return 0


def cmd_generate(args):
    """生成歌单"""
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    
    # 解析风格偏好
    style_prefs = None
    if args.prefer:
        style_prefs = [s.strip() for s in args.prefer.split(",") if s.strip()]
    
    seed = args.seed
    
    print(f"🎵 生成歌单: {date_str}")
    if style_prefs:
        print(f"   风格偏好: {', '.join(style_prefs)}")
    if seed is not None:
        print(f"   随机种子: {seed}")
    
    try:
        playlist = scheduler_engine.generate_playlist(
            date_str=date_str,
            style_overrides=style_prefs,
            seed=seed,
            verbose=True,
        )
        
        # 保存歌单
        filepath = scheduler_engine.save_playlist(playlist)
        print(f"\n💾 歌单已保存: {filepath}")
        
        # 更新播放历史
        if not args.dry_run:
            scheduler_engine.update_play_history(playlist)
            print("📝 播放历史已更新")
        else:
            print("📝 (dry-run 模式，未更新播放历史)")
        
        # 输出格式化歌单
        print(scheduler_engine.format_playlist(playlist))
        
    except Exception as e:
        print(f"❌ 生成失败: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


def cmd_show(args):
    """显示歌单"""
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    
    playlist = scheduler_engine.load_playlist(date_str)
    if not playlist:
        print(f"❌ 找不到 {date_str} 的歌单")
        print(f"   请先运行: python cafe_playlist.py generate --date {date_str}")
        return 1
    
    print(scheduler_engine.format_playlist(playlist))
    return 0


def cmd_week(args):
    """生成一周歌单（周一到周五）"""
    # 确定本周一的日期
    today = datetime.now()
    
    if args.start:
        try:
            start_date = datetime.strptime(args.start, "%Y-%m-%d")
        except ValueError:
            print(f"❌ 日期格式错误: {args.start}，请使用 YYYY-MM-DD")
            return 1
    else:
        # 默认从本周一开始
        start_date = today - timedelta(days=today.weekday())
    
    style_prefs = None
    if args.prefer:
        style_prefs = [s.strip() for s in args.prefer.split(",") if s.strip()]
    
    print(f"📅 生成一周歌单: {start_date.strftime('%Y-%m-%d')} ~ "
          f"{(start_date + timedelta(days=4)).strftime('%Y-%m-%d')}")
    if style_prefs:
        print(f"   风格偏好: {', '.join(style_prefs)}")
    
    weekdays = ["周一", "周二", "周三", "周四", "周五"]
    
    for i in range(5):
        day = start_date + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        
        print(f"\n{'='*60}")
        print(f"📅 {weekdays[i]} {date_str}")
        print(f"{'='*60}")
        
        try:
            playlist = scheduler_engine.generate_playlist(
                date_str=date_str,
                style_overrides=style_prefs,
                verbose=True,
            )
            
            filepath = scheduler_engine.save_playlist(playlist)
            
            if not args.dry_run:
                scheduler_engine.update_play_history(playlist)
            
            summary = playlist.get("summary", {})
            print(f"\n  ✅ {summary.get('total_albums', 0)} 张专辑, "
                  f"时长 {summary.get('actual_duration_display', '?')} "
                  f"({summary.get('fill_percentage', 0)}%)")
            
        except Exception as e:
            print(f"  ❌ {date_str} 生成失败: {e}")
    
    print(f"\n🎉 一周歌单生成完毕！")
    print(f"   歌单目录: {scheduler_engine.PLAYLISTS_DIR}")
    return 0


def cmd_stats(args):
    """显示专辑库统计"""
    stats = album_db.get_album_stats()
    
    if stats["total"] == 0:
        print("📊 专辑库为空，请先导入数据")
        return 0
    
    print(f"\n{'='*50}")
    print(f"📊 专辑库统计")
    print(f"{'='*50}")
    print(f"  总专辑数: {stats['total']}")
    print(f"  风格类型: {stats['genre_count']} 种")
    print(f"  地区: {', '.join(stats['regions'])}")
    print(f"  有时长数据: {stats['with_duration']}")
    print(f"  缺少时长: {stats['without_duration']}")
    print(f"  有QQ音乐链接: {stats['with_qq_url']}")
    
    # 噪音来源统计
    ns = stats.get("noise_sources", {})
    print(f"\n🔊 噪音程度来源:")
    print(f"    手动填写: {ns.get('manual', 0)}")
    print(f"    风格估算: {ns.get('estimated', 0)}")
    print(f"    默认值(4.0): {ns.get('default', 0)}")
    
    if stats.get("genres"):
        print(f"\n🎸 所有风格标签:")
        # 按行打印，每行 5 个
        genres = stats["genres"]
        for i in range(0, len(genres), 5):
            batch = genres[i:i+5]
            print(f"    {', '.join(batch)}")
    
    print(f"{'='*50}\n")
    return 0


def cmd_config(args):
    """显示当前配置"""
    try:
        config = scheduler_engine.load_config()
        print(f"\n{'='*50}")
        print(f"⚙️  编排配置")
        print(f"{'='*50}")
        print(json.dumps(config, ensure_ascii=False, indent=2))
        print(f"{'='*50}\n")
        print(f"📁 配置文件: {scheduler_engine.CONFIG_FILE}")
    except Exception as e:
        print(f"❌ 加载配置失败: {e}")
        return 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="☕ 咖啡店歌单自动编排系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="可用命令")
    
    # import 命令
    import_parser = subparsers.add_parser("import", help="导入专辑数据")
    import_parser.add_argument("--csv", help="Notion 导出的 CSV 文件路径")
    import_parser.add_argument("--json", dest="json_file", help="JSON 文件路径")
    import_parser.add_argument("--replace", action="store_true",
                               help="替换模式（默认为合并模式）")
    
    # fetch-duration 命令
    fetch_parser = subparsers.add_parser("fetch-duration", help="抓取专辑时长")
    fetch_parser.add_argument("--force", action="store_true",
                              help="强制重新抓取已有时长的专辑")
    fetch_parser.add_argument("--name", help="只抓取指定专辑")
    
    # auto-url 命令
    auto_url_parser = subparsers.add_parser("auto-url", help="自动搜索补全 QQ 音乐 URL 并抓取时长")
    auto_url_parser.add_argument("--force", action="store_true",
                                  help="强制重新搜索所有专辑（包括已有URL的）")
    
    # generate 命令
    gen_parser = subparsers.add_parser("generate", help="生成歌单")
    gen_parser.add_argument("--date", help="目标日期 (YYYY-MM-DD)，默认今天")
    gen_parser.add_argument("--prefer", help="风格偏好，逗号分隔 (如 R&B,jazz)")
    gen_parser.add_argument("--seed", type=int, help="随机种子（用于复现）")
    gen_parser.add_argument("--dry-run", action="store_true",
                            help="不更新播放历史")
    
    # show 命令
    show_parser = subparsers.add_parser("show", help="显示歌单")
    show_parser.add_argument("--date", help="日期 (YYYY-MM-DD)，默认今天")
    
    # week 命令
    week_parser = subparsers.add_parser("week", help="生成一周歌单")
    week_parser.add_argument("--start", help="起始日期 (YYYY-MM-DD)，默认本周一")
    week_parser.add_argument("--prefer", help="风格偏好，逗号分隔")
    week_parser.add_argument("--dry-run", action="store_true",
                             help="不更新播放历史")
    
    # stats 命令
    subparsers.add_parser("stats", help="显示专辑库统计")
    
    # config 命令
    subparsers.add_parser("config", help="显示当前配置")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 0
    
    cmd_map = {
        "import": cmd_import,
        "fetch-duration": cmd_fetch_duration,
        "auto-url": cmd_auto_url,
        "generate": cmd_generate,
        "show": cmd_show,
        "week": cmd_week,
        "stats": cmd_stats,
        "config": cmd_config,
    }
    
    handler = cmd_map.get(args.command)
    if handler:
        return handler(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
