'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const sent = [], events = new Map();
let receive;
const window = {
  chrome: { webview: {
    addEventListener: (name, callback) => { receive = callback; },
    postMessage: value => sent.push({ value }),
    postMessageWithAdditionalObjects: (value, files) => sent.push({ value, files })
  } },
  addEventListener: (name, callback) => events.set(name, callback)
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../ui/src/bridge.js'),'utf8'), { window, Map, Set, Promise, Error, Object, queueMicrotask, encodeURIComponent });
const api = window.lenticulizer;
const reply = (item, result) => receive({ data: { id: item.value.id, result } });
(async () => {
  const boot = api.bootstrap(); reply(sent.at(-1), { projectPath: 'C:\\one\\project.json' }); await boot;
  const first = api.solveSettings({ settings: { mode: 'Automatic' } }); const a = sent.at(-1);
  const second = api.solveSettings({ settings: { mode: 'Manual' } }); const b = sent.at(-1);
  reply(b, { mode: 'Manual' }); reply(a, { mode: 'Automatic' });
  assert.equal((await first).mode,'Automatic'); assert.equal((await second).mode,'Manual');
  assert.equal(a.value.projectPath,'C:\\one\\project.json');
  const change = api.patchProject({ settings: { mode: 'Semi-Automatic' } },'rebuild-pair');
  const changed = sent.at(-1);
  assert.equal(changed.value.args.priority,'rebuild-pair'); assert.equal(changed.value.args.patch.settings.mode,'Semi-Automatic');
  reply(changed,{ revision:4 }); await change;
  const denied = api.readProject(); receive({ data: { id:sent.at(-1).value.id, error:'The active project changed.' } });
  await assert.rejects(denied,/active project changed/);
  receive({ data:{ event:'project-updated',data:{ active_project_path:'C:\\two\\project.json', revision:8, project_switched:true } } });
  let buffered; api.onProjectUpdated(value => { buffered=value; }); await Promise.resolve();
  assert.equal(buffered.revision,8);
  const later = api.readProject(); assert.equal(sent.at(-1).value.projectPath,'C:\\two\\project.json');reply(sent.at(-1),{}); await later;
  const files = [{ name:'first.png' },{ name:'second.png' }]; const drop = api.getDroppedImages(files);
  assert.equal(sent.at(-1).files,files); assert.equal(sent.at(-1).value.method,'images:dropped');reply(sent.at(-1),[]);await drop;
  const recognized = api.importDroppedFiles(files);
  assert.equal(sent.at(-1).files,files); assert.equal(sent.at(-1).value.method,'files:import');
  assert.equal(sent.at(-1).value.args.target,'auto'); assert.equal(sent.at(-1).value.projectPath,'C:\\two\\project.json');
  reply(sent.at(-1),{ project:{ revision:9 },heightmapImported:true });
  assert.equal((await recognized).heightmapImported,true);
  const explicit = api.importDroppedFiles(files,'heightmap');
  assert.equal(sent.at(-1).value.args.target,'heightmap');
  receive({ data:{ id:sent.at(-1).value.id,error:'Drop one heightmap at a time.' } });
  await assert.rejects(explicit,/one heightmap/);
  const asset = new URL(api.assetUrl("C:\\images\\name # &'s.png",19));
  assert.equal(asset.origin,'https://lenticulizer.app');assert.equal(asset.searchParams.get('path'),"C:\\images\\name # &'s.png");assert.equal(asset.searchParams.get('v'),'19');assert.equal(asset.hash,'');
  const closing = api.readProject(); events.get('pagehide')();await assert.rejects(closing,/interface was closed/);
  assert.equal(Object.isFrozen(api),true);
  console.log('PASS: WebView2 bridge checks: out-of-order replies, settings/rebuild intent, project binding, startup update buffering, errors, native dropped files, special-character asset URLs and shutdown.');
})().catch(error => { console.error(error); process.exitCode=1; });
