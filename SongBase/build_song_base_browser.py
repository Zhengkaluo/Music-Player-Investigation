#!/usr/bin/env python3
"""Build a standalone, offline-friendly browser for SongBase."""

from __future__ import annotations

import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
SOURCE = BASE / "song_base_by_artist.json"
OUTPUT = BASE / "song_base_browser.html"


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SongBase 曲库浏览器</title>
  <style>
    :root { --bg:#101614; --panel:#17201d; --panel-2:#1d2925; --line:#2d3c36; --text:#edf3ee; --muted:#9aaca3; --accent:#c9dd87; --accent-ink:#1a240c; --warm:#e9b88c; --radius:16px; }
    * { box-sizing:border-box; }
    body { margin:0; background:var(--bg); color:var(--text); font:15px/1.5 ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; }
    button, input, select { font:inherit; }
    button, select { cursor:pointer; }
    a { color:inherit; }
    .shell { width:min(1440px, calc(100% - 32px)); margin:0 auto; padding:32px 0 52px; }
    .eyebrow { color:var(--accent); font-size:12px; letter-spacing:.12em; text-transform:uppercase; margin:0 0 8px; }
    h1 { margin:0; font-size:clamp(28px, 4vw, 42px); letter-spacing:-.035em; }
    .subhead { color:var(--muted); margin:8px 0 26px; }
    .metrics { display:grid; grid-template-columns:repeat(4, minmax(0,1fr)); gap:10px; margin-bottom:22px; }
    .metric { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius); padding:14px 16px; }
    .metric strong { display:block; font-size:23px; letter-spacing:-.03em; }
    .metric span { color:var(--muted); font-size:13px; }
    .toolbar { background:var(--panel); border:1px solid var(--line); border-radius:var(--radius); padding:14px; display:grid; grid-template-columns:minmax(230px,2fr) repeat(3,minmax(120px,1fr)) auto; gap:10px; }
    input, select { width:100%; color:var(--text); background:var(--panel-2); border:1px solid var(--line); border-radius:10px; padding:10px 12px; outline:none; }
    input:focus, select:focus { border-color:var(--accent); box-shadow:0 0 0 3px rgba(201,221,135,.12); }
    .button { background:transparent; color:var(--muted); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }
    .button:hover { color:var(--text); border-color:var(--muted); }
    .tabs { display:flex; gap:8px; margin:24px 0 14px; flex-wrap:wrap; }
    .tab { color:var(--muted); border:1px solid var(--line); background:transparent; border-radius:999px; padding:8px 14px; }
    .tab[aria-selected="true"] { color:var(--accent-ink); background:var(--accent); border-color:var(--accent); font-weight:700; }
    .result-bar { display:flex; justify-content:space-between; align-items:center; gap:16px; color:var(--muted); margin:0 0 12px; }
    .result-bar select { max-width:180px; padding:7px 10px; }
    .grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(280px, 1fr)); gap:10px; }
    details, .album-card { border:1px solid var(--line); background:var(--panel); border-radius:14px; overflow:hidden; }
    summary { list-style:none; cursor:pointer; padding:15px 16px; display:flex; gap:10px; justify-content:space-between; align-items:center; }
    summary::-webkit-details-marker { display:none; }
    .artist-name, .album-name { font-weight:700; overflow-wrap:anywhere; }
    .meta { color:var(--muted); font-size:13px; }
    .badge { flex:none; color:var(--accent); border:1px solid rgba(201,221,135,.38); padding:2px 8px; border-radius:999px; font-size:12px; }
    .track-list { border-top:1px solid var(--line); }
    .track { padding:11px 16px; display:grid; grid-template-columns:minmax(0,1fr) auto; gap:8px; align-items:center; border-top:1px solid rgba(45,60,54,.72); }
    .track:first-child { border-top:0; }
    .track-title { overflow-wrap:anywhere; }
    .track-album { color:var(--muted); font-size:12px; overflow-wrap:anywhere; }
    .links { display:flex; gap:7px; align-items:center; }
    .link { text-decoration:none; color:var(--muted); border:1px solid var(--line); border-radius:8px; padding:4px 7px; font-size:12px; white-space:nowrap; }
    .link:hover { color:var(--accent); border-color:var(--accent); }
    .album-card { padding:16px; }
    .album-card .track-list { margin:14px -16px -16px; }
    table { width:100%; border-collapse:collapse; border:1px solid var(--line); border-radius:14px; overflow:hidden; background:var(--panel); }
    th, td { text-align:left; padding:10px 12px; border-bottom:1px solid rgba(45,60,54,.72); vertical-align:top; }
    th { color:var(--muted); font-size:12px; font-weight:600; background:var(--panel-2); position:sticky; top:0; }
    tr:last-child td { border-bottom:0; }
    .table-wrap { overflow-x:auto; border-radius:14px; }
    .empty { color:var(--muted); padding:48px 0; text-align:center; }
    .footer { color:var(--muted); font-size:12px; margin-top:22px; }
    @media (max-width:780px) { .shell { width:min(100% - 20px, 1440px); padding-top:20px; } .metrics { grid-template-columns:repeat(2,1fr); } .toolbar { grid-template-columns:1fr 1fr; } .toolbar input { grid-column:1 / -1; } .toolbar .button { grid-column:1 / -1; } th:nth-child(3), td:nth-child(3) { display:none; } }
  </style>
