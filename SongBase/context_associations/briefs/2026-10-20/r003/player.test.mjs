import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const page = fs.readFileSync(new URL('./完整歌单.html', import.meta.url), 'utf8');
const script = id => {
  const match = page.match(new RegExp(`<script[^>]*id="${id}"[^>]*>([\\s\\S]*?)<\\/script>`));
  assert.ok(match, `${id} must be embedded so the page works from file://`);
  return match[1];
};
const data = JSON.parse(script('playlist-data'));
const sandbox = {Intl, Date};
vm.runInNewContext(script('playlist-timeline'), sandbox);
const timeline = sandbox.PlaylistTimeline;
assert.equal(data.entries.length, 120);
assert.equal(data.entries.at(-1).end, 32400);
for (let i = 0; i < data.entries.length; i++) {
  const e = data.entries[i];
  assert.equal(e.start, i ? data.entries[i - 1].end : 0);
  const position = timeline.locate(data.entries, e.start);
  assert.equal(position.index, i, 'exact boundaries select the next song');
  assert.equal(position.offset, 0);
  assert.ok(fs.existsSync(new URL(e.src, new URL('./完整歌单.html', import.meta.url))));
}
const third = data.entries[2];
assert.equal(timeline.locate(data.entries, third.start - .001).index, 1);
assert.equal(timeline.locate(data.entries, third.start + 40).offset, 40);
assert.equal(timeline.clock(data.startAt, third.start), '09:39:41');
assert.equal(timeline.clock(data.startAt, data.entries[107].start), '17:32:27');
const final = timeline.locate(data.entries, 999999);
assert.equal(final.index, 119);
assert.ok(Math.abs(final.offset - 430.013) < .001, 'last track stops at the planned trim');
assert.equal(timeline.clock(data.startAt, final.position), '18:30:00');
assert.equal(timeline.locate(data.entries, -5).position, 0);
assert.equal(timeline.locate(data.entries, NaN).position, 0);
console.log('Passed: 120 local audio paths, continuous plan, exact boundaries, seeking, scene clocks, final trim.');

// Exercise the actual controller with media events, without playing through nine hours.
const elements = new Map();
function element(id) {
  if (!elements.has(id)) elements.set(id, {
    textContent: id === 'playlist-data' ? JSON.stringify(data) : '', value: '0', attrs: {},
    append() {}, setAttribute(k,v) {this.attrs[k]=v;}, getAttribute(k) {return this.attrs[k] || null;},
    removeAttribute(k) {delete this.attrs[k];}, classList: {toggle() {}}, dataset: {},
  });
  return elements.get(id);
}
const media = element('playlist-audio');
Object.assign(media, {
  paused: true, ended: false, currentTime: 0, duration: Infinity,
  pause() {this.paused=true;}, load() {this.currentTime=0;this.ended=false;},
  play() {this.paused=false;return Promise.resolve();},
});
Object.defineProperty(media, 'src', {get() {return this.attrs.src;},set(v) {this.attrs.src=v;}});
const controller = {
  document: {getElementById:element, createElement:()=>element(`option-${elements.size}`), querySelectorAll:()=>[], querySelector:()=>null},
  window:{addEventListener() {}}, Intl, Date, console,
  URL:{revokeObjectURL() {},createObjectURL:()=> 'blob:test'},
};
vm.createContext(controller);
vm.runInContext(script('playlist-timeline'), controller);
vm.runInContext(script('playlist-controller'), controller);
media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 1 \/ 120/);
media.play();media.currentTime=17.5;media.ontimeupdate();
assert.equal(element('playlist-clock').textContent,'09:30:17');
element('playlist-next').onclick();media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 2 \/ 120/);
assert.equal(media.paused,false);
element('playlist-prev').onclick();media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 1 \/ 120/);
element('playlist-next').onclick();media.onloadedmetadata();
media.currentTime=data.entries[1].duration;media.ontimeupdate();media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 3 \/ 120/,'a finished song advances exactly once');
media.onended();
assert.match(element('playlist-now').textContent,/第 3 \/ 120/,'stale ended event must not skip a song');
media.ended=true;media.onended();media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 4 \/ 120/,'natural media end also advances');
const seek=element('playlist-position');
seek.value=data.entries[107].start+40;seek.oninput();
assert.equal(element('playlist-clock').textContent,'17:33:07');
seek.onchange();media.onloadedmetadata();
assert.match(element('playlist-now').textContent,/第 108 \/ 120/);
assert.equal(media.currentTime,40);
assert.equal(media.paused,false,'seeking during playback resumes the selected song');
const picker=element('playlist-track');picker.value='119';picker.onchange();media.onloadedmetadata();
media.currentTime=431;media.ontimeupdate();
assert.equal(media.paused,true);
assert.equal(element('playlist-clock').textContent,'18:30:00');
assert.ok(Math.abs(media.currentTime-430.013)<.001);
assert.match(element('playlist-status').textContent,/歌单已播放到计划结束/);
picker.value='0';picker.onchange();media.onloadedmetadata();
const duplicate={name:data.entries[0].filename};
element('playlist-folder').onchange({target:{files:[duplicate,duplicate]}});
assert.match(element('playlist-status').textContent,/多个同名音频/);
assert.equal(media.getAttribute('src'),null);
console.log('Passed controller: actual time update, prev/next setup, automatic advance once, scene seek/resume, final trim stop, ambiguous-audio rejection.');
