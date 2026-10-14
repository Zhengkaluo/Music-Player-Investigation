#!/usr/bin/env python3
"""Build one offline queue for missing SongBase tags and human ZMPD labels."""

from __future__ import annotations

import json
from pathlib import Path

from build_annotation_gap_report import ROOT, identity_index, load_songbase, read_json, zmpd_tracks
from build_song_tags_browser import CANDIDATES_PATH, SONGS_PATH, TAGS_PATH, build_payload, load_json


BASE = Path(__file__).resolve().parent
OUTPUT_PATH = BASE / "song_combined_annotation.html"
ZMPD_MANIFEST_PATH = BASE.parent / "ZMPD-模型预测开发" / "manifests" / "training-manifest.json"

ZMPD_DIMENSIONS = {
    "time_scene": ["8-11", "11-14", "14-17", "17-20"],
    "energy_state": ["平静", "渐进", "有冲劲", "爆发", "不确定"],
    "scale": list(range(1, 11)),
}


def merge_annotation_requirements(payload: dict, zmpd_ids: set[str]) -> dict:
    """Keep only tracks missing at least one annotation family."""
    songs = []
    for song in payload["songs"]:
        needs_tag = song["tags"] is None
        needs_zmpd = song["id"] not in zmpd_ids
        if not (needs_tag or needs_zmpd):
            continue
        songs.append({
            **song,
            "needs": {"tag": needs_tag, "zmpd": needs_zmpd},
            "zmpd_labeled": not needs_zmpd,
            "gap_type": "both" if needs_tag and needs_zmpd else ("tag" if needs_tag else "zmpd"),
        })
    return {**payload, "songs": songs, "zmpd_dimensions": ZMPD_DIMENSIONS}


def build_combined_payload() -> dict:
    library = load_json(SONGS_PATH)
    tags = load_json(TAGS_PATH)
    candidates = load_json(CANDIDATES_PATH) if CANDIDATES_PATH.exists() else None
    payload = build_payload(library, tags, candidates)
    aliases = read_json(ROOT / "song_identity_aliases.json")
    songbase = load_songbase()
    index = identity_index(songbase, aliases["artistAliases"])
    zmpd_ids, unmatched = zmpd_tracks(songbase, index, aliases)
    manifest = read_json(ZMPD_MANIFEST_PATH)
    payload = merge_annotation_requirements(payload, zmpd_ids)
    payload["zmpd_source"] = {
        "schema_version": manifest.get("schemaVersion"),
        "generated_at": manifest.get("generatedAt"),
        "qualified_tracks": manifest.get("summary", {}).get("qualifiedTracks"),
        "matched_songbase_tracks": len(zmpd_ids),
        "unmatched_audio_identities": len(unmatched),
    }
    return payload


TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>SongBase Tag + ZMPD 联合标注</title>
  <style>
    :root{--bg:#0e1412;--panel:#17201d;--panel2:#1d2925;--line:#304039;--text:#edf3ee;--muted:#9aaca3;--accent:#c9dd87;--accentInk:#18210d;--blue:#9fc8dc;--warm:#e9b88c;--radius:15px}
    *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.5 ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif}button,input,select,textarea{font:inherit}button,select{cursor:pointer}a{color:inherit}.shell{width:min(1500px,calc(100% - 28px));margin:auto;padding:26px 0 44px}.topline{display:flex;justify-content:space-between;gap:18px;align-items:start}.eyebrow{margin:0 0 6px;color:var(--accent);font-size:12px;letter-spacing:.13em;text-transform:uppercase}h1{margin:0;font-size:clamp(26px,4vw,40px);letter-spacing:-.035em}.sub{margin:7px 0 20px;color:var(--muted)}.button{display:inline-flex;align-items:center;justify-content:center;text-decoration:none;color:var(--muted);background:transparent;border:1px solid var(--line);border-radius:9px;padding:9px 12px}.button:hover{border-color:var(--muted);color:var(--text)}.button.primary{color:var(--accentInk);background:var(--accent);border-color:var(--accent);font-weight:750}.button:disabled{opacity:.42;cursor:not-allowed}.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:9px;margin-bottom:12px}.metric{padding:13px 15px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}.metric strong{display:block;font-size:22px}.metric span,.meta{color:var(--muted);font-size:12px}.toolbar{display:grid;grid-template-columns:minmax(220px,2fr) repeat(3,minmax(140px,1fr)) auto;gap:9px;padding:12px;margin-bottom:12px;background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}input,select,textarea{width:100%;color:var(--text);background:var(--panel2);border:1px solid var(--line);border-radius:9px;padding:9px 11px;outline:none}input:focus,select:focus,textarea:focus{border-color:var(--accent)}textarea{resize:vertical;min-height:70px}.workspace{display:grid;grid-template-columns:minmax(280px,360px) minmax(0,1fr);gap:12px;align-items:start}.queue,.editor{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius)}.queue{position:sticky;top:12px;max-height:calc(100vh - 24px);overflow:auto}.queue-head{position:sticky;top:0;z-index:2;padding:12px 14px;background:var(--panel);border-bottom:1px solid var(--line);color:var(--muted);font-size:12px}.queue-item{display:block;width:100%;padding:11px 14px;text-align:left;color:var(--text);background:transparent;border:0;border-bottom:1px solid rgba(48,64,57,.7)}.queue-item:hover{background:var(--panel2)}.queue-item.active{background:rgba(201,221,135,.12);box-shadow:inset 3px 0 var(--accent)}.queue-title{display:flex;justify-content:space-between;gap:8px;font-weight:700}.dots{display:flex;gap:4px}.dot,.badge{display:inline-flex;align-items:center;justify-content:center;border-radius:999px}.dot{width:20px;height:20px;color:var(--bg);font-size:10px;font-style:normal;background:var(--warm)}.dot.z{background:var(--blue)}.queue-item.done .dot{background:var(--accent)}.editor{padding:18px}.song-head{display:flex;justify-content:space-between;gap:16px;margin-bottom:16px}.song-head h2{margin:0 0 4px;font-size:25px}.media{display:flex;align-items:center;gap:9px;margin-top:10px}.external{color:var(--accent);border-color:rgba(201,221,135,.55);font-weight:700}audio{width:min(440px,100%);height:36px}.badge{padding:4px 9px;border:1px solid var(--line);color:var(--muted);font-size:11px}.badge.missing{color:var(--warm);border-color:rgba(233,184,140,.45)}.panels{display:grid;grid-template-columns:1fr 1fr;gap:12px}.panel{padding:15px;background:var(--panel2);border:1px solid var(--line);border-radius:12px}.panel h3{margin:0 0 4px}.panel-note{margin:0 0 13px;color:var(--muted);font-size:12px}.existing{color:var(--muted)}.existing strong{color:var(--text)}.field{margin-top:11px}.field>label,.field-title{display:block;margin-bottom:6px;color:var(--muted);font-size:12px}.chips,.scale{display:flex;flex-wrap:wrap;gap:6px}.chip{position:relative}.chip input{position:absolute;opacity:0;pointer-events:none}.chip span{display:block;padding:7px 10px;border:1px solid var(--line);border-radius:999px;cursor:pointer}.chip input:checked+span{color:var(--accentInk);background:var(--accent);border-color:var(--accent)}.scale .chip span{min-width:34px;text-align:center;padding:6px}.secondary{display:flex;flex-wrap:wrap;gap:6px}.secondary label{display:flex;align-items:center;gap:6px;margin:0;padding:7px 9px;border:1px solid var(--line);border-radius:999px}.secondary input{width:auto;margin:0;accent-color:var(--accent)}.candidate{margin-top:9px;padding:9px 10px;border:1px dashed rgba(159,200,220,.45);border-radius:9px;color:var(--blue);font-size:12px}.status{min-height:22px;margin:13px 0 0;color:var(--muted);font-size:12px}.status.done{color:var(--accent)}.editor-actions{display:flex;justify-content:space-between;gap:8px;margin-top:14px;padding-top:14px;border-top:1px solid var(--line)}.actions{display:flex;gap:8px}.empty{padding:48px;text-align:center;color:var(--muted)}.toast{position:fixed;z-index:20;right:20px;bottom:20px;max-width:min(440px,calc(100% - 40px));padding:11px 14px;background:var(--panel2);border:1px solid var(--line);border-radius:10px;box-shadow:0 10px 35px rgba(0,0,0,.3);opacity:0;transform:translateY(8px);pointer-events:none;transition:.18s}.toast.show{opacity:1;transform:translateY(0)}.toast.error{color:var(--warm);border-color:var(--warm)}
    @media(max-width:1000px){.toolbar{grid-template-columns:1fr 1fr}.toolbar input{grid-column:1/-1}.panels{grid-template-columns:1fr}}@media(max-width:780px){.metrics{grid-template-columns:1fr 1fr}.workspace{grid-template-columns:1fr}.queue{position:static;max-height:280px}.topline,.song-head{display:block}.topline .button{margin-bottom:12px}}@media(max-width:560px){.shell{width:calc(100% - 18px);padding-top:16px}.toolbar{grid-template-columns:1fr}.toolbar input{grid-column:auto}.editor-actions,.actions{display:block}.button{width:100%;margin-top:6px}}
  </style>