</head>
<body>
  <main class="shell">
    <p class="eyebrow">Offline music library</p>
    <h1>SongBase 曲库浏览器</h1>
    <p id="subhead" class="subhead"></p>
    <section class="metrics" aria-label="曲库概览">
      <div class="metric"><strong id="metricSongs">—</strong><span>歌曲</span></div>
      <div class="metric"><strong id="metricArtists">—</strong><span>艺人</span></div>
      <div class="metric"><strong id="metricAlbums">—</strong><span>专辑</span></div>
      <div class="metric"><strong id="metricYoutube">—</strong><span>可用 YouTube</span></div>
    </section>
    <section class="toolbar" aria-label="筛选曲库">
      <input id="search" type="search" placeholder="搜索艺人、歌曲或专辑…" autocomplete="off">
      <select id="sourceFilter" aria-label="播放来源"><option value="all">全部播放来源</option><option value="youtube">有 YouTube</option><option value="no-youtube">无 YouTube</option></select>
      <select id="frequencyFilter" aria-label="艺人收录频率"><option value="all">全部艺人频率</option><option value="single">仅收录 1 首</option><option value="medium">收录 2–4 首</option><option value="frequent">收录 5 首以上</option></select>
      <select id="durationFilter" aria-label="歌曲时长"><option value="all">全部时长</option><option value="short">3 分钟以内</option><option value="medium">3–6 分钟</option><option value="long">6 分钟以上</option></select>
      <button class="button" id="clearFilters" type="button">清除筛选</button>
    </section>
    <nav class="tabs" aria-label="浏览方式">
      <button class="tab" type="button" data-view="artists" aria-selected="true">艺人</button>
      <button class="tab" type="button" data-view="albums" aria-selected="false">专辑</button>
      <button class="tab" type="button" data-view="songs" aria-selected="false">歌曲</button>
    </nav>
    <section class="result-bar"><span id="resultCount"></span><select id="sort" aria-label="排序"></select></section>
    <section id="results" aria-live="polite"></section>
    <p class="footer">数据来自 song_base_by_artist.json；页面为离线快照，更新 JSON 后重新运行构建程序即可刷新。</p>
  </main>
  <script>
    const LIBRARY = __LIBRARY_JSON__;
    const allArtists = LIBRARY.singers || [];
    const allSongs = allArtists.flatMap(group => group.songs.map(song => ({...song, artist:group.name, artistSongCount:group.song_count})));
    const $ = id => document.getElementById(id);
    const state = { view:'artists', search:'', source:'all', frequency:'all', duration:'all' };

    function escapeHtml(value) { return String(value ?? '').replace(/[&<>'"]/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char])); }
    function duration(seconds) { const mins=Math.floor(seconds/60); return `${mins}:${String(seconds%60).padStart(2,'0')}`; }
    function hasYoutube(song) { return Boolean(song.youtube); }
    function matches(song) {
      const needle = state.search.trim().toLocaleLowerCase();
      if (needle && ![song.title, song.artist, song.full_singer, song.album].join(' ').toLocaleLowerCase().includes(needle)) return false;
      if (state.source === 'youtube' && !hasYoutube(song)) return false;
      if (state.source === 'no-youtube' && hasYoutube(song)) return false;
      if (state.frequency === 'single' && song.artistSongCount !== 1) return false;
      if (state.frequency === 'medium' && !(song.artistSongCount >= 2 && song.artistSongCount <= 4)) return false;
      if (state.frequency === 'frequent' && song.artistSongCount < 5) return false;
      if (state.duration === 'short' && song.duration >= 180) return false;
      if (state.duration === 'medium' && !(song.duration >= 180 && song.duration < 360)) return false;
      if (state.duration === 'long' && song.duration < 360) return false;
      return true;
    }
    function links(song) {
      return `<div class="links"><a class="link" href="${escapeHtml(song.qq_music)}" target="_blank" rel="noopener">QQ</a>${song.youtube ? `<a class="link" href="${escapeHtml(song.youtube)}" target="_blank" rel="noopener">YouTube</a>` : ''}</div>`;
    }
    function track(song, showAlbum=true) {
      return `<div class="track"><div><div class="track-title">${escapeHtml(song.title)}</div>${showAlbum ? `<div class="track-album">${escapeHtml(song.album || '未标注专辑')} · ${duration(song.duration)}</div>` : `<div class="track-album">${duration(song.duration)}</div>`}</div>${links(song)}</div>`;
    }
    function sortOptions() {
      const options = state.view === 'artists' ? [['count','收录数最多'],['name','艺人名称']] : state.view === 'albums' ? [['count','曲目数最多'],['name','专辑名称'],['artist','艺人名称']] : [['name','歌曲名称'],['artist','艺人名称'],['album','专辑名称'],['duration','时长最长']];
      $('sort').innerHTML = options.map(([value,label]) => `<option value="${value}">${label}</option>`).join('');
    }
    function renderArtists(songs) {
      const groups = new Map();
      songs.forEach(song => { if(!groups.has(song.artist)) groups.set(song.artist, []); groups.get(song.artist).push(song); });
      const sort = $('sort').value || 'count';
      const list = [...groups.entries()].map(([name, tracks]) => ({name, tracks, youtube:tracks.filter(hasYoutube).length}));
      list.sort((a,b) => sort === 'name' ? a.name.localeCompare(b.name) : b.tracks.length-a.tracks.length || a.name.localeCompare(b.name));
      $('resultCount').textContent = `找到 ${list.length} 位艺人 · ${songs.length} 首歌曲`;
      $('results').innerHTML = list.length ? `<div class="grid">${list.map(item => `<details><summary><div><div class="artist-name">${escapeHtml(item.name)}</div><div class="meta">${item.tracks.length} 首 · YT ${item.youtube}</div></div><span class="badge">展开</span></summary><div class="track-list">${item.tracks.sort((a,b)=>a.album.localeCompare(b.album)||a.title.localeCompare(b.title)).map(song=>track(song,true)).join('')}</div></details>`).join('')}</div>` : '<div class="empty">没有符合条件的艺人。</div>';
    }
    function renderAlbums(songs) {
      const groups = new Map();
      songs.forEach(song => { const key=`${song.artist}\\u0000${song.album || '未标注专辑'}`; if(!groups.has(key)) groups.set(key, {artist:song.artist, album:song.album || '未标注专辑', tracks:[]}); groups.get(key).tracks.push(song); });
      const sort = $('sort').value || 'count';
      const list = [...groups.values()];
      list.sort((a,b) => sort === 'name' ? a.album.localeCompare(b.album) : sort === 'artist' ? a.artist.localeCompare(b.artist) : b.tracks.length-a.tracks.length || a.album.localeCompare(b.album));
      $('resultCount').textContent = `找到 ${list.length} 张专辑 · ${songs.length} 首歌曲`;
      $('results').innerHTML = list.length ? `<div class="grid">${list.map(item => `<article class="album-card"><div class="album-name">${escapeHtml(item.album)}</div><div class="meta">${escapeHtml(item.artist)} · ${item.tracks.length} 首 · ${duration(item.tracks.reduce((sum,song)=>sum+song.duration,0))}</div><div class="track-list">${item.tracks.sort((a,b)=>a.title.localeCompare(b.title)).map(song=>track(song,false)).join('')}</div></article>`).join('')}</div>` : '<div class="empty">没有符合条件的专辑。</div>';
    }
    function renderSongs(songs) {
      const sort = $('sort').value || 'name';
      const list = [...songs].sort((a,b) => sort === 'artist' ? a.artist.localeCompare(b.artist) : sort === 'album' ? a.album.localeCompare(b.album) : sort === 'duration' ? b.duration-a.duration : a.title.localeCompare(b.title));
      $('resultCount').textContent = `找到 ${list.length} 首歌曲`;
      $('results').innerHTML = list.length ? `<div class="table-wrap"><table><thead><tr><th>歌曲</th><th>艺人</th><th>专辑</th><th>时长</th><th>播放</th></tr></thead><tbody>${list.map(song => `<tr><td>${escapeHtml(song.title)}</td><td>${escapeHtml(song.artist)}</td><td>${escapeHtml(song.album || '未标注专辑')}</td><td>${duration(song.duration)}</td><td>${links(song)}</td></tr>`).join('')}</tbody></table></div>` : '<div class="empty">没有符合条件的歌曲。</div>';
    }
    function render() { const songs=allSongs.filter(matches); if(state.view==='artists') renderArtists(songs); else if(state.view==='albums') renderAlbums(songs); else renderSongs(songs); }
    function setView(view) { state.view=view; document.querySelectorAll('.tab').forEach(tab => tab.setAttribute('aria-selected', String(tab.dataset.view===view))); sortOptions(); render(); }
    function init() {
      const albumCount = new Set(allSongs.map(song => `${song.artist}\\u0000${song.album || ''}`)).size;
      $('metricSongs').textContent=allSongs.length.toLocaleString(); $('metricArtists').textContent=allArtists.length.toLocaleString(); $('metricAlbums').textContent=albumCount.toLocaleString(); $('metricYoutube').textContent=allSongs.filter(hasYoutube).length.toLocaleString();
      $('subhead').textContent=`${LIBRARY.export_date || ''} 导出 · 按艺人、专辑或歌曲快速浏览`;
      sortOptions(); render();
      $('search').addEventListener('input', event=>{state.search=event.target.value; render();});
      $('sourceFilter').addEventListener('change', event=>{state.source=event.target.value; render();});
      $('frequencyFilter').addEventListener('change', event=>{state.frequency=event.target.value; render();});
      $('durationFilter').addEventListener('change', event=>{state.duration=event.target.value; render();});
      $('sort').addEventListener('change', render);
      document.querySelectorAll('.tab').forEach(tab=>tab.addEventListener('click',()=>setView(tab.dataset.view)));
      $('clearFilters').addEventListener('click',()=>{state.search='';state.source='all';state.frequency='all';state.duration='all';$('search').value='';$('sourceFilter').value='all';$('frequencyFilter').value='all';$('durationFilter').value='all';render();});
    }
    init();
  </script>
</body>
</html>'''


def main() -> None:
    library = json.loads(SOURCE.read_text(encoding="utf-8"))
    payload = json.dumps(library, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT.write_text(TEMPLATE.replace("__LIBRARY_JSON__", payload), encoding="utf-8")
    print(f"Built {OUTPUT.name}: {library['total_unique_songs']} songs, {library['total_singers']} artists")


if __name__ == "__main__":
    main()
