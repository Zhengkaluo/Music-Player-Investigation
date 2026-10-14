// Exercise the unchanged main-project generator with the upgraded v1 library.
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const { chromium } = require('/Users/kaluozheng/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');

const root = __dirname;
const run = path.join(root, 'catalog-upgrade-2026-10-11');
const source = '/Users/kaluozheng/MusicPlayer-FlowSystem/apps/playlist-generator';
const catalogue = path.join(run, '歌曲特征-1204首-待验证.json');
const types = {'.html':'text/html', '.js':'application/javascript', '.css':'text/css'};
const server = http.createServer((request, response) => {
  const relative = decodeURIComponent(new URL(request.url, 'http://localhost').pathname).slice(1) || 'index.html';
  const file = path.resolve(source, relative);
  if (!file.startsWith(source + path.sep) || !fs.existsSync(file)) { response.writeHead(404); response.end(); return; }
  response.setHeader('Content-Type', types[path.extname(file)] || 'application/octet-stream');
  fs.createReadStream(file).pipe(response);
});

(async () => {
  fs.writeFileSync(path.join(run,'browser-smoke-audit.json'),JSON.stringify({status:'running'})+'\n');
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const browser = await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless:true, args:['--autoplay-policy=no-user-gesture-required']});
  const context = await browser.newContext({viewport:{width:1440,height:1000}, reducedMotion:'reduce', acceptDownloads:true});
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  try {
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    const loadStart = Date.now();
    await page.locator('#catalogInput').setInputFiles(catalogue);
    await page.waitForFunction(() => document.querySelector('#catalogStatus').textContent.includes('1204 首特征已加载'), {timeout:180000});
    const loadSeconds = (Date.now()-loadStart)/1000;
    console.log(JSON.stringify({phase:'loaded',loadSeconds}));
    await page.locator('#musicInput').setInputFiles(path.join(root, 'SongResources'));
    const coverage = await page.locator('#coverage').innerText();
    assert(coverage.includes('1204 首可直接播放'), coverage);
    await page.locator('#generateCurves').click();
    const generationStart = Date.now();
    // Dispatch returns before the synchronous generator finishes so progress can be polled.
    const generation = page.locator('#buildPlaylist').click({timeout:300000});
    await generation;
    await page.locator('#playlist li').first().waitFor({timeout:300000});
    const generationSeconds = (Date.now()-generationStart)/1000;
    const summary = await page.locator('#playlistSummary').innerText();
    console.log(JSON.stringify({phase:'generated',generationSeconds,summary}));
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#exportPlaylist').click();
    const download = await downloadPromise;
    const exportedPath = path.join(run, 'browser-smoke-playlist.json');
    await download.saveAs(exportedPath);
    const playlist = JSON.parse(fs.readFileSync(exportedPath, 'utf8'));
    assert.equal(playlist.schemaVersion, 'flowset.browser-playlist/v1');
    assert(playlist.tracks.length > 10);
    assert.equal(new Set(playlist.tracks.map(track => track.filename)).size, playlist.tracks.length);
    assert(playlist.tracks.at(-1).endMinute >= 117.5 && playlist.tracks.at(-1).endMinute <= 124.5);
    assert(playlist.tracks.slice(1).every(track => track.transition && track.transition.risk < .5));
    await page.locator('#audio').evaluate(audio => {audio.muted = true;});
    await page.locator('#playPause').click();
    await page.waitForFunction(() => document.querySelector('#audio').currentTime > .5);
    const playback = await page.locator('#audio').evaluate(audio => ({time:audio.currentTime,duration:audio.duration,error:audio.error?.code || null}));
    assert(playback.duration > 0 && !playback.error);
    await page.locator('#playPause').click();
    // Isolated test profile only; this simulated event is never training evidence.
    await page.locator('#preferVariant').click();
    const feedbackPromise = page.waitForEvent('download');
    await page.locator('#exportFeedback').click();
    const feedback = await feedbackPromise;
    const feedbackPath = path.join(run, 'browser-smoke-feedback.json');
    await feedback.saveAs(feedbackPath);
    const feedbackData = JSON.parse(fs.readFileSync(feedbackPath, 'utf8'));
    assert.equal(feedbackData.catalog.trackCount, 1204);
    await page.screenshot({path:path.join(run,'browser-smoke.png'),fullPage:true});
    assert.deepEqual(errors, []);
    const audit = {status:'passed',generatorSource:source,tracks:1204,coverage,loadSeconds,generationSeconds,
      playlistSummary:summary,playlistTracks:playlist.tracks.length,
      actualDurationMinutes:playlist.tracks.at(-1).endMinute,
      maximumTransitionRisk:Math.max(...playlist.tracks.slice(1).map(track=>track.transition.risk)),
      feedbackExportReadable:true,playback,pageErrors:errors};
    fs.writeFileSync(path.join(run,'browser-smoke-audit.json'),JSON.stringify(audit,null,2)+'\n');
    console.log(JSON.stringify(audit));
  } finally {
    await browser.close();
    server.close();
  }
})().catch(error => {
  fs.writeFileSync(path.join(run,'browser-smoke-audit.json'),JSON.stringify({status:'failed',error:error.message})+'\n');
  console.error(error); server.close(); process.exitCode=1;
});