</head>
<body>
  <main class="shell">
    <div class="topline"><div><p class="eyebrow">Unified annotation queue</p><h1>Tag + ZMPD 联合标注</h1><p class="sub">每首只显示它当前缺少的标注块；两边都缺才会同时要求填写。所有改动先存为草稿，必须点“完成本首”才会进入导出。</p></div><a class="button" href="song_tags_browser.html">← 返回标签浏览器</a></div>
    <section class="metrics"><div class="metric"><strong id="total">—</strong><span>联合队列</span></div><div class="metric"><strong id="both">—</strong><span>Tag + ZMPD 都缺</span></div><div class="metric"><strong id="completed">—</strong><span>已完成</span></div><div class="metric"><strong id="remaining">—</strong><span>待处理</span></div></section>
    <section class="toolbar"><input id="search" type="search" placeholder="搜索歌曲、艺人或专辑…"><select id="artist"><option value="all">全部艺人</option></select><select id="gap"><option value="all">全部缺口</option><option value="both">Tag + ZMPD 都缺</option><option value="tag">只缺 Tag</option><option value="zmpd">只缺 ZMPD</option></select><select id="status"><option value="pending">只看待处理</option><option value="all">全部</option><option value="done">只看已完成</option><option value="local">只看有本地音源</option></select><button class="button primary" id="export" type="button">导出已完成 JSON</button></section>
    <section class="workspace"><aside class="queue"><div class="queue-head" id="queueHead">—</div><div id="queue"></div></aside><article class="editor" id="editor"><div class="empty">请选择一首曲目开始标注。</div></article></section>
  </main><div class="toast" id="toast"></div>
  <script>
    const DATA=__PAYLOAD__,STORAGE_KEY='songbase.combined-annotations/v1';
    const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const today=()=>new Date().toISOString().slice(0,10);let reviews={};try{reviews=JSON.parse(localStorage.getItem(STORAGE_KEY)||'{}')}catch(e){reviews={}}let state={search:'',artist:'all',gap:'all',status:'pending',activeId:null};
    function blankTag(song){const c=song.candidate||{},genre=c.genre||null;return {genre,secondary_genres:(c.secondary_genres||[]).filter(g=>g!==genre).slice(0,2),language:null,instrumental:c.instrumental??null,note:''}}
    function blankZmpd(){return {time_scene:[],energy_state:null,noise:null,swing:null,burden:null,confidence:null,note:''}}
    function review(song){return {tag:song.needs.tag?blankTag(song):null,zmpd:song.needs.zmpd?blankZmpd():null,completed:false,...(reviews[song.id]||{})}}
    function tagValid(song,value){return !song.needs.tag||Boolean(value.tag?.genre)}
    function zmpdValid(song,value){const z=value.zmpd;return !song.needs.zmpd||Boolean(z&&z.time_scene?.length&&z.energy_state&&z.noise&&z.swing&&z.burden)}
    function done(song){const value=review(song);return value.completed===true&&tagValid(song,value)&&zmpdValid(song,value)}
    function persist(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify(reviews));return true}catch(e){toast('无法保存本机草稿，请尽快导出。',true);return false}}
    let timer;function toast(message,error=false){const n=$('toast');n.textContent=message;n.className=`toast show${error?' error':''}`;clearTimeout(timer);timer=setTimeout(()=>n.className='toast',2500)}
    function filtered(){const q=state.search.trim().toLocaleLowerCase();return DATA.songs.filter(song=>{if(q&&![song.title,song.artist,song.full_singer,song.album].join(' ').toLocaleLowerCase().includes(q))return false;if(state.artist!=='all'&&song.artist!==state.artist)return false;if(state.gap!=='all'&&song.gap_type!==state.gap)return false;if(state.status==='pending'&&done(song))return false;if(state.status==='done'&&!done(song))return false;if(state.status==='local'&&!song.audio_url)return false;return true}).sort((a,b)=>a.artist.localeCompare(b.artist)||a.title.localeCompare(b.title))}
    function metrics(){const completed=DATA.songs.filter(done).length;$('total').textContent=DATA.songs.length;$('both').textContent=DATA.songs.filter(s=>s.gap_type==='both').length;$('completed').textContent=completed;$('remaining').textContent=DATA.songs.length-completed;$('export').disabled=completed===0}
    function renderQueue(){const rows=filtered();if(!rows.some(s=>s.id===state.activeId))state.activeId=rows[0]?.id||null;$('queueHead').textContent=`当前筛选 ${rows.length} / ${DATA.songs.length} 首`;$('queue').innerHTML=rows.length?rows.map(song=>`<button class="queue-item${song.id===state.activeId?' active':''}${done(song)?' done':''}" data-id="${esc(song.id)}"><div class="queue-title"><span>${esc(song.title)}</span><span class="dots">${song.needs.tag?'<i class="dot">T</i>':''}${song.needs.zmpd?'<i class="dot z">Z</i>':''}</span></div><div class="meta">${esc(song.artist)} · ${esc(song.album||'未标注专辑')}</div></button>`).join(''):'<div class="empty">当前筛选没有曲目。</div>';document.querySelectorAll('[data-id]').forEach(n=>n.addEventListener('click',()=>{state.activeId=n.dataset.id;render()}))}
    function option(value,label,current){return `<option value="${esc(value)}"${String(value)===String(current)?' selected':''}>${esc(label)}</option>`}
    function chips(values,current,name,multiple=false){const selected=new Set(Array.isArray(current)?current:[current]);return `<div class="chips">${values.map(v=>`<label class="chip"><input type="${multiple?'checkbox':'radio'}" name="${name}" value="${esc(v)}"${selected.has(v)?' checked':''}><span>${esc(v)}</span></label>`).join('')}</div>`}
    function scale(name,value){return `<div class="scale">${DATA.zmpd_dimensions.scale.map(v=>`<label class="chip"><input type="radio" name="${name}" value="${v}"${Number(value)===v?' checked':''}><span>${v}</span></label>`).join('')}</div>`}
    function existingTag(song){const t=song.tags;return `<div class="existing"><strong>已有 Tag，本次不修改</strong><p>主：${esc(t.genre)}${t.secondary_genres?.length?`<br>副：${t.secondary_genres.map(esc).join(' / ')}`:''}<br>语言：${esc(t.language||'未判定')} · 器乐性：${t.instrumental===true?'Instrumental':t.instrumental===false?'非器乐':'未判定'}</p></div>`}
    function tagPanel(song,value){if(!song.needs.tag)return `<section class="panel"><h3>Tag</h3>${existingTag(song)}</section>`;const t=value.tag,c=song.candidate,confidence=c?.confidence==null?null:(c.confidence<=1?c.confidence*100:c.confidence);const genres=[option('','请选择主 Tag',t.genre),...DATA.taxonomy.genres.map(g=>option(g,g,t.genre))].join('');const second=DATA.taxonomy.genres.map(g=>`<label${g===t.genre?' style="opacity:.4"':''}><input type="checkbox" data-secondary="${esc(g)}"${t.secondary_genres.includes(g)&&g!==t.genre?' checked':''}${g===t.genre?' disabled':''}>${esc(g)}</label>`).join('');return `<section class="panel"><h3>Tag <span class="badge missing">待标</span></h3><p class="panel-note">主风格必填；副风格最多两个。</p>${c?.genre?`<div class="candidate">候选：${esc(c.genre)}${confidence==null?'':` · ${Math.round(confidence)}%`}（已预填，需你确认）</div>`:''}<div class="field"><label>主 Tag</label><select id="genreField">${genres}</select></div><div class="field"><span class="field-title">副 Tag</span><div class="secondary">${second}</div></div><div class="field"><label>语言</label><select id="languageField">${option('','中英文或未判定',t.language)}${DATA.taxonomy.languages.map(g=>option(g,g,t.language)).join('')}</select></div><div class="field"><label>器乐性</label><select id="instrumentalField">${option('','未判定',t.instrumental===null?'':String(t.instrumental))}${option('true','Instrumental',String(t.instrumental))}${option('false','非器乐',String(t.instrumental))}</select></div><div class="field"><label>Tag 备注（可选）</label><textarea id="tagNote">${esc(t.note)}</textarea></div></section>`}
    function zmpdPanel(song,value){if(!song.needs.zmpd)return `<section class="panel"><h3>ZMPD</h3><div class="existing"><strong>已有完整人工 ZMPD，本次不修改</strong><p>该记录已进入当前训练 manifest。</p></div></section>`;const z=value.zmpd;return `<section class="panel"><h3>ZMPD <span class="badge missing">待标</span></h3><p class="panel-note">五维都必填；时段可多选，其余单选。</p><div class="field"><span class="field-title">适合的时段</span>${chips(DATA.zmpd_dimensions.time_scene,z.time_scene,'timeScene',true)}</div><div class="field"><span class="field-title">能量状态</span>${chips(DATA.zmpd_dimensions.energy_state,z.energy_state,'energyState')}</div><div class="field"><span class="field-title">噪音程度</span>${scale('noise',z.noise)}</div><div class="field"><span class="field-title">摇摆速率</span>${scale('swing',z.swing)}</div><div class="field"><span class="field-title">负担程度</span>${scale('burden',z.burden)}</div><div class="field"><label>把握程度（用于审计，可选）</label><select id="confidenceField">${option('','未填写',z.confidence??'')}${[1,2,3,4,5].map(v=>option(v,`${v} / 5`,z.confidence)).join('')}</select></div><div class="field"><label>ZMPD 备注（可选）</label><textarea id="zmpdNote">${esc(z.note)}</textarea></div></section>`}
    function renderEditor(){const song=DATA.songs.find(s=>s.id===state.activeId);if(!song){$('editor').innerHTML='<div class="empty">当前筛选没有可编辑曲目。</div>';return}const value=review(song),external=song.youtube||song.bilibili||song.qq_music,media=song.audio_url?`<audio controls src="${esc(song.audio_url)}"></audio>`:external?`<a class="button external" href="${esc(external)}" target="_blank" rel="noopener">↗ 外部播放</a>`:'<span class="meta">暂无可用播放链接</span>';$('editor').innerHTML=`<div class="song-head"><div><h2>${esc(song.title)}</h2><div class="meta">${esc(song.artist)} · ${esc(song.album||'未标注专辑')} · ${esc(song.id)}</div><div class="media">${media}</div></div><div>${song.needs.tag?'<span class="badge missing">缺 Tag</span>':'<span class="badge">已有 Tag</span>'} ${song.needs.zmpd?'<span class="badge missing">缺 ZMPD</span>':'<span class="badge">已有 ZMPD</span>'}</div></div><div class="panels">${tagPanel(song,value)}${zmpdPanel(song,value)}</div><div class="status${done(song)?' done':''}">${done(song)?'✓ 已确认完成，会进入导出 JSON':'草稿会自动保存；填完本首所有缺口后，请点“完成本首”。'}</div><div class="editor-actions"><button class="button" id="clearCurrent">清空本首</button><div class="actions"><button class="button" id="previous">上一首</button><button class="button" id="next">下一首</button><button class="button primary" id="complete">${done(song)?'撤销完成':'完成本首并下一首'}</button></div></div>`;wire(song)}
    function save(song,value,rerender=false){reviews[song.id]=value;persist();if(rerender)render();else metrics()}
    function wire(song){if(song.needs.tag){$('genreField').addEventListener('change',e=>{const v=review(song);v.tag.genre=e.target.value||null;v.tag.secondary_genres=v.tag.secondary_genres.filter(g=>g!==v.tag.genre);v.completed=false;save(song,v,true)});$('languageField').addEventListener('change',e=>{const v=review(song);v.tag.language=e.target.value||null;save(song,v)});$('instrumentalField').addEventListener('change',e=>{const v=review(song);v.tag.instrumental=e.target.value===''?null:e.target.value==='true';save(song,v)});$('tagNote').addEventListener('input',e=>{const v=review(song);v.tag.note=e.target.value;save(song,v)});document.querySelectorAll('[data-secondary]').forEach(n=>n.addEventListener('change',e=>{const v=review(song);let s=v.tag.secondary_genres.filter(g=>g!==v.tag.genre);if(e.target.checked&&!s.includes(n.dataset.secondary)){if(s.length>=2){toast('副 Tag 最多两个。',true);renderEditor();return}s.push(n.dataset.secondary)}else s=s.filter(g=>g!==n.dataset.secondary);v.tag.secondary_genres=s;save(song,v)}))}if(song.needs.zmpd){document.querySelectorAll('[name="timeScene"]').forEach(n=>n.addEventListener('change',()=>{const v=review(song);v.zmpd.time_scene=[...document.querySelectorAll('[name="timeScene"]:checked')].map(x=>x.value);v.completed=false;save(song,v)}));[['energyState','energy_state',false],['noise','noise',true],['swing','swing',true],['burden','burden',true]].forEach(([name,key,numeric])=>document.querySelectorAll(`[name="${name}"]`).forEach(n=>n.addEventListener('change',e=>{const v=review(song);v.zmpd[key]=numeric?Number(e.target.value):e.target.value;v.completed=false;save(song,v)})));$('confidenceField').addEventListener('change',e=>{const v=review(song);v.zmpd.confidence=e.target.value?Number(e.target.value):null;save(song,v)});$('zmpdNote').addEventListener('input',e=>{const v=review(song);v.zmpd.note=e.target.value;save(song,v)})}$('clearCurrent').addEventListener('click',()=>clearCurrent(song));$('previous').addEventListener('click',()=>move(-1));$('next').addEventListener('click',()=>move(1));$('complete').addEventListener('click',()=>toggleCompleted(song))}
    function clearCurrent(song){if(!confirm('清空这首的全部联合标注草稿吗？'))return;delete reviews[song.id];persist();render();toast('本首草稿已清空')}
    function move(step){const rows=filtered(),index=rows.findIndex(s=>s.id===state.activeId);if(!rows.length)return;state.activeId=rows[(Math.max(0,index)+step+rows.length)%rows.length].id;render()}
    function toggleCompleted(song){const v=review(song);if(done(song)){v.completed=false;save(song,v,true);toast('已撤销完成，草稿保留');return}if(!tagValid(song,v)){toast('请先选择主 Tag。',true);return}if(!zmpdValid(song,v)){toast('请填完 ZMPD 的全部五个维度。',true);return}const rows=filtered(),index=rows.findIndex(s=>s.id===song.id),next=rows[index+1]?.id||rows[0]?.id||null;v.completed=true;save(song,v);state.activeId=next===song.id?null:next;render();toast('本首已完成，会进入导出 JSON')}
    function exportJson(){const entries=DATA.songs.filter(done).map(song=>{const v=review(song);return {track_id:song.id,song:{title:song.title,artist:song.artist,full_singer:song.full_singer,album:song.album,qq_music:song.qq_music,audio_url:song.audio_url},requirements:song.needs,completed:true,tag_review:song.needs.tag?{resolved_tags:{genre:v.tag.genre,secondary_genres:v.tag.secondary_genres,language:v.tag.language,instrumental:v.tag.instrumental},note:v.tag.note.trim()}:null,zmpd_review:song.needs.zmpd?{selections:{time_scene:v.zmpd.time_scene,energy_state:v.zmpd.energy_state,noise:v.zmpd.noise,swing:v.zmpd.swing,burden:v.zmpd.burden},confidence:v.zmpd.confidence,note:v.zmpd.note.trim()}:null,existing:{tag:song.tags,zmpd_labeled:song.zmpd_labeled}}});if(!entries.length){toast('还没有已确认完成的曲目。',true);return}const payload={schema_version:'songbase.combined-annotations/v1',exported_at:new Date().toISOString(),purpose:'Human-authored SongBase Tag and ZMPD annotations. Missing sides only; this file does not update formal stores by itself.',source:{browser:'song_combined_annotation.html',library_date:DATA.library_date,tags_updated_at:DATA.tags_updated_at,taxonomy_version:DATA.taxonomy_version,zmpd_manifest:DATA.zmpd_source},zmpd_schema:{time_scene:{label:'适合的时段',mode:'multiple'},energy_state:{label:'能量状态',mode:'single'},noise:{label:'噪音程度',range:[1,10]},swing:{label:'摇摆速率',range:[1,10]},burden:{label:'负担程度',range:[1,10]}},summary:{queue_total:DATA.songs.length,completed:entries.length,remaining:DATA.songs.length-entries.length,completed_by_gap:{both:entries.filter(e=>e.requirements.tag&&e.requirements.zmpd).length,tag_only:entries.filter(e=>e.requirements.tag&&!e.requirements.zmpd).length,zmpd_only:entries.filter(e=>!e.requirements.tag&&e.requirements.zmpd).length}},reviews:entries};const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)+'\n'],{type:'application/json'})),link=document.createElement('a');link.href=url;link.download=`song_combined_annotations_${today()}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);toast(`已导出 ${entries.length} 首完成标注`)}
    function render(){renderQueue();metrics();renderEditor()}
    function init(){const artists=[...new Set(DATA.songs.map(s=>s.artist))].sort((a,b)=>a.localeCompare(b));$('artist').innerHTML+=artists.map(a=>`<option value="${esc(a)}">${esc(a)}</option>`).join('');[['search','input'],['artist','change'],['gap','change'],['status','change']].forEach(([id,event])=>$(id).addEventListener(event,e=>{state[id]=e.target.value;render()}));$('export').addEventListener('click',exportJson);state.activeId=filtered()[0]?.id||DATA.songs[0]?.id||null;render()}init();
  </script>
</body>
</html>'''


def main() -> None:
    payload = build_combined_payload()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT_PATH.write_text(TEMPLATE.replace("__PAYLOAD__", encoded), encoding="utf-8")
    counts = {kind: sum(song["gap_type"] == kind for song in payload["songs"]) for kind in ("both", "tag", "zmpd")}
    print(f"Built {OUTPUT_PATH.name}: {len(payload['songs'])} tracks {counts}")


if __name__ == "__main__":
    main()
