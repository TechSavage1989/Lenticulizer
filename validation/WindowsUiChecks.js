(async () => {
  const checks = [];
  let requestId = 900000;
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
  const check = (value, label) => { if (!value) throw new Error(label); checks.push(label); };
  function imagePixels(img) {
    const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
    const ctx = canvas.getContext('2d'); ctx.drawImage(img, 0, 0, 1, 1);
    return Array.from(ctx.getImageData(0, 0, 1, 1).data);
  }
  function checkTexture(img, label) {
    const canvas = document.createElement('canvas');
    const gl = canvas.getContext('webgl'); check(!!gl, `${label}: WebGL available`);
    const texture = gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, img);
    check(gl.getError() === gl.NO_ERROR, `${label}: image accepted as a WebGL texture`);
    gl.deleteTexture(texture);
    const release = gl.getExtension('WEBGL_lose_context'); if (release) release.loseContext();
  }
  async function wait(test, label) {
    const limit = Date.now() + 15000;
    while (!await test()) { if (Date.now() > limit) throw new Error(`Timed out: ${label}`); await pause(40); }
  }
  function native(method, args = {}) {
    const id = ++requestId;
    return new Promise((resolve, reject) => {
      const receive = event => {
        if (event.data.id !== id) return;
        chrome.webview.removeEventListener('message', receive);
        if (event.data.error) reject(new Error(event.data.error)); else resolve(event.data.result);
      };
      chrome.webview.addEventListener('message', receive);
      chrome.webview.postMessage({ id, method, args });
    });
  }
  try {
    await wait(() => document.getElementById('backendStatus').textContent === 'Processing ready', 'initialization');
    const api = window.lenticulizer;
    const viewState=window.__lenticulizerDiagnostics.view();
    check(viewState.yaw===0 && viewState.pitch===0,'3D preview starts in Front view');
    const radio = mode => Array.from(document.querySelectorAll('input[name="settings-mode"]')).find(input => input.value === mode);
    const nav = page => document.querySelector(`.nav-item[data-page="${page}"]`).click();
    const modes = ['Automatic', 'Semi-Automatic', 'Manual'];
    for (const mode of modes) {
      radio(mode).click();
      await wait(async () => (await api.readProject()).settings.mode === mode, `${mode} saved`);
      check(radio(mode).checked, `${mode} selected`);
      check(document.getElementById('printProfile').disabled === (mode === 'Automatic'), `${mode} profile control state`);
      check(document.querySelectorAll('input[name="settings-mode"]:checked').length === 1, `${mode} exclusive selection`);
    }
    const thickness = document.getElementById('printProfile');
    thickness.value = 'Manual Thickness'; thickness.dispatchEvent(new Event('change', { bubbles: true }));
    check(!document.getElementById('manualThickness').disabled, 'Manual thickness available');
    for (const page of ['project','sources','optics','output','calibration','blender']) {
      nav(page);
      const main = document.querySelector('.main-pane'); main.scrollTop = main.scrollHeight;
      await pause(40);
      const pane = main.getBoundingClientRect(), bar = document.querySelector('.settings-mode-bar').getBoundingClientRect();
      check(bar.top >= pane.top && bar.bottom <= pane.bottom, `Mode selector stays visible on ${page}`);
      for (const mode of modes) {
        const bounds = radio(mode).getBoundingClientRect();
        check(bounds.width >= 65 && bounds.height >= 30 && bounds.right <= pane.right, `${page}: ${mode} target fits`);
      }
      main.scrollTop = 0;
    }
    radio('Automatic').click(); await pause(450);
    const paths = await native('ui-check:fixtures');
    const written = await api.patchProject({ settings: { width_mm: 8, height_mm: 6, workflow: 'Build from source frames', mode: 'Automatic' }, assets: { source_frames: paths } }, 'rebuild-pair');
    await wait(async () => { const p = await api.readProject(); return p.revision > written.revision && p.generation.status === 'ready'; }, 'integrated generation');
    nav('sources');
    await wait(() => document.querySelectorAll('.source-thumb').length === 3 && Array.from(document.querySelectorAll('.source-thumb')).every(img => img.complete && img.naturalWidth > 0), 'source thumbnails');
    check(true, 'Native image bridge displays red, yellow and blue source thumbnails');
    const expected = [[255,0,0,255],[255,255,0,255],[0,0,255,255]];
    for (let i = 0; i < 3; i++) {
      const img = document.querySelectorAll('.source-thumb')[i];
      check(new URL(img.src).origin === location.origin, `Source ${i}: same origin`);
      check(imagePixels(img).every((value, channel) => Math.abs(value - expected[i][channel]) <= 1), `Source ${i}: decoded pixels match fixture`);
      checkTexture(img, `Source ${i}`);
      img.click();
      await wait(() => { const selected = document.getElementById('sidePreviewImage'); return selected.complete && selected.naturalWidth === 32 + i; }, `Selected image ${i}`);
    }
    nav('output');
    await wait(() => ['outputInterlacedImage','outputHeightmapImage'].every(id => document.getElementById(id).naturalWidth > 0), 'generated previews');
    for (const id of ['outputInterlacedImage','outputHeightmapImage']) {
      const img = document.getElementById(id); check(imagePixels(img)[3] === 255, `${id}: readable opaque canvas pixels`); checkTexture(img, id);
    }
    const previousUrl = document.getElementById('outputInterlacedImage').src;
    const rebuilt = await api.patchProject({settings: {orientation: 'Horizontal'}}, 'rebuild-pair');
    await wait(async () => { const p = await api.readProject(); return p.revision > rebuilt.revision && p.generation.status === 'ready'; }, 'horizontal rebuild');
    await wait(() => document.getElementById('outputInterlacedImage').src !== previousUrl && ['outputInterlacedImage','outputHeightmapImage'].every(id => { const img = document.getElementById(id); return img.complete && img.naturalWidth > 0; }), 'regenerated preview refresh');
    check(true, 'Both generated previews reload after orientation changes');
    check(!document.getElementById('outputExportBothButton').disabled, 'Matching pair is exportable');
    check(!document.getElementById('outputGeneratePairButton').disabled, 'Output generation action enabled');
    for (let i = 0; i < 12; i++) { radio(modes[i % 3]).click(); await pause(12); }
    radio('Semi-Automatic').click();
    await wait(async () => { const p = await api.readProject(); return p.settings.mode === 'Semi-Automatic' && p.generation.status === 'ready'; }, 'latest mode');
    await pause(500);
    check(radio('Semi-Automatic').checked, 'Older calculation or generation cannot revert the selected mode');
    const current=await api.readProject(), ref=current.assets.heightmap;
    const imported=await api.patchProject({assets:{reference_heightmap:ref},settings:{reference_heightmap_width_mm:current.settings.width_mm,reference_heightmap_height_mm:current.settings.height_mm,reference_heightmap_thickness_mm:current.settings.thickness_mm,reference_heightmap_detection:'Automatic',reference_heightmap_show:true}},'reference');
    await wait(async()=>{const p=await api.readProject();return p.revision>imported.revision && p.reference_heightmap_info?.ok===true;},'reference detection');
    nav('sources');
    await wait(()=>!document.getElementById('referenceHeightmapFields').classList.contains('hidden') && document.getElementById('referenceHeightmapImage').naturalWidth>0,'reference preview image');
    check(document.getElementById('referencePitch').disabled,'automatic detection locks manual pitch');
    check(window.__lenticulizerDiagnostics.geometry().imported,'reference geometry uses imported samples');
    document.getElementById('referenceBuildButton').click();
    await wait(async()=>{const p=await api.readProject();return p.settings.workflow==='Build from heightmap' && p.generation.status==='ready' && p.assets.interlaced_image!==current.assets.interlaced_image;},'heightmap input build');
    check(document.getElementById('widthMm').disabled && document.getElementById('lpi').readOnly,'imported geometry controls are authoritative');
    const pairBefore=(await api.readProject()).assets;
    const style=document.getElementById('referenceStyle');style.value='TINTED';style.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(async()=>{const p=await api.readProject();return p.settings.reference_heightmap_display_style==='TINTED' && p.generation.status==='ready';},'reference display sync');
    const afterStyle=(await api.readProject()).assets;
    check(pairBefore.interlaced_image===afterStyle.interlaced_image && pairBefore.heightmap===afterStyle.heightmap,'display changes preserve generated files');
    document.getElementById('side3dLeft').click();
    const rotated=window.__lenticulizerDiagnostics.view();
    const changed=await api.patchProject({settings:{phase_pitch:.1}},'rebuild-pair');
    await wait(async()=>{const p=await api.readProject();return p.revision>changed.revision && p.generation.status==='ready';},'imported registration update');
    const kept=window.__lenticulizerDiagnostics.view();check(kept.yaw===rotated.yaw && kept.pitch===rotated.pitch,'regeneration preserves the chosen 3D view');
    chrome.webview.postMessage({ id: ++requestId, method: 'ui-check:result', args: { ok: true, checks } });
  } catch (error) {
    chrome.webview.postMessage({ id: ++requestId, method: 'ui-check:result', args: { ok: false, checks, error: error.message, stack: error.stack } });
  }
})();
