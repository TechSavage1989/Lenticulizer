'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const script = fs.readFileSync(path.join(__dirname,'../ui/src/renderer.js'),'utf8');
const calls = [], status = [], navigations = [], previews = [], windows = new Map(), elements = new Map();
let rejectNext = false, failPublish = false, active = 0, maximumActive = 0;
for (const id of ['sourceGrid','projectDropZone','referenceHeightmapCard','preview3dTab']) {
  const events = new Map(), classes = new Set();
  elements.set(id, { events, classList:{ add:x=>classes.add(x), remove:x=>classes.delete(x) },
    addEventListener:(name,callback)=>events.set(name,callback), contains:()=>false,
    click:()=>previews.push(id), scrollIntoView:()=>previews.push(id+':scroll') });
}
const context = vm.createContext({
  $, window:{ addEventListener:(name,callback)=>windows.set(name,callback) }, Promise, Array,
  api:{ importDroppedFiles:async (files,target)=>{
    active++;maximumActive=Math.max(maximumActive,active);calls.push({files,target});
    await new Promise(resolve=>setImmediate(resolve));active--;
    if (rejectNext) {rejectNext=false;throw new Error('Import failed');}
    return {project:{revision:calls.length},heightmapImported:target==='heightmap'||files.some(f=>f.name==='map.png'),sourcesAdded:target==='heightmap'?0:1,message:'Native import result'};
  }},
  publishNow:async()=>!failPublish, updateFromProject:project=>assert.ok(project.revision>0),
  setStatus:message=>status.push(message),activatePage:page=>navigations.push(page)
});
function $(id){return elements.get(id);}
vm.runInContext(script.slice(script.indexOf('  function imageExtensionOk('),script.indexOf('  function setupSplitters()')),context);
vm.runInContext('setupSourceDropZone()',context);
function event(files,types=['Files']){
  return {dataTransfer:{files,types},prevented:false,stopped:false,
    preventDefault(){this.prevented=true;},stopPropagation(){this.stopped=true;}};
}
function drop(id, files){
  const e=event(files);
  if(id)elements.get(id).events.get('drop')(e);
  if(!e.stopped)windows.get('drop')(e);
  return {e,done:vm.runInContext('fileDropQueue',context)};
}
(async()=>{
  for(const id of ['sourceGrid','projectDropZone',null]){
    const file={name:'map.png'}, prior=calls.length; const pending=drop(id,[file]);await pending.done;
    assert.equal(calls.length,prior+1,'one import per drop, including bubbled events');
    assert.equal(calls.at(-1).target,'auto');assert.equal(calls.at(-1).files[0],file);
    assert.equal(pending.e.prevented,true);assert.equal(status.at(-1),'Native import result');
  }
  const explicit=drop('referenceHeightmapCard',[{name:'ambiguous.tiff'}]);await explicit.done;
  assert.equal(explicit.e.stopped,true);assert.equal(calls.at(-1).target,'heightmap');
  assert.ok(previews.includes('preview3dTab'));assert.ok(previews.includes('referenceHeightmapCard:scroll'));
  const unsupported=calls.length;await drop(null,[{name:'notes.txt'}]).done;
  assert.equal(calls.length,unsupported);assert.match(status.at(-1),/Drop PNG/);
  const internal=event([],['application/x-lenticulizer-source-index']);windows.get('drop')(internal);
  assert.equal(internal.prevented,false);assert.equal(calls.length,unsupported,'internal reorder is not an import');
  const first=drop('sourceGrid',[{name:'first.jpg'}]),second=drop('sourceGrid',[{name:'second.png'}]);
  await Promise.all([first.done,second.done]);
  assert.equal(maximumActive,1,'drop gestures are serialized');
  assert.equal(calls.at(-2).files[0].name,'first.jpg');assert.equal(calls.at(-1).files[0].name,'second.png');
  rejectNext=true;await drop(null,[{name:'bad.png'}]).done;assert.equal(status.at(-1),'Import failed');
  await drop(null,[{name:'next.jpg'}]).done;assert.equal(status.at(-1),'Native import result','queue recovers after import failure');
  failPublish=true;const prior=calls.length;await drop(null,[{name:'pending.png'}]).done;
  assert.equal(calls.length,prior,'failed settings commit prevents import');
  assert.ok(navigations.every(page=>page==='sources'));
  console.log('PASS: actual drop UI handlers: automatic/dedicated routing, native File objects, bubbling, project-page status, reference navigation, internal reorder, gesture order and error recovery.');
})().catch(error=>{console.error(error);process.exitCode=1;});
