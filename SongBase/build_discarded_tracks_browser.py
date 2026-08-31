#!/usr/bin/env python3
"""Build an offline browser for the canonical discarded-track archive."""

from __future__ import annotations

import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
SOURCE = BASE / "archive" / "removed_tracks" / "discarded_tracks.json"
OUTPUT = BASE / "archive" / "removed_tracks" / "discarded_tracks_browser.html"

TEMPLATE = r'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SongBase 归档舍弃</title><style>
:root{--bg:#151312;--panel:#211d1b;--panel2:#2a2421;--line:#453a34;--text:#f4ece6;--muted:#b8a79d;--accent:#e5a675;--red:#d9796f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}.shell{width:min(1280px,calc(100% - 28px));margin:auto;padding:30px 0 48px}h1{margin:0;font-size:clamp(28px,4vw,42px)}.sub{color:var(--muted);margin:8px 0 24px}.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:18px}.metric,.toolbar,.card{background:var(--panel);border:1px solid var(--line);border-radius:14px}.metric{padding:14px 16px}.metric strong{display:block;font-size:24px}.metric span,.meta{color:var(--muted);font-size:13px}.toolbar{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:10px;padding:12px;margin-bottom:16px}input,select,button{font:inherit;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px}button{cursor:pointer}.result{color:var(--muted);margin:0 0 10px}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(310px,1fr));gap:10px}.card{padding:15px}.title{font-weight:750;font-size:16px}.artist{color:var(--accent);font-size:13px}.tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}.tag{border:1px solid var(--line);border-radius:999px;padding:2px 8px;font-size:12px;color:var(--muted)}.tag.audio{color:var(--accent);border-color:#76553f}.tag.formal{color:#d6c78d}.links{display:flex;gap:7px;margin-top:12px}.links a{text-decoration:none;color:var(--muted);border:1px solid var(--line);border-radius:8px;padding:4px 8px;font-size:12px}.reason{margin-top:10px;color:var(--muted);font-size:12px}.empty{text-align:center;color:var(--muted);padding:48px}.footer{color:var(--muted);font-size:12px;margin-top:20px}@media(max-width:700px){.metrics{grid-template-columns:1fr 1fr}.toolbar{grid-template-columns:1fr 1fr}.toolbar input{grid-column:1/-1}}
</style></head><body><main class="shell"><h1>SongBase 归档舍弃</h1><p class="sub">已退出主曲库、正式标签、候选数据和主浏览页；保留于此供追溯与恢复。</p>
<section class="metrics"><div class="metric"><strong id="total">—</strong><span>舍弃曲目</span></div><div class="metric"><strong id="artists">—</strong><span>涉及艺人</span></div><div class="metric"><strong id="audio">—</strong><span>保留本地音频</span></div></section>
<section class="toolbar"><input id="search" type="search" placeholder="搜索歌曲、艺人、专辑…"><select id="artist"><option value="all">全部艺人</option></select><select id="audioFilter"><option value="all">全部音频状态</option><option value="yes">有归档音频</option><option value="no">无归档音频</option></select><button id="clear">清除</button></section>
<p class="result" id="result"></p><section id="list"></section><p class="footer">数据来自 discarded_tracks.json；此页面只读。</p></main>
<script>const DATA=__DATA__;const tracks=Object.values(DATA.tracks||{});const $=id=>document.getElementById(id);const esc=v=>String(v??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
function render(){const q=$('search').value.trim().toLocaleLowerCase(),artist=$('artist').value,audio=$('audioFilter').value;const rows=tracks.filter(t=>{const has=(t.archived_audio||[]).length>0;if(q&&![t.title,t.artist,t.album,t.full_singer].join(' ').toLocaleLowerCase().includes(q))return false;if(artist!=='all'&&t.artist!==artist)return false;if(audio==='yes'&&!has)return false;if(audio==='no'&&has)return false;return true}).sort((a,b)=>a.artist.localeCompare(b.artist)||a.title.localeCompare(b.title));$('result').textContent=`显示 ${rows.length} / ${tracks.length} 首`;$('list').innerHTML=rows.length?`<div class="grid">${rows.map(t=>{const formal=t.former_formal_tag,hasAudio=(t.archived_audio||[]).length>0;return `<article class="card"><div class="title">${esc(t.title)}</div><div class="artist">${esc(t.artist)}</div><div class="meta">${esc(t.album||'未标注专辑')} · ${esc(t.id)} · ${esc(t.discarded_at||'历史记录')}</div><div class="tags">${hasAudio?'<span class="tag audio">有归档音频</span>':''}${formal?`<span class="tag formal">原主标签：${esc(formal.genre)}</span>`:''}${t.former_candidate?.genre_candidate?`<span class="tag">原候选：${esc(t.former_candidate.genre_candidate)}</span>`:''}</div><div class="reason">${esc(t.reason||'人工复核舍弃')}</div><div class="links">${(t.archived_audio||[]).map((file,index)=>`<a href="${encodeURIComponent(file)}" target="_blank">本地音频${t.archived_audio.length>1?` ${index+1}`:''}</a>`).join('')}${t.qq_music?`<a href="${esc(t.qq_music)}" target="_blank" rel="noopener">QQ</a>`:''}${t.youtube?`<a href="${esc(t.youtube)}" target="_blank" rel="noopener">YouTube</a>`:''}</div></article>`}).join('')}</div>`:'<div class="empty">没有符合条件的归档曲目。</div>'}
function init(){const artists=[...new Set(tracks.map(t=>t.artist))].sort((a,b)=>a.localeCompare(b));$('total').textContent=tracks.length;$('artists').textContent=artists.length;$('audio').textContent=tracks.filter(t=>(t.archived_audio||[]).length).length;$('artist').innerHTML+=artists.map(a=>`<option value="${esc(a)}">${esc(a)}</option>`).join('');['search','artist','audioFilter'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));$('clear').addEventListener('click',()=>{$('search').value='';$('artist').value='all';$('audioFilter').value='all';render()});render()}init();</script></body></html>'''


def main() -> None:
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    if data.get("schema_version") != "songbase.discarded-tracks/v1":
        raise ValueError("discarded_tracks.json schema_version 无效")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    audio_count = sum(bool(track.get("archived_audio")) for track in data.get("tracks", {}).values())
    print(f"Built {OUTPUT.name}: {len(data.get('tracks', {}))} discarded, {audio_count} archived audio")


if __name__ == "__main__":
    main()
