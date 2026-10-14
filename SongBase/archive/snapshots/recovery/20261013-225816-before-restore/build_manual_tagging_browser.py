#!/usr/bin/env python3
"""Build an offline, manual tagging queue for tracks without a genre candidate."""

from __future__ import annotations

import json
from pathlib import Path

from build_song_tags_browser import (
    CANDIDATES_PATH,
    SONGS_PATH,
    TAGS_PATH,
    build_payload,
    load_json,
)


BASE = Path(__file__).resolve().parent
OUTPUT_PATH = BASE / "song_manual_tagging.html"


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SongBase 无候选手动标注</title>
  <style>
    :root{--bg:#0e1412;--panel:#17201d;--panel2:#1d2925;--line:#304039;--text:#edf3ee;--muted:#9aaca3;--accent:#c9dd87;--accentInk:#18210d;--blue:#9fc8dc;--warm:#e9b88c;--radius:15px}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}button,input,select,textarea{font:inherit}button,select{cursor:pointer}a{color:inherit}.shell{width:min(1480px,calc(100% - 28px));margin:auto;padding:26px 0 44px}.topline{display:flex;align-items:start;justify-content:space-between;gap:18px}.eyebrow{margin:0 0 6px;color:var(--accent);font-size:12px;letter-spacing:.13em;text-transform:uppercase}h1{margin:0;font-size:clamp(26px,4vw,40px);letter-spacing:-.035em}.sub{margin:7px 0 20px;color:var(--muted)}.back,.button{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;color:var(--muted);background:transparent;border:1px solid var(--line);border-radius:9px;padding:9px 12px}.button:hover,.back:hover{border-color:var(--muted);color:var(--text)}.button.primary{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:750}.button:disabled{cursor:not-allowed;opacity:.45}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}.metric{padding:13px 15px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}.metric strong{display:block;font-size:22px}.metric span{color:var(--muted);font-size:12px}.bar{height:7px;margin-top:7px;background:var(--panel2);border-radius:99px;overflow:hidden}.bar i{display:block;height:100%;background:var(--accent)}
    .toolbar{display:grid;grid-template-columns:minmax(240px,2fr) minmax(180px,1fr) minmax(150px,.8fr) auto;gap:9px;padding:12px;margin-bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}input,select,textarea{width:100%;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px;outline:none}input:focus,select:focus,textarea:focus{border-color:var(--accent)}textarea{resize:vertical;min-height:78px}.workspace{display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:12px;align-items:start}.queue,.editor{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}.queue{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}.queue-head{position:sticky;top:0;z-index:2;padding:12px 14px;background:var(--panel);border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.queue-item{display:block;width:100%;padding:11px 14px;text-align:left;color:var(--text);background:transparent;border:0;border-bottom:1px solid rgba(48,64,57,.7)}.queue-item:hover{background:var(--panel2)}.queue-item.active{background:rgba(201,221,135,.12);box-shadow:inset 3px 0 var(--accent)}.queue-title{display:flex;justify-content:space-between;gap:8px;font-weight:700}.queue-title i{flex:0 0 auto;width:8px;height:8px;margin-top:7px;border-radius:50%;background:var(--line)}.queue-item.done .queue-title i{background:var(--accent)}.meta{color:var(--muted);font-size:12px}.editor{padding:18px}.song-head{margin-bottom:16px}.song-head h2{margin:0 0 4px;font-size:25px}.media-action{display:flex;align-items:center;gap:9px;margin-top:10px}.external{color:var(--accent);border-color:rgba(201,221,135,.55);font-weight:700}audio{width:min(440px,100%);height:36px}.reason{padding:11px 12px;margin-bottom:15px;color:var(--muted);background:var(--panel2);border:1px solid var(--line);border-radius:10px;font-size:12px}.reason b{color:var(--warm)}.signals{display:flex;flex-wrap:wrap;gap:5px;margin-top:7px}.signal{border:1px solid var(--line);border-radius:999px;padding:2px 7px;font-size:11px}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:13px}.field.full{grid-column:1/-1}.field label{display:block;margin-bottom:5px;color:var(--muted);font-size:12px}.secondary{display:flex;flex-wrap:wrap;gap:7px}.secondary label{display:flex;align-items:center;gap:6px;margin:0;padding:7px 10px;color:var(--text);border:1px solid var(--line);border-radius:999px}.secondary label.disabled{opacity:.42}.secondary input{width:auto;margin:0;accent-color:var(--accent)}.status{min-height:20px;margin:12px 0 0;color:var(--muted);font-size:12px}.status.done{color:var(--accent)}.editor-actions{display:flex;flex-wrap:wrap;justify-content:space-between;gap:8px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}.action-group{display:flex;flex-wrap:wrap;gap:8px}.empty{padding:52px;text-align:center;color:var(--muted)}.toast{position:fixed;z-index:10;right:20px;bottom:20px;max-width:min(430px,calc(100% - 40px));padding:11px 14px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;box-shadow:0 10px 35px rgba(0,0,0,.3);opacity:0;transform:translateY(8px);pointer-events:none;transition:.18s}.toast.show{opacity:1;transform:translateY(0)}.toast.error{color:var(--warm);border-color:var(--warm)}
    @media(max-width:850px){.metrics{grid-template-columns:1fr 1fr}.toolbar{grid-template-columns:1fr 1fr}.toolbar input{grid-column:1/-1}.workspace{grid-template-columns:1fr}.queue{position:static;max-height:280px}.topline{display:block}.back{margin-bottom:12px}}@media(max-width:560px){.shell{width:calc(100% - 18px);padding-top:16px}.toolbar,.form-grid{grid-template-columns:1fr}.toolbar input,.field.full{grid-column:auto}.metrics{gap:6px}.metric{padding:10px}.editor{padding:14px}.editor-actions{display:block}.action-group{margin-top:8px}.button{width:100%;margin-top:6px}}
  </style>
</head>
<body>
  <main class="shell">
    <div class="topline"><div><p class="eyebrow">Manual review queue</p><h1>无候选曲目手动标注</h1><p class="sub">逐首填写并自动保存在本机；导出的 JSON 不会直接改写正式标签库。</p></div><a class="back" href="song_tags_browser.html">← 返回标签浏览器</a></div>
    <section class="metrics">
      <div class="metric"><strong id="total">—</strong><span>无主候选</span></div>
      <div class="metric"><strong id="completed">—</strong><span>已完成</span></div>
      <div class="metric"><strong id="remaining">—</strong><span>待处理</span></div>
      <div class="metric"><strong id="rate">—</strong><span>完成率</span><div class="bar"><i id="progress"></i></div></div>
    </section>
    <section class="toolbar">
      <input id="search" type="search" placeholder="搜索歌曲、艺人或专辑…">
      <select id="artist"><option value="all">全部艺人</option></select>
      <select id="status"><option value="pending">只看待处理</option><option value="all">全部</option><option value="done">只看已完成</option></select>
      <button class="button primary" id="export" type="button">导出已完成 JSON</button>
    </section>
    <section class="workspace">
      <aside class="queue"><div class="queue-head" id="queueHead">—</div><div id="queue"></div></aside>
      <article class="editor" id="editor"><div class="empty">请选择一首曲目开始标注。</div></article>
    </section>
  </main>
  <div class="toast" id="toast"></div>
  <script>
    const DATA=__PAYLOAD__;
    const STORAGE_KEY='songbase.manual-tag-reviews/v1';
    const $=id=>document.getElementById(id);
    const esc=value=>String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const today=()=>new Date().toISOString().slice(0,10);
    let reviews={};try{reviews=JSON.parse(localStorage.getItem(STORAGE_KEY)||'{}')}catch(error){reviews={}}
    let state={search:'',artist:'all',status:'pending',activeId:null};
    function blank(){return {genre:null,secondary_genres:[],language:null,instrumental:null,note:'',completed:false}}
    function review(id){return {...blank(),...(reviews[id]||{})}}
    function done(id){const value=review(id);return value.completed===true&&Boolean(value.genre)}
    function persist(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(reviews));return true}catch(error){toast('浏览器无法保存本机进度，请先导出当前结果。',true);return false}}
    let toastTimer;function toast(message,error=false){const node=$('toast');node.textContent=message;node.className=`toast show${error?' error':''}`;clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.className='toast',2600)}
    function filtered(){const q=state.search.trim().toLocaleLowerCase();return DATA.songs.filter(song=>{if(q&&![song.title,song.artist,song.album].join(' ').toLocaleLowerCase().includes(q))return false;if(state.artist!=='all'&&song.artist!==state.artist)return false;if(state.status==='pending'&&done(song.id))return false;if(state.status==='done'&&!done(song.id))return false;return true}).sort((a,b)=>a.artist.localeCompare(b.artist)||a.title.localeCompare(b.title))}
    function metrics(){const completed=DATA.songs.filter(song=>done(song.id)).length,total=DATA.songs.length,rate=total?completed/total*100:0;$('total').textContent=total;$('completed').textContent=completed;$('remaining').textContent=total-completed;$('rate').textContent=`${rate.toFixed(1)}%`;$('progress').style.width=`${rate}%`;$('export').disabled=completed===0}
    function renderQueue(){const rows=filtered();if(!rows.some(song=>song.id===state.activeId)){state.activeId=rows[0]?.id||null}$('queueHead').textContent=`当前筛选 ${rows.length} / ${DATA.songs.length} 首`;$('queue').innerHTML=rows.length?rows.map(song=>`<button class="queue-item${song.id===state.activeId?' active':''}${done(song.id)?' done':''}" type="button" data-id="${esc(song.id)}"><div class="queue-title"><span>${esc(song.title)}</span><i></i></div><div class="meta">${esc(song.artist)} · ${esc(song.album||'未标注专辑')}</div></button>`).join(''):'<div class="empty">当前筛选没有曲目。</div>';document.querySelectorAll('[data-id]').forEach(button=>button.addEventListener('click',()=>{state.activeId=button.dataset.id;render()}))}
    function option(value,label,current){return `<option value="${esc(value)}"${value===current?' selected':''}>${esc(label)}</option>`}
    function weakSignals(song){const tags=(song.candidate?.matched_tags||[]).map(item=>item.tag).filter(Boolean);const errors=(song.candidate?.errors||[]).map(item=>typeof item==='string'?item:(item.error||item.message)).filter(Boolean);return `<div class="reason"><b>没有形成主风格候选。</b>${tags.length?`<div class="signals">${[...new Set(tags)].slice(0,10).map(tag=>`<span class="signal">${esc(tag)}</span>`).join('')}</div>`:''}${errors.length?`<div style="margin-top:7px">查询信息：${esc(errors.join('；'))}</div>`:''}</div>`}
    function renderEditor(){const song=DATA.songs.find(item=>item.id===state.activeId);if(!song){$('editor').innerHTML='<div class="empty">当前筛选没有可编辑的曲目。</div>';return}const value=review(song.id);const genreOptions=[option('','请选择主 Tag',value.genre),...DATA.taxonomy.genres.map(g=>option(g,g,value.genre))].join('');const secondary=DATA.taxonomy.genres.map(g=>{const disabled=g===value.genre,checked=value.secondary_genres.includes(g)&&!disabled;return `<label class="${disabled?'disabled':''}"><input type="checkbox" data-secondary="${esc(g)}"${checked?' checked':''}${disabled?' disabled':''}>${esc(g)}</label>`}).join('');const languageOptions=[option('','默认中文/英文或未知',value.language),...DATA.taxonomy.languages.map(g=>option(g,g,value.language))].join('');const instrumentalOptions=option('','未知',value.instrumental===null?'':String(value.instrumental))+option('true','Instrumental',String(value.instrumental))+option('false','非器乐',String(value.instrumental));const external=song.youtube||song.bilibili||song.qq_music;const media=song.audio_url?`<audio controls src="${esc(song.audio_url)}"></audio>`:external?`<a class="button external" href="${esc(external)}" target="_blank" rel="noopener">↗ 外部播放</a>`:'<span class="meta">暂无可用播放链接</span>';const statusText=done(song.id)?'✓ 已确认完成，会进入导出 JSON':value.genre?'草稿已自动保存；检查其他字段后，请点击“完成本首并下一首”。':'尚未完成；请先选择主 Tag。';$('editor').innerHTML=`<div class="song-head"><h2>${esc(song.title)}</h2><div class="meta">${esc(song.artist)} · ${esc(song.album||'未标注专辑')} · ${esc(song.id)}</div><div class="media-action">${media}</div></div>${weakSignals(song)}<div class="form-grid"><div class="field"><label>主 Tag（完成标注所必需）</label><select id="genreField">${genreOptions}</select></div><div class="field"><label>器乐状态</label><select id="instrumentalField">${instrumentalOptions}</select></div><div class="field full"><label>副 Tag（可选，最多两个）</label><div class="secondary">${secondary}</div></div><div class="field"><label>语言</label><select id="languageField">${languageOptions}</select></div><div class="field full"><label>备注（可选）</label><textarea id="noteField" placeholder="写下需要我入库时注意的判断…">${esc(value.note)}</textarea></div></div><div class="status${done(song.id)?' done':''}">${statusText}</div><div class="editor-actions"><button class="button" id="clearCurrent" type="button">清空本首</button><div class="action-group"><button class="button" id="previous" type="button">上一首</button><button class="button" id="skip" type="button">下一首</button><button class="button primary" id="complete" type="button">${done(song.id)?'撤销完成':'完成本首并下一首'}</button></div></div>`;
      $('genreField').addEventListener('change',event=>update(song.id,'genre',event.target.value||null,true));$('languageField').addEventListener('change',event=>update(song.id,'language',event.target.value||null,false));$('instrumentalField').addEventListener('change',event=>update(song.id,'instrumental',event.target.value===''?null:event.target.value==='true',false));$('noteField').addEventListener('input',event=>update(song.id,'note',event.target.value,false,false));document.querySelectorAll('[data-secondary]').forEach(node=>node.addEventListener('change',event=>toggleSecondary(song.id,node.dataset.secondary,event.target.checked)));$('clearCurrent').addEventListener('click',()=>clearCurrent(song.id));$('previous').addEventListener('click',()=>move(-1));$('skip').addEventListener('click',()=>move(1));$('complete').addEventListener('click',()=>toggleCompleted(song.id));
    }
    function update(id,field,value,fullRender=false,showToast=true){const next={...review(id),[field]:value};if(field==='genre'){next.secondary_genres=next.secondary_genres.filter(g=>g!==value);if(!value)next.completed=false}reviews[id]=next;persist();if(showToast)toast('草稿已自动保存');if(fullRender)render();else metrics()}
    function toggleSecondary(id,genre,checked){const value=review(id);let items=value.secondary_genres.filter(g=>g!==value.genre);if(checked&&!items.includes(genre)){if(items.length>=2){toast('副 Tag 最多两个。',true);renderEditor();return}items.push(genre)}else if(!checked)items=items.filter(g=>g!==genre);reviews[id]={...value,secondary_genres:items};persist();metrics();toast('已自动保存')}
    function clearCurrent(id){if(!confirm('清空这首曲目的全部手动标注吗？'))return;delete reviews[id];persist();render();toast('本首标注已清空')}
    function visibleIds(){return filtered().map(song=>song.id)}
    function move(step){const ids=visibleIds(),index=ids.indexOf(state.activeId);if(!ids.length)return;state.activeId=ids[(Math.max(0,index)+step+ids.length)%ids.length];render()}
    function toggleCompleted(id){const value=review(id);if(done(id)){reviews[id]={...value,completed:false};persist();render();toast('已撤销完成，保留为草稿');return}if(!value.genre){toast('请先选择主 Tag，再确认完成。',true);return}const rows=filtered(),index=rows.findIndex(song=>song.id===id),nextId=rows[index+1]?.id||rows[0]?.id||null;reviews[id]={...value,completed:true};persist();state.activeId=nextId===id?null:nextId;render();toast('本首已完成，会进入导出 JSON')}
    function exportJson(){const entries=DATA.songs.filter(song=>done(song.id)).map(song=>{const value=review(song.id);return {track_id:song.id,song:{title:song.title,artist:song.artist,album:song.album,qq_music:song.qq_music},completed:true,resolved_tags:{genre:value.genre,secondary_genres:value.secondary_genres,language:value.language,instrumental:value.instrumental},note:value.note.trim()}});if(!entries.length){toast('还没有手动确认完成的标注可导出。',true);return}const payload={schema_version:'songbase.manual-tag-reviews/v1',exported_at:today(),purpose:'Human-authored tags for SongBase tracks without a genre candidate. This file does not update song_tags.json by itself.',source:{browser:'song_manual_tagging.html',library_date:DATA.library_date,tags_updated_at:DATA.tags_updated_at,taxonomy_version:DATA.taxonomy_version},summary:{queue_total:DATA.songs.length,completed:entries.length,remaining:DATA.songs.length-entries.length},reviews:entries};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=`song_manual_tags_${today()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已导出 ${entries.length} 首完成标注`)}
    function render(){renderQueue();metrics();renderEditor()}
    function init(){const artists=[...new Set(DATA.songs.map(song=>song.artist))].sort((a,b)=>a.localeCompare(b));$('artist').innerHTML+=artists.map(a=>`<option value="${esc(a)}">${esc(a)}</option>`).join('');$('search').addEventListener('input',event=>{state.search=event.target.value;render()});$('artist').addEventListener('change',event=>{state.artist=event.target.value;render()});$('status').addEventListener('change',event=>{state.status=event.target.value;render()});$('export').addEventListener('click',exportJson);state.activeId=filtered()[0]?.id||DATA.songs[0]?.id||null;render()}
    init();
  </script>
</body>
</html>'''


def main() -> None:
    library = load_json(SONGS_PATH)
    tags = load_json(TAGS_PATH)
    candidates = load_json(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else None
    payload = build_payload(library, tags, candidates)
    payload["songs"] = [
        song
        for song in payload["songs"]
        if song["tags"] is None
        and (song["candidate"] is None or not song["candidate"].get("genre"))
    ]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT_PATH.write_text(TEMPLATE.replace("__PAYLOAD__", encoded), encoding="utf-8")
    print(f"Built {OUTPUT_PATH.name}: {len(payload['songs'])} tracks without a genre candidate")


if __name__ == "__main__":
    main()
