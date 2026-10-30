(() => {
  const browserPreviewProject = {
    schema: 1, revision: 1, changed_by: 'preview',
    assets: { interlaced_image: '', heightmap: '', source_frames: [] },
    settings: {
      mode: 'Automatic', output_mode: 'Lenticular Lens', relief_prism_height_mm: 0.8,
      workflow: 'Build from source frames', width_mm: 100, height_mm: 100, lpi: 24,
      lpi_helper_mode: 'Recommended', lpi_helper_preset: 'Balanced', views: 2, printer_dpi: 1440,
      build_detail_mode: 'Auto from printer DPI', pixels_per_lenticule: 60, orientation: 'Vertical',
      lens_profile: 'Auto Recommended', print_profile: 'Recommended (Reference Calibrated)',
      manual_thickness_mm: 1.0, base_mode: 'Recommended (Reference Calibrated)', manual_base_mm: 0.3,
      thickness_mm: 1.0, base_mm: 0.3, rise_mm: 0.7, viewing_angle_mode: 'Standard',
      custom_viewing_angle_deg: 44, viewing_angle_deg: 44, ior: 1.55, backing_mm: 5.0, backing_enabled: true, backing_saved_mm: 5.0, phase_pitch: 0
    }
  };

  const api = window.lenticulizer || {
    bootstrap: async () => ({ version: '3.0.0-alpha.32', sessionDir: 'Browser Preview', projectPath: 'Browser preview only', project: browserPreviewProject, backendExists: false, blenderAddon: '', blenderAddonExists: false }),
    startBackend: async () => ({ ok: false, error: 'Browser preview only' }),
    backendStatus: async () => ({ running: false }),
    runtimeNotices: async () => false,
    updateStatus: async () => ({ state: 'unavailable', installedVersion: '3.0.0-alpha.32', latestVersion: '', message: 'Browser preview only', notes: [], canDownload: false, canInstall: false }),
    checkForUpdates: async () => ({ state: 'unavailable', installedVersion: '3.0.0-alpha.32', latestVersion: '', message: 'Browser preview only', notes: [], canDownload: false, canInstall: false }),
    downloadUpdate: async () => ({ state: 'error', message: 'Browser preview only' }),
    installUpdate: async () => ({ ok: false, error: 'Browser preview only' }),
    openUpdateRelease: async () => false,
    solveSettings: async (patch) => ({ ok: true, settings: { ...browserPreviewProject.settings, ...(patch.settings || {}) } }),
    patchProject: async (patch) => {
      browserPreviewProject.settings = { ...browserPreviewProject.settings, ...(patch.settings || {}) };
      browserPreviewProject.assets = { ...browserPreviewProject.assets, ...(patch.assets || {}) };
      browserPreviewProject.revision += 1;
      return browserPreviewProject;
    },
    readProject: async () => browserPreviewProject,
    addImages: async () => [], importInterlaced: async () => null, importHeightmap: async () => null, analyzeHeightmap: async () => null,
    getPathForFile: () => '',
    showPath: async () => false, openPath: async () => false, exportBothAssets: async () => ({ ok: false, error: 'Browser preview only' }), exportAsset: async () => ({ ok: false, error: 'Browser preview only' }),
    onProjectUpdated: () => {}, onBackendStatus: () => {}, onUpdateStatus: () => {}
  };

  const $ = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const degToRad = (v) => v * Math.PI / 180;
  const wrap01 = (v) => ((v % 1) + 1) % 1;

  let bootstrap = null;
  let project = null;
  let sourceItems = [];
  let currentWorkflow = 'Build from source frames';
  let writeTimer = null;
  let solveTimer = null;
  let solveSequence = 0;
  let appliedSolveSequence = 0;
  let outgoingBuildSequence = 0;
  let lastSolvedSettings = null;
  let selectedSourcePreviewPath = '';
  let resultPreviewPath = '';
  let heightmapPreviewPath = '';
  let draggedSourceIndex = -1;
  let displayUnit = 'mm';
  let settingsDirty = false;
  let deferredProject = null;
  let updateState = null;
  let dismissedUpdateVersion = '';

  const controls = {
    printerDpi: $('printerDpi'), settingsMode: $('settingsMode'), outputMode: $('outputMode'),
    widthMm: $('widthMm'), heightMm: $('heightMm'), units: $('units'), orientation: $('orientation'),
    lpi: $('lpi'), views: $('views'), lpiMode: $('lpiMode'), lpiPreset: $('lpiPreset'),
    buildDetail: $('buildDetail'), pixelsPerLens: $('pixelsPerLens'), lensProfile: $('lensProfile'),
    printProfile: $('printProfile'), manualThickness: $('manualThickness'), ior: $('ior'),
    baseMode: $('baseMode'), manualBase: $('manualBase'), viewingAngleMode: $('viewingAngleMode'),
    customAngle: $('customAngle'), reliefHeight: $('reliefHeight'), phase: $('phase'), backingEnabled: $('backingEnabled'), backingMm: $('backingMm'),
    calibrationMode: $('calibrationMode'), calibrationCouponSize: $('calibrationCouponSize')
  };

  function num(el, fallback) {
    const value = Number(el && el.value);
    return Number.isFinite(value) ? value : fallback;
  }

  function setStatus(message) { if ($('statusMessage')) $('statusMessage').textContent = message; document.querySelectorAll('.status-mirror').forEach(el => { el.textContent = message || 'Ready'; }); }

  function updateBackendStatus(running, text) {
    const pill = $('backendStatus');
    if (!pill) return;
    pill.classList.toggle('status-good', !!running);
    pill.classList.toggle('status-warn', !running);
    pill.textContent = text || (running ? 'Processing ready' : 'Initializing processing');
  }

  function formatBytes(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return '';
    if (bytes >= 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
    if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${Math.round(bytes / 1024)} KB`;
  }

  function renderUpdateStatus(value, manual = false) {
    if (!value || typeof value !== 'object') return;
    updateState = value;
    const installed = value.installedVersion || bootstrap?.version || 'Unknown';
    const latest = value.latestVersion || '';
    if ($('helpInstalledVersion')) $('helpInstalledVersion').textContent = installed;
    if ($('helpLatestVersion')) $('helpLatestVersion').textContent = latest || (value.state === 'checking' ? 'Checking…' : 'No published release');
    if ($('helpUpdateStatus')) $('helpUpdateStatus').textContent = value.message || value.state || 'Unknown';

    const banner = $('updateBanner');
    if (!banner) return;
    const visibleState = ['available', 'downloaded', 'downloading', 'error', 'offline', 'deferred'].includes(value.state);
    const dismissed = latest && dismissedUpdateVersion === latest && value.state === 'available';
    banner.classList.toggle('hidden', !visibleState || dismissed);
    banner.className = `update-banner${(!visibleState || dismissed) ? ' hidden' : ''} state-${value.state || 'idle'}`;

    let headline = 'Update status';
    if (value.state === 'available') headline = 'Update available';
    else if (value.state === 'downloaded') headline = 'Update ready to install';
    else if (value.state === 'downloading') headline = 'Downloading update';
    else if (value.state === 'error') headline = 'Update check failed';
    else if (value.state === 'offline') headline = 'Update check unavailable';
    else if (value.state === 'deferred') headline = 'Update check paused';
    $('updateHeadline').textContent = headline;
    const progress = value.state === 'downloading' && Number(value.totalBytes) > 0 ? ` · ${formatBytes(value.downloadedBytes)} / ${formatBytes(value.totalBytes)}` : '';
    $('updateVersionText').textContent = latest ? `${installed} → ${latest}${progress}` : `${value.message || ''}${progress}`;

    const notes = Array.isArray(value.notes) ? value.notes.slice(0, 3) : [];
    const list = $('updateNotes');
    list.replaceChildren(...notes.map(note => { const li = document.createElement('li'); li.textContent = note; return li; }));
    const download = $('updateDownloadButton');
    const install = $('updateInstallButton');
    const readMore = $('updateReadMoreButton');
    download.classList.toggle('hidden', !value.canDownload && value.state !== 'downloading');
    download.disabled = value.state === 'downloading';
    download.textContent = value.state === 'downloading' ? 'Downloading…' : 'Download';
    install.classList.toggle('hidden', !value.canInstall);
    readMore.classList.toggle('hidden', !value.readMoreUrl);
    if (manual) setStatus(value.message || 'Update check complete.');
  }

  function setupUpdates() {
    $('manualUpdateCheckButton')?.addEventListener('click', async () => {
      $('helpUpdateStatus').textContent = 'Checking…';
      try { renderUpdateStatus(await api.checkForUpdates(), true); }
      catch (error) { setStatus(`Update check failed: ${error.message || error}`); }
    });
    $('updateDownloadButton')?.addEventListener('click', async () => {
      try { renderUpdateStatus(await api.downloadUpdate(), true); }
      catch (error) { setStatus(`Update download failed: ${error.message || error}`); }
    });
    $('updateInstallButton')?.addEventListener('click', async () => {
      try {
        const result = await api.installUpdate();
        if (result?.installing) setStatus(`Installing ${result.version || 'update'} and restarting…`);
      } catch (error) { setStatus(`Update install failed: ${error.message || error}`); }
    });
    $('updateReadMoreButton')?.addEventListener('click', async () => {
      try { await api.openUpdateRelease(); } catch (error) { setStatus(`Could not open release notes: ${error.message || error}`); }
    });
    $('updateDismissButton')?.addEventListener('click', () => {
      dismissedUpdateVersion = updateState?.latestVersion || '';
      $('updateBanner')?.classList.add('hidden');
    });
  }

  function setWorkflow(value) {
    currentWorkflow = ['Use existing interlaced image', 'Build from heightmap'].includes(value) ? value : 'Build from source frames';
    const badge = $('workflowBadge');
    if (badge) badge.textContent = currentWorkflow === 'Build from source frames' ? 'Source images' : currentWorkflow === 'Build from heightmap' ? 'Imported heightmap' : 'Existing interlaced';
    updateControlStates(true);
    updateSourceActionState();
  }

  const referenceFields = {
    referenceWidth: ['reference_heightmap_width_mm', 100], referenceHeight: ['reference_heightmap_height_mm', 100],
    referenceScale: ['reference_heightmap_thickness_mm', 1.86], referenceOrientation: ['reference_heightmap_orientation', 'Vertical'],
    referenceDetection: ['reference_heightmap_detection', 'Automatic'], referencePitch: ['reference_heightmap_pitch_px', 0],
    referencePhase: ['reference_heightmap_phase_pitch', 0], referenceStyle: ['reference_heightmap_display_style', 'OPAQUE']
  };
  function referencePatch() {
    return Object.fromEntries(Object.entries(referenceFields).map(([id,[key,fallback]]) => [key, typeof fallback === 'number' ? num($(id), fallback) : $(id).value]));
  }
  function updateReferenceControls(next) {
    const s=next.settings||{}, info=next.reference_heightmap_info||{}, path=next.assets?.reference_heightmap||'';
    $('referenceHeightmapEmpty').classList.toggle('hidden',!!path);
    $('referenceHeightmapFields').classList.toggle('hidden',!path);
    for (const [id,[key,fallback]] of Object.entries(referenceFields)) setControlValue($(id), s[key] ?? fallback);
    for (const id of ['referenceOrientation','referencePitch','referencePhase']) $(id).disabled = $('referenceDetection').value !== 'Manual';
    const image=$('referenceHeightmapImage'), url=fileUrl(path,next.revision||0);
    if (path && image.getAttribute('src')!==url) image.src=url;
    if (!path) image.removeAttribute('src');
    const referenceName=path.split(/[\/]/).pop()||'';
    $('referenceHeightmapName').textContent=referenceName;
    if ($('referenceSummaryName')) $('referenceSummaryName').textContent = referenceName || 'Optional';
    if ($('referenceSummaryStatus')) $('referenceSummaryStatus').textContent = path ? (currentWorkflow === 'Build from heightmap' ? 'Controls the current build' : 'Loaded for inspection') : 'No reference loaded';
    const details=$('referenceHeightmapCard');
    if (details && details.tagName === 'DETAILS') {
      if (!path) { details.open = false; delete details.dataset.lastPath; }
      else if (details.dataset.lastPath !== path) { details.open = true; details.dataset.lastPath = path; }
    }
    const pitch=Number(s.reference_heightmap_pitch_px||0), axis=s.reference_heightmap_orientation==='Horizontal'?'height':'width';
    const lpi=pitch>0?Number(info[axis+'_px']||0)*25.4/(Number(s['reference_heightmap_'+axis+'_mm']||100)*pitch):0;
    $('referenceHeightmapAnalysis').textContent=(info.message||'Reading heightmap...')+(pitch>0?` ${pitch.toFixed(6)} pixels/lens; ${lpi.toFixed(4)} LPI; ${s.reference_heightmap_orientation}.`:'')+(info.confidence!=null?` Confidence ${Math.round(info.confidence*100)}%.`:'');
    const notes=[];
    if (!(info.width_mm>0 && info.height_mm>0)) notes.push('No physical-size metadata: current project dimensions were used at import. Set the actual width and height.');
    if (!(info.scale_mm>0)) notes.push('No height-scale metadata: current thickness was used at import. Set the height represented by white.');
    notes.push('Black is zero height. The original file stays unchanged. Clear and tinted display are inspection styles.');
    $('referenceHeightmapScaleHint').textContent=notes.join(' ');
    $('referenceBuildButton').disabled=!path || info.grayscale===false || !((s.reference_heightmap_detection==='Manual' && pitch>=2)||info.ok);
    $('referenceProceduralButton').classList.toggle('hidden',currentWorkflow!=='Build from heightmap');
    $('referencePreviewButton').classList.toggle('active',!!s.reference_heightmap_show);
    $('referenceProjectButton').classList.toggle('active',!s.reference_heightmap_show);
  }
  async function importHeightmap() {
    await publishNow('settings');
    const next=await api.importHeightmap();
    if (!next) return;
    updateFromProject(next); activatePage('sources'); $('preview3dTab').click();
    setStatus('Heightmap imported. Review the scale and detection, then choose Build from heightmap.');
  }
  async function analyzeHeightmap() {
    await publishNow('reference');
    const next=await api.analyzeHeightmap(); if(next) updateFromProject(next);
  }
  function bindReferenceControls() {
    $('importHeightmapButton').addEventListener('click',importHeightmap);
    $('referenceAnalyzeButton').addEventListener('click',analyzeHeightmap);
    $('referenceBuildButton').addEventListener('click',async()=>{
      setWorkflow('Build from heightmap');
      await publishNow('rebuild-pair',{settings:{workflow:'Build from heightmap',reference_heightmap_show:false,phase_pitch:0}});
      $('preview3dTab').click();
    });
    $('referenceProceduralButton').addEventListener('click',async()=>{
      setWorkflow('Build from source frames');
      await publishNow('rebuild-pair',{settings:{workflow:'Build from source frames',reference_heightmap_show:false,imported_heightmap_geometry:false}});
    });
    $('referenceClearButton').addEventListener('click',async()=>{
      const active=currentWorkflow==='Build from heightmap';
      if(active) setWorkflow('Build from source frames');
      await publishNow(active?'rebuild-pair':'reference',{assets:{reference_heightmap:''},settings:{reference_heightmap_show:false,imported_heightmap_geometry:false}});
    });
    for (const [id,shown] of [['referencePreviewButton',true],['referenceProjectButton',false]]) $(id).addEventListener('click',async()=>{
      await publishNow('reference',{settings:{reference_heightmap_show:shown}}); $('preview3dTab').click();
    });
    for(const id of Object.keys(referenceFields)) {
      const el=$(id);
      if(el.type==='number') { el.addEventListener('focus',()=>markEditing(el,true)); el.addEventListener('blur',()=>markEditing(el,false)); }
      el.addEventListener('change',async()=>{
        if(el.type==='number' && (!el.checkValidity()||!el.value)) { el.reportValidity();return; }
        for (const field of ['referenceOrientation','referencePitch','referencePhase']) $(field).disabled=$('referenceDetection').value!=='Manual';
        await publishNow(id==='referenceStyle'?'reference':currentWorkflow==='Build from heightmap'?'rebuild-pair':'reference');
      });
    }
  }

  function snapToViewMultiple(value, views) {
    const step = Math.max(1, Math.round(views || 1));
    let rounded = Math.round(Number(value || 0) / step) * step;
    if (rounded < step * 4) rounded = step * 4;
    if (rounded < 24) rounded = 24;
    if (rounded > 256) rounded = 256;
    return rounded;
  }

  function syncViewsToSourceCount() {
    if (currentWorkflow !== 'Use existing interlaced image' && sourceItems.length > 0 && controls.views) {
      controls.views.value = String(sourceItems.length);
    }
  }

  function updateControlStates(applyDerived = true) {
    if (!controls.settingsMode || !controls.lpiMode) return;
    const automatic = controls.settingsMode.value === 'Automatic';
    const semi = controls.settingsMode.value === 'Semi-Automatic';
    const relief = controls.outputMode.value === 'Lens-Free Relief';
    const importedMap = currentWorkflow === 'Build from heightmap';
    const buildMode = currentWorkflow !== 'Use existing interlaced image';

    document.querySelectorAll('input[name="settings-mode"]').forEach(option => {
      option.checked = option.value === controls.settingsMode.value;
    });
    const modeHints = relief ? {
      'Automatic': 'LPI and prism height follow the automatic recommendations.',
      'Semi-Automatic': 'Choose an LPI preset and prism height, with calculated settings kept in sync.',
      'Manual': 'Enter LPI and prism height directly. Choose Custom build quality to edit image detail.'
    } : {
      'Automatic': 'Print profile, base height and build quality are calculated automatically.',
      'Semi-Automatic': 'Choose print and base profiles and build quality; calculated values stay linked.',
      'Manual': 'Select manual thickness, manual base height or Custom build quality to edit their values.'
    };
    $('settingsModeHint').textContent = modeHints[controls.settingsMode.value] || '';

    if (buildMode && sourceItems.length > 0) controls.views.value = String(sourceItems.length);
    controls.views.readOnly = buildMode;

    // Match the stable v2 workflow behavior so controls never appear editable
    // when the native core will immediately normalize them to another mode.
    if (applyDerived && !importedMap) {
      if (buildMode && controls.lpiMode.value === 'Detect from image') controls.lpiMode.value = 'Recommended';
      if (!buildMode && controls.lpiMode.value === 'Recommended') controls.lpiMode.value = 'Detect from image';
      if (relief && automatic) controls.lpiMode.value = 'Recommended';
      if (relief && semi && controls.lpiMode.value === 'Detect from image') controls.lpiMode.value = 'Recommended';
      if (relief && controls.settingsMode.value === 'Manual') controls.lpiMode.value = 'Manual';
      if (automatic && controls.buildDetail) controls.buildDetail.value = 'Auto from printer DPI';
    }

    controls.lpiMode.disabled = relief && (automatic || controls.settingsMode.value === 'Manual');
    controls.lpi.readOnly = controls.lpiMode.value !== 'Manual';
    controls.lpiPreset.disabled = controls.lpiMode.value !== 'Recommended' || (relief && automatic);
    controls.buildDetail.disabled = !buildMode || automatic;
    controls.pixelsPerLens.disabled = !buildMode;
    controls.pixelsPerLens.readOnly = controls.buildDetail.value !== 'Custom' || automatic;

    if (controls.lensProfile) controls.lensProfile.disabled = relief;
    if (controls.printProfile) controls.printProfile.disabled = automatic || relief;
    if (controls.baseMode) controls.baseMode.disabled = automatic || relief;
    if (controls.ior) controls.ior.disabled = relief;
    if (controls.reliefHeight) controls.reliefHeight.disabled = !relief || automatic;
    if (controls.manualThickness) controls.manualThickness.disabled = automatic || relief || controls.printProfile.value !== 'Manual Thickness';
    if (controls.manualBase) controls.manualBase.disabled = automatic || relief || controls.baseMode.value !== 'Manual base height';
    if (controls.customAngle) controls.customAngle.disabled = relief || controls.viewingAngleMode.value !== 'Custom';
    if (controls.viewingAngleMode) controls.viewingAngleMode.disabled = relief;

    const setIrrelevant = (id, irrelevant) => { const el=$(id); if(el) el.classList.toggle('is-irrelevant', !!irrelevant); };
    setIrrelevant('manualThicknessField', relief || automatic || controls.printProfile.value !== 'Manual Thickness');
    setIrrelevant('manualBaseField', relief || automatic || controls.baseMode.value !== 'Manual base height');
    setIrrelevant('customAngleField', relief || controls.viewingAngleMode.value !== 'Custom');
    const backingEnabled = !controls.backingEnabled || !!controls.backingEnabled.checked;
    setIrrelevant('backingThicknessField', !backingEnabled);
    if (controls.backingMm) controls.backingMm.disabled = !backingEnabled;

    controls.widthMm.disabled = importedMap;
    controls.heightMm.disabled = importedMap;
    controls.orientation.disabled = importedMap;
    if (importedMap) {
      for (const name of ['lpiMode','lpiPreset','buildDetail','pixelsPerLens','lensProfile','printProfile','manualThickness','baseMode','manualBase','viewingAngleMode','customAngle','reliefHeight']) controls[name].disabled = true;
      controls.lpi.readOnly = true;
      $('settingsModeHint').textContent = 'The imported heightmap controls lens geometry and raster size. Adjust its physical scale and detection below.';
      $('interlaceControlHint').textContent = 'LPI follows the heightmap pitch and physical size. Source count supplies the views. The phase control adjusts image registration without changing the imported height samples.';
      return;
    }
    const views = Math.max(2, Math.min(8, Math.round(num(controls.views, sourceItems.length || 2))));
    const dpi = Math.max(1, Math.round(num(controls.printerDpi, 1440)));

    // Do not duplicate the v2 solver in JavaScript. Recommended LPI, build-detail
    // resolution, optical thickness/base and viewing-angle values are calculated by
    // the native core and returned in the next app-authored project revision.
    const hint = $('interlaceControlHint');
    if (hint) {
      const parts = [];
      if (controls.lpiMode.value === 'Recommended') parts.push(`${controls.lpiPreset.value} preset: ${num(controls.lpi, 0).toFixed(3).replace(/\.000$/, '')} LPI at ${dpi} DPI.`);
      else if (controls.lpiMode.value === 'Detect from image') parts.push('LPI is detected from the active interlaced image.');
      else parts.push('LPI is manually editable.');
      if (automatic) parts.push('Automatic settings mode keeps build quality on Auto from printer DPI.');
      else if (controls.buildDetail.value === 'Custom') parts.push('Custom build quality enables direct pixels-per-lenticule editing.');
      else parts.push(`${controls.buildDetail.value}: ${Math.round(num(controls.pixelsPerLens, 0))} pixels per lenticule.`);
      if (buildMode && sourceItems.length) parts.push(`Views follows the ${sourceItems.length} source images because each source image is one generated view.`);
      hint.textContent = parts.join(' ');
    }
  }

  function updateSourceActionState() {
    const assets = (project && project.assets) || {};
    const relief = controls.outputMode && controls.outputMode.value === 'Lens-Free Relief';
    const canBuild = currentWorkflow !== 'Use existing interlaced image' && sourceItems.length >= 2 && (!relief || sourceItems.length === 2);
    const hasInterlaced = !!assets.interlaced_image;
    const hasHeightmap = !!assets.heightmap;
    const mapReady = !!assets.reference_heightmap && (project?.settings?.reference_heightmap_detection === 'Manual' ? Number(project?.settings?.reference_heightmap_pitch_px) >= 2 : project?.reference_heightmap_info?.ok === true);
    const canGeneratePair = currentWorkflow === 'Build from heightmap' ? canBuild && mapReady : currentWorkflow === 'Build from source frames' ? canBuild : hasInterlaced;
    if ($('generatePairButton')) $('generatePairButton').disabled = !canGeneratePair;
    if ($('opticsGeneratePairButton')) $('opticsGeneratePairButton').disabled = !canGeneratePair;
    if ($('outputGeneratePairButton')) $('outputGeneratePairButton').disabled = !canGeneratePair;
    for (const id of ['outputExportInterlacedButton','outputShowInterlacedButton']) if ($(id)) $(id).disabled = !hasInterlaced;
    for (const id of ['outputExportHeightmapButton','outputShowHeightmapButton']) if ($(id)) $(id).disabled = !hasHeightmap;
    const pairReady = !project?.generation || project.generation.status === 'ready';
    if ($('outputExportBothButton')) $('outputExportBothButton').disabled = !(hasInterlaced && hasHeightmap && pairReady);
    if ($('exportTestSetButton')) $('exportTestSetButton').disabled = !(hasInterlaced && hasHeightmap && pairReady);
    if ($('sourceCountLabel')) $('sourceCountLabel').textContent = `${sourceItems.length} / 8 images`;
    if ($('projectSourceCount')) $('projectSourceCount').textContent = `${sourceItems.length} loaded`;
    if ($('analyzeButton')) {
      $('analyzeButton').disabled = currentWorkflow === 'Build from heightmap' || !hasInterlaced;
      $('analyzeButton').textContent = controls.lpiMode && controls.lpiMode.value === 'Detect from image' ? 'Analyze / Verify detected LPI' : 'Analyze / Verify LPI';
    }
    if ($('calibrationButton')) $('calibrationButton').disabled = currentWorkflow === 'Build from heightmap' || !hasInterlaced;
    if ($('calibrationButton')) $('calibrationButton').title = currentWorkflow === 'Build from heightmap' ? 'Use the registration control for imported heightmaps. Procedural calibration changes lens geometry.' : ''; 
    if ($('openBlenderButton')) $('openBlenderButton').disabled = !hasInterlaced;
    if ($('exportBlenderButton')) $('exportBlenderButton').disabled = !hasInterlaced;
  }

  function settingsPatch() {
    const views = Math.max(1, Math.min(8, Math.round(num(controls.views, 2))));
    return {
      settings: {
        ...referencePatch(),
        mode: controls.settingsMode.value,
        output_mode: controls.outputMode.value,
        relief_prism_height_mm: num(controls.reliefHeight, 0.8),
        workflow: currentWorkflow,
        width_mm: num(controls.widthMm, 100) * (displayUnit === 'in' ? 25.4 : 1.0),
        height_mm: num(controls.heightMm, 100) * (displayUnit === 'in' ? 25.4 : 1.0),
        lpi: num(controls.lpi, 24),
        lpi_helper_mode: controls.lpiMode.value,
        lpi_helper_preset: controls.lpiPreset.value,
        views,
        printer_dpi: Math.round(num(controls.printerDpi, 1440)),
        build_detail_mode: controls.buildDetail.value,
        pixels_per_lenticule: Math.max(2, Math.round(num(controls.pixelsPerLens, 60))),
        orientation: controls.orientation.value,
        lens_profile: controls.lensProfile.value,
        lens_profile_selection: controls.lensProfile.value,
        print_profile: controls.printProfile.value,
        manual_thickness_mm: num(controls.manualThickness, 1.0),
        manual_thickness_unit: 'mm',
        base_mode: controls.baseMode.value,
        manual_base_mm: num(controls.manualBase, 0.3),
        viewing_angle_mode: controls.viewingAngleMode.value,
        custom_viewing_angle_deg: num(controls.customAngle, 44),
        ior: num(controls.ior, 1.55),
        backing_mm: controls.backingEnabled && controls.backingEnabled.checked ? num(controls.backingMm, 5.0) : 0,
        backing_enabled: !controls.backingEnabled || !!controls.backingEnabled.checked,
        backing_saved_mm: num(controls.backingMm, 5.0),
        phase_pitch: num(controls.phase, 0),
        calibration_mode: controls.calibrationMode ? controls.calibrationMode.value : 'Thickness Test',
        calibration_coupon_size: controls.calibrationCouponSize ? controls.calibrationCouponSize.value : '20 mm'
      },
      assets: { source_frames: sourceItems.map(item => item.path).filter(Boolean) }
    };
  }

  function rebuildPriorityForControl(el) {
    if (!el) return 'settings';
    const pair = new Set([
      controls.printerDpi, controls.settingsMode, controls.outputMode, controls.widthMm, controls.heightMm,
      controls.orientation, controls.lpi, controls.views, controls.lpiMode,
      controls.lpiPreset, controls.buildDetail, controls.pixelsPerLens
    ]);
    const mapOnly = new Set([
      controls.settingsMode, controls.lensProfile, controls.printProfile,
      controls.manualThickness, controls.ior, controls.baseMode, controls.manualBase,
      controls.viewingAngleMode, controls.customAngle, controls.reliefHeight, controls.phase
    ]);
    if (pair.has(el)) return 'rebuild-pair';
    if (mapOnly.has(el)) return 'rebuild-pair';
    if (el === controls.backingMm || el === controls.backingEnabled) return 'blender-setting';
    return 'settings';
  }

  function applyFastSolvedSettings(response, sequence) {
    if (!response || response.ok === false || !response.settings) return false;
    if (sequence < appliedSolveSequence) return false;
    appliedSolveSequence = sequence;
    const s = response.settings;

    // Only settings/calculated readouts are updated here. Generated assets remain
    // attached to the last completed native build until the app-authored project
    // revision arrives, so a fast solve can never display half-built output files.
    setControlValue(controls.printerDpi, s.printer_dpi);
    setControlValue(controls.settingsMode, s.mode);
    setControlValue(controls.outputMode, s.output_mode);
    setControlValue(controls.orientation, s.orientation);
    setControlValue(controls.lpi, s.lpi);
    setControlValue(controls.views, s.views);
    setControlValue(controls.lpiMode, s.lpi_helper_mode);
    setControlValue(controls.lpiPreset, s.lpi_helper_preset);
    setControlValue(controls.buildDetail, s.build_detail_mode);
    setControlValue(controls.pixelsPerLens, s.pixels_per_lenticule);
    setControlValue(controls.lensProfile, s.lens_profile_selection || s.lens_profile);
    setControlValue(controls.printProfile, s.print_profile);
    setControlValue(controls.manualThickness, s.manual_thickness_mm);
    setControlValue(controls.ior, s.ior);
    setControlValue(controls.baseMode, s.base_mode);
    setControlValue(controls.manualBase, s.manual_base_mm);
    setControlValue(controls.viewingAngleMode, s.viewing_angle_mode);
    setControlValue(controls.customAngle, s.custom_viewing_angle_deg);
    setControlValue(controls.reliefHeight, s.relief_prism_height_mm);
    setControlValue(controls.phase, s.phase_pitch);
    if (controls.backingEnabled) controls.backingEnabled.checked = s.backing_enabled !== false && Number(s.backing_mm || 0) > 0;
    setControlValue(controls.backingMm, Number(s.backing_mm || 0) > 0 ? s.backing_mm : (s.backing_saved_mm || controls.backingMm?.value || 5));

    if ($('phaseValue')) $('phaseValue').textContent = `${Number(s.phase_pitch || 0) >= 0 ? '+' : ''}${Number(s.phase_pitch || 0).toFixed(3)} pitch`;
    if ($('metricThickness')) $('metricThickness').textContent = `${Number(s.thickness_mm || s.manual_thickness_mm || 0).toFixed(3)} mm`;
    if ($('metricBase')) $('metricBase').textContent = `${Number(s.base_mm || s.manual_base_mm || 0).toFixed(3)} mm`;
    if ($('metricRise')) $('metricRise').textContent = `${Number(s.rise_mm || Math.max(0, Number(s.thickness_mm || 0) - Number(s.base_mm || 0))).toFixed(3)} mm`;
    if ($('metricAngle')) $('metricAngle').textContent = currentWorkflow === 'Build from heightmap' ? 'Not inferred' : `${Number(s.viewing_angle_deg || s.custom_viewing_angle_deg || 0).toFixed(1)} deg`;
    if ($('summaryMode')) $('summaryMode').textContent = s.output_mode || 'Lenticular Lens';
    if ($('summaryLpiViews')) $('summaryLpiViews').textContent = `${Number(s.lpi || 0).toFixed(3).replace(/\.000$/, '')} / ${Number(s.views || 0)}`;
    if ($('summaryOrientation')) $('summaryOrientation').textContent = s.orientation || 'Vertical';

    const relief = s.output_mode === 'Lens-Free Relief';
    if ($('lensSettingsCard')) $('lensSettingsCard').classList.toggle('hidden', relief);
    if ($('reliefSettingsCard')) $('reliefSettingsCard').classList.toggle('hidden', !relief);
    updateControlStates(false);
    updateSourceActionState();
    updateViewerButtonLabels();

    // Let the already-fast WebGL preview respond to the solved optical state now,
    // rather than waiting for PNG regeneration.
    lastSolvedSettings = { ...s };
    const base = project || browserPreviewProject;
    const solvedProject = { ...base, settings: { ...(base.settings || {}), ...s } };
    project = solvedProject;
    updateViewers(solvedProject);
    return true;
  }

  function queueFastSolve(delayMs = 25) {
    clearTimeout(solveTimer);
    const sequence = ++solveSequence;
    solveTimer = setTimeout(async () => {
      try {
        const response = await api.solveSettings(settingsPatch());
        if (sequence !== solveSequence) return;
        applyFastSolvedSettings(response, sequence);
      } catch (_) {
        // Heavy project synchronization remains the correctness fallback. A fast
        // solver failure must never prevent the normal production rebuild.
      }
    }, delayMs);
  }

  function queueWrite(priority = 'settings') {
    settingsDirty = true;
    queueFastSolve(20);
    clearTimeout(writeTimer);
    const buildSequence = ++outgoingBuildSequence;
    const delay = priority === 'blender-setting' || priority === 'settings' ? 180 : 220;
    writeTimer = setTimeout(async () => {
      try {
        const written = await api.patchProject(settingsPatch(), priority);
        if (buildSequence !== outgoingBuildSequence) return;
        settingsDirty = false;
        const completed = deferredProject;
        deferredProject = null;
        if (completed && Number(completed.revision) > Number(written.revision)) {
          updateFromProject(completed);
          return;
        }
        const solved = (lastSolvedSettings && appliedSolveSequence === solveSequence) ? lastSolvedSettings : null;
        project = { ...(project || browserPreviewProject), ...written, settings: { ...(written.settings || {}), ...(solved || {}) } };
        updateViewers(project);
        updateSourceActionState();
        if (priority === 'rebuild-pair') setStatus(currentWorkflow === 'Build from heightmap' ? 'Rebuilding the interlaced image with a copy of the imported heightmap...' : 'Optics updated. Rebuilding the interlaced image and matching 16-bit heightmap...');
        else if (priority === 'rebuild-heightmap') setStatus('Imported interlaced image updated. Rebuilding the matching 16-bit heightmap...');
        else setStatus('Settings saved.');
      } catch (err) {
        if (buildSequence === outgoingBuildSequence) settingsDirty = false;
        setStatus(`Could not synchronize project: ${err.message || err}`);
      }
    }, delay);
  }


  async function publishNow(priority = 'settings', patch = null) {
    clearTimeout(writeTimer);
    clearTimeout(solveTimer);
    ++outgoingBuildSequence;
    ++solveSequence;
    settingsDirty = false;
    deferredProject = null;
    try {
      const basePatch = settingsPatch();
      const mergedPatch = patch ? mergePatchObjects(basePatch, patch) : basePatch;
      const response = await api.patchProject(mergedPatch, priority);
      if (response.command_canceled) { setStatus('Action canceled.'); return null; }
      if (!project || Number(response.revision) >= Number(project.revision)) project = response;
      updateFromProject(project);
      setStatus(`Project revision ${project.revision} saved.`);
      return project;
    } catch (err) {
      setStatus(`Could not publish project: ${err.message || err}`);
      return null;
    }
  }

  function mergePatchObjects(base, extra) {
    if (!extra || typeof extra !== 'object' || Array.isArray(extra)) return extra === undefined ? base : extra;
    const result = { ...(base || {}) };
    for (const [key, value] of Object.entries(extra)) {
      if (value && typeof value === 'object' && !Array.isArray(value)) {
        result[key] = mergePatchObjects(result[key] || {}, value);
      } else {
        result[key] = value;
      }
    }
    return result;
  }

  function setControlValue(el, value) {
    if (!el || value === undefined || value === null) return;
    // Native-core responses can arrive while a number is still being typed. Never
    // rewrite the active field mid-keystroke; doing so was the cause of malformed
    // values such as an IOR of "561" while entering 1.56.
    if (document.activeElement === el && el.dataset.userEditing === '1') return;
    const target = String(value);
    if (el.tagName === 'SELECT') {
      const lower = target.toLowerCase();
      let match = Array.from(el.options).find(o => o.value.toLowerCase() === lower || o.text.toLowerCase() === lower);
      if (!match) {
        // Native v2 may return descriptive labels such as
        // "Recommended (...) - 0.76 mm". Match the canonical option prefix.
        match = Array.from(el.options).find(o => lower.startsWith(o.value.toLowerCase()) || lower.startsWith(o.text.toLowerCase()) || o.value.toLowerCase().startsWith(lower));
      }
      if (match) el.value = match.value;
    } else {
      el.value = target;
    }
  }

  function updateFromProject(next) {
    if (!next) return;
    project = next;
    const s = next.settings || {};
    const a = next.assets || {};
    if (String(next.changed_by || '').toLowerCase() !== 'electron') lastSolvedSettings = { ...s };
    const incomingFrames = Array.isArray(a.source_frames) ? a.source_frames.filter(Boolean) : [];
    const currentFramePaths = sourceItems.map(item => item.path);
    if (incomingFrames.length !== currentFramePaths.length || incomingFrames.some((value, index) => value !== currentFramePaths[index])) {
      sourceItems = incomingFrames.slice(0, 8).map(p => ({ path: p, name: p.split(/[\\/]/).pop(), url: fileUrl(p) }));
      renderSources();
    }
    setWorkflow(s.workflow || 'Build from source frames');
    setControlValue(controls.printerDpi, s.printer_dpi);
    setControlValue(controls.settingsMode, s.mode);
    setControlValue(controls.outputMode, s.output_mode);
    const displayScale = displayUnit === 'in' ? 25.4 : 1.0;
    setControlValue(controls.widthMm, Number(s.width_mm || 0) / displayScale);
    setControlValue(controls.heightMm, Number(s.height_mm || 0) / displayScale);
    setControlValue(controls.orientation, s.orientation);
    setControlValue(controls.lpi, s.lpi);
    setControlValue(controls.views, s.views);
    setControlValue(controls.lpiMode, s.lpi_helper_mode);
    setControlValue(controls.lpiPreset, s.lpi_helper_preset);
    setControlValue(controls.buildDetail, s.build_detail_mode);
    setControlValue(controls.pixelsPerLens, s.pixels_per_lenticule);
    setControlValue(controls.lensProfile, s.lens_profile_selection || s.lens_profile);
    setControlValue(controls.printProfile, s.print_profile);
    setControlValue(controls.manualThickness, s.manual_thickness_mm);
    setControlValue(controls.ior, s.ior);
    setControlValue(controls.baseMode, s.base_mode);
    setControlValue(controls.manualBase, s.manual_base_mm);
    setControlValue(controls.viewingAngleMode, s.viewing_angle_mode);
    setControlValue(controls.customAngle, s.custom_viewing_angle_deg);
    setControlValue(controls.reliefHeight, s.relief_prism_height_mm);
    setControlValue(controls.phase, s.phase_pitch);
    if (controls.backingEnabled) controls.backingEnabled.checked = s.backing_enabled !== false && Number(s.backing_mm || 0) > 0;
    setControlValue(controls.backingMm, Number(s.backing_mm || 0) > 0 ? s.backing_mm : (s.backing_saved_mm || controls.backingMm?.value || 5));
    setControlValue(controls.calibrationMode, s.calibration_mode);
    setControlValue(controls.calibrationCouponSize, s.calibration_coupon_size);
    if ($('analysisResult')) $('analysisResult').textContent = next.analysis_text || 'Run Analyze / Verify LPI to inspect the current generated or imported interlaced image.';

    $('phaseValue').textContent = `${Number(s.phase_pitch || 0) >= 0 ? '+' : ''}${Number(s.phase_pitch || 0).toFixed(3)} pitch`;
    $('metricThickness').textContent = `${Number(s.thickness_mm || s.manual_thickness_mm || 0).toFixed(3)} mm`;
    $('metricBase').textContent = `${Number(s.base_mm || s.manual_base_mm || 0).toFixed(3)} mm`;
    $('metricRise').textContent = `${Number(s.rise_mm || Math.max(0, Number(s.thickness_mm || 0) - Number(s.base_mm || 0))).toFixed(3)} mm`;
    $('metricAngle').textContent = currentWorkflow === 'Build from heightmap' ? 'Not inferred' : `${Number(s.viewing_angle_deg || s.custom_viewing_angle_deg || 0).toFixed(1)} deg`;
    $('summaryMode').textContent = s.output_mode || 'Lenticular Lens';
    $('summarySize').textContent = `${(Number(s.width_mm || 0) / displayScale).toFixed(displayUnit === 'in' ? 3 : 1)} × ${(Number(s.height_mm || 0) / displayScale).toFixed(displayUnit === 'in' ? 3 : 1)} ${displayUnit}`;
    $('summaryLpiViews').textContent = `${Number(s.lpi || 0).toFixed(3).replace(/\.000$/, '')} / ${Number(s.views || 0)}`;
    $('summaryOrientation').textContent = s.orientation || 'Vertical';
    $('projectPathLabel').textContent = bootstrap ? bootstrap.projectPath : '';

    const relief = s.output_mode === 'Lens-Free Relief';
    $('lensSettingsCard').classList.toggle('hidden', relief);
    $('reliefSettingsCard').classList.toggle('hidden', !relief);
    $('viewOrderHint').textContent = s.orientation === 'Horizontal' ? 'Horizontal lens direction: top to bottom source order.' : 'Vertical lens direction: left to right source order.';

    $('heightmapOutputTitle').textContent = `${currentWorkflow === 'Build from heightmap' ? (next.reference_heightmap_info?.bit_depth || '') : 16}-bit heightmap / depth map`;
    const interlaced = a.interlaced_image || '';
    const heightmap = a.heightmap || '';
    $('resultInterlacedPath').textContent = interlaced || 'Not generated';
    $('resultHeightmapPath').textContent = heightmap || 'Not generated';
    $('interlacedName').textContent = interlaced ? interlaced.split(/[\\/]/).pop() : 'No interlaced image loaded';

    resultPreviewPath = interlaced || '';
    heightmapPreviewPath = heightmap || '';
    if (selectedSourcePreviewPath && !sourceItems.some(item => item.path === selectedSourcePreviewPath) && selectedSourcePreviewPath !== interlaced) {
      selectedSourcePreviewPath = '';
    }
    if (!selectedSourcePreviewPath) {
      selectedSourcePreviewPath = (sourceItems[0] && sourceItems[0].path) || interlaced || '';
    }
    showSidePreviewPath(selectedSourcePreviewPath || interlaced || '');
    showResultPreviewPath(resultPreviewPath || '');
    showHeightmapPreviewPath(heightmapPreviewPath || '');
    updateControlStates(false);
    updateSourceActionState();
    if(s.reference_heightmap_show && a.reference_heightmap) $('previewTitle').textContent='Reference heightmap';
    updateReferenceControls(next);
    updateViewerButtonLabels();
    updateViewers(next);
  }

  function fileUrl(p, token = '') {
    if (!p) return '';
    if (api.assetUrl) return api.assetUrl(p, token);
    let normalized = p.replace(/\\/g, '/');
    if (/^[A-Za-z]:\//.test(normalized)) normalized = '/' + normalized;
    const base = 'file://' + encodeURI(normalized);
    return token === '' || token === null || token === undefined ? base : `${base}?v=${encodeURIComponent(String(token))}`;
  }

  function assetRevisionToken() {
    return (project && project.revision) || 0;
  }

  function showSidePreviewPath(p) {
    selectedSourcePreviewPath = p || '';
    const isGenerated = !!(project && project.assets && project.assets.interlaced_image && selectedSourcePreviewPath === project.assets.interlaced_image);
    const url = fileUrl(selectedSourcePreviewPath, isGenerated ? assetRevisionToken() : '');
    const side = $('sidePreviewImage');
    if (!url) {
      side.style.display = 'none'; $('sidePreviewEmpty').style.display = 'grid';
      if ($('previewTitle')) $('previewTitle').textContent = 'Project overview';
      return;
    }
    side.src = url;
    side.style.display = 'block';
    $('sidePreviewEmpty').style.display = 'none';
    if ($('previewTitle')) $('previewTitle').textContent = selectedSourcePreviewPath.split(/[\\/]/).pop() || 'Image preview';
  }

  function applyNaturalAspect(img, frame) {
    if (!img || !frame) return;
    const update = () => {
      if (img.naturalWidth > 0 && img.naturalHeight > 0) {
        frame.style.setProperty('--asset-aspect', `${img.naturalWidth} / ${img.naturalHeight}`);
      }
    };
    img.addEventListener('load', update, { once: true });
    if (img.complete) requestAnimationFrame(update);
  }

  function showResultPreviewPath(p) {
    resultPreviewPath = p || '';
    const url = fileUrl(resultPreviewPath, assetRevisionToken());
    const result = $('resultImage');
    const output = $('outputInterlacedImage');
    const empty = $('outputInterlacedEmpty');
    if (!url) {
      if (result) result.style.display = 'none';
      if ($('resultPlaceholder')) $('resultPlaceholder').style.display = 'block';
      if (output) output.style.display = 'none';
      if (empty) empty.style.display = 'grid';
      return;
    }
    if (result) { result.src = url; result.style.display = 'block'; applyNaturalAspect(result, result.closest('.result-preview')); }
    if ($('resultPlaceholder')) $('resultPlaceholder').style.display = 'none';
    if (output) { output.src = url; output.style.display = 'block'; applyNaturalAspect(output, output.closest('.output-image-stage')); }
    if (empty) empty.style.display = 'none';
  }

  function showHeightmapPreviewPath(p) {
    heightmapPreviewPath = p || '';
    const url = fileUrl(heightmapPreviewPath, assetRevisionToken());
    const result = $('heightmapResultImage');
    const output = $('outputHeightmapImage');
    const empty = $('outputHeightmapEmpty');
    if (!url) {
      if (result) result.style.display = 'none';
      if ($('heightmapResultPlaceholder')) $('heightmapResultPlaceholder').style.display = 'block';
      if (output) output.style.display = 'none';
      if (empty) empty.style.display = 'grid';
      return;
    }
    if (result) { result.src = url; result.style.display = 'block'; applyNaturalAspect(result, result.closest('.result-preview')); }
    if ($('heightmapResultPlaceholder')) $('heightmapResultPlaceholder').style.display = 'none';
    if (output) { output.src = url; output.style.display = 'block'; applyNaturalAspect(output, output.closest('.output-image-stage')); }
    if (empty) empty.style.display = 'none';
  }

  function sourcePositionLabel(index, count) {
    const horizontal = controls.orientation.value === 'Horizontal';
    if (count === 2) return horizontal ? ['Top', 'Bottom'][index] : ['Left', 'Right'][index];
    if (count === 3) return horizontal ? ['Top', 'Center', 'Bottom'][index] : ['Left', 'Center', 'Right'][index];
    if (count === 4) return horizontal ? ['Far Top','Center Top','Center Bottom','Far Bottom'][index] : ['Far Left','Center Left','Center Right','Far Right'][index];
    if (count === 5) return horizontal ? ['Far Top','Top','Center','Bottom','Far Bottom'][index] : ['Far Left','Left','Center','Right','Far Right'][index];
    if (count === 6) return horizontal ? ['Far Top','Top','Center Top','Center Bottom','Bottom','Far Bottom'][index] : `View ${index + 1}`;
    if (count === 7) return horizontal ? ['Far Top','Top','Center Top','Center','Center Bottom','Bottom','Far Bottom'][index] : `View ${index + 1}`;
    if (count === 8) return horizontal ? ['Far Top','Top','Center Top','Slight Top','Slight Bottom','Center Bottom','Bottom','Far Bottom'][index] : `View ${index + 1}`;
    return `View ${index + 1}`;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
  }

  function renderSources() {
    const grid = $('sourceGrid');
    grid.innerHTML = '';
    grid.classList.toggle('empty', sourceItems.length === 0);
    if (!sourceItems.length) {
      grid.innerHTML = '<div class="empty-state"><strong>Drop source images here</strong><span>Drop source images or a lens heightmap. Heightmaps are detected automatically.</span></div>';
      updateSourceActionState();
      updateViewers(project);
      return;
    }

    sourceItems.forEach((item, index) => {
      const card = document.createElement('div');
      card.className = 'source-card';
      card.draggable = true;
      card.dataset.index = String(index);
      card.innerHTML = `<img class="source-thumb" draggable="false" src="${item.url || fileUrl(item.path)}" alt=""><div class="source-card-meta"><strong>${escapeHtml(item.name || (item.path || '').split(/[\\/]/).pop())}</strong><span>${sourcePositionLabel(index, sourceItems.length)}</span></div><div class="source-card-actions"><button data-action="up" data-index="${index}">Up</button><button data-action="down" data-index="${index}">Down</button><button data-action="remove" data-index="${index}">Remove</button></div>`;
      card.querySelector('.source-thumb').addEventListener('click', () => showSidePreviewPath(item.path));

      card.addEventListener('dragstart', (event) => {
        draggedSourceIndex = index;
        card.classList.add('drag-source');
        document.body.classList.add('source-dragging');
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('application/x-lenticulizer-source-index', String(index));
        event.dataTransfer.setData('text/plain', String(index));
      });
      card.addEventListener('dragend', () => {
        draggedSourceIndex = -1;
        card.classList.remove('drag-source');
        document.body.classList.remove('source-dragging');
        document.querySelectorAll('.source-card.drag-over').forEach(el => el.classList.remove('drag-over'));
      });
      card.addEventListener('dragover', (event) => {
        if (event.dataTransfer.types && Array.from(event.dataTransfer.types).includes('Files')) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        card.classList.add('drag-over');
      });
      card.addEventListener('dragleave', () => card.classList.remove('drag-over'));
      card.addEventListener('drop', (event) => {
        if (event.dataTransfer.files && event.dataTransfer.files.length) return;
        event.preventDefault();
        event.stopPropagation();
        card.classList.remove('drag-over');
        const from = draggedSourceIndex >= 0 ? draggedSourceIndex : Number(event.dataTransfer.getData('application/x-lenticulizer-source-index'));
        const to = index;
        if (!Number.isFinite(from) || from < 0 || from >= sourceItems.length || from === to) return;
        const [moved] = sourceItems.splice(from, 1);
        sourceItems.splice(to, 0, moved);
        renderSources();
        queueWrite('rebuild-pair');
      });
      grid.appendChild(card);
    });

    grid.querySelectorAll('button[data-action]').forEach(btn => btn.addEventListener('click', (event) => {
      event.stopPropagation();
      const index = Number(btn.dataset.index); const action = btn.dataset.action;
      if (action === 'remove') { sourceItems.splice(index, 1); syncViewsToSourceCount(); }
      if (action === 'up' && index > 0) [sourceItems[index - 1], sourceItems[index]] = [sourceItems[index], sourceItems[index - 1]];
      if (action === 'down' && index < sourceItems.length - 1) [sourceItems[index + 1], sourceItems[index]] = [sourceItems[index], sourceItems[index + 1]];
      if (sourceItems.length && currentWorkflow !== 'Build from heightmap') setWorkflow('Build from source frames');
      renderSources(); updateControlStates(true); queueWrite('rebuild-pair');
    }));
    updateSourceActionState();
    updateViewers(project);
  }

  function imageExtensionOk(name) { return /\.(png|jpe?g|bmp|tiff?)$/i.test(name || ''); }

  let fileDropQueue = Promise.resolve();
  function addDroppedFiles(files, target = 'auto') {
    // Keep separate drop gestures in order, including their pending settings.
    const dropped = Array.from(files || []).filter(file => imageExtensionOk(file.name));
    fileDropQueue = fileDropQueue.then(async () => {
      if (!dropped.length) { setStatus('Drop PNG, JPG, BMP or TIFF image files.'); return; }
      if (!api.importDroppedFiles) { setStatus('File dropping is available in the desktop app.'); return; }
      if (!await publishNow('settings')) return;
      setStatus('Inspecting dropped images for lens heightmaps...');
      const result = await api.importDroppedFiles(dropped, target);
      if (!result || !result.project) return;
      updateFromProject(result.project);
      if (result.heightmapImported) {
        activatePage('sources'); $('preview3dTab').click();
        $('referenceHeightmapCard').scrollIntoView({ block: 'nearest' });
      } else if (result.sourcesAdded > 0) activatePage('sources');
      setStatus(result.message || 'Images imported.');
    }).catch(error => { setStatus(error.message || String(error)); });
    return fileDropQueue;
  }

  function setupSourceDropZone() {
    const isFileDrag = event => event.dataTransfer && Array.from(event.dataTransfer.types || []).includes('Files');
    const bindDropZone = (zone, target = 'auto') => {
      if (!zone) return;
      ['dragenter','dragover'].forEach(type => zone.addEventListener(type, event => {
        if (!isFileDrag(event)) return;
        event.preventDefault(); event.stopPropagation();
        event.dataTransfer.dropEffect = 'copy'; zone.classList.add('drop-active');
      }));
      zone.addEventListener('dragleave', event => {
        if (!zone.contains(event.relatedTarget)) zone.classList.remove('drop-active');
      });
      zone.addEventListener('drop', event => {
        if (!event.dataTransfer?.files?.length) return;
        event.preventDefault(); event.stopPropagation(); zone.classList.remove('drop-active');
        addDroppedFiles(event.dataTransfer.files, target);
      });
    };
    bindDropZone($('sourceGrid'));
    bindDropZone($('projectDropZone'));
    bindDropZone($('referenceHeightmapCard'), 'heightmap');
    window.addEventListener('dragover', event => {
      if (!isFileDrag(event)) return;
      event.preventDefault(); event.dataTransfer.dropEffect = 'copy';
    });
    window.addEventListener('drop', event => {
      if (!isFileDrag(event)) return;
      event.preventDefault();
      if (event.dataTransfer.files?.length) addDroppedFiles(event.dataTransfer.files);
    });
  }

  function setupSplitters() {
    const root = document.documentElement;
    const sidebarStored = Number(localStorage.getItem('lenticulizer.sidebarWidth'));
    const previewStored = Number(localStorage.getItem('lenticulizer.previewWidth'));
    if (Number.isFinite(sidebarStored)) root.style.setProperty('--sidebar-width', `${clamp(sidebarStored, 124, 320)}px`);
    if (Number.isFinite(previewStored)) root.style.setProperty('--preview-width', `${clamp(previewStored, 250, 720)}px`);

    const compactButton = $('compactNavButton');
    const previewButton = $('togglePreviewButton');
    const thumbSelect = $('sourceThumbSize');
    const sourceGrid = $('sourceGrid');

    function applyCompactNav(compact, persist = true) {
      document.body.classList.toggle('nav-compact', !!compact);
      if (compactButton) {
        compactButton.setAttribute('aria-pressed', compact ? 'true' : 'false');
        compactButton.textContent = compact ? 'Full nav' : 'Compact nav';
        compactButton.title = compact ? 'Restore full navigation' : 'Compact navigation';
      }
      if (persist) localStorage.setItem('lenticulizer.navCompact', compact ? '1' : '0');
      requestViewerResize();
    }
    function applyPreviewHidden(hidden, persist = true) {
      document.body.classList.toggle('preview-hidden', !!hidden);
      if (previewButton) {
        previewButton.setAttribute('aria-pressed', hidden ? 'true' : 'false');
        previewButton.textContent = hidden ? 'Show preview' : 'Hide preview';
        previewButton.title = hidden ? 'Restore the preview pane' : 'Hide the preview pane';
      }
      if (persist) localStorage.setItem('lenticulizer.previewHidden', hidden ? '1' : '0');
      requestViewerResize();
      if (!hidden) requestAnimationFrame(() => renderAllViewers(false));
    }
    function applyThumbSize(value, persist = true) {
      const size = ['small','medium','large'].includes(value) ? value : 'medium';
      if (thumbSelect) thumbSelect.value = size;
      if (sourceGrid) {
        sourceGrid.classList.remove('thumb-small','thumb-medium','thumb-large');
        sourceGrid.classList.add(`thumb-${size}`);
      }
      if (persist) localStorage.setItem('lenticulizer.sourceThumbSize', size);
    }

    applyCompactNav(localStorage.getItem('lenticulizer.navCompact') === '1', false);
    applyPreviewHidden(localStorage.getItem('lenticulizer.previewHidden') === '1', false);
    applyThumbSize(localStorage.getItem('lenticulizer.sourceThumbSize') || 'medium', false);
    if (compactButton) compactButton.addEventListener('click', () => applyCompactNav(!document.body.classList.contains('nav-compact')));
    if (previewButton) previewButton.addEventListener('click', () => applyPreviewHidden(!document.body.classList.contains('preview-hidden')));
    if (thumbSelect) thumbSelect.addEventListener('change', () => applyThumbSize(thumbSelect.value));

    function dragGlobal(splitter, kind) {
      if (!splitter) return;
      splitter.addEventListener('pointerdown', event => {
        event.preventDefault();
        splitter.setPointerCapture(event.pointerId);
        splitter.classList.add('dragging');
        document.body.classList.add('resizing');
        const workspace = document.querySelector('.workspace');
        const rect = workspace.getBoundingClientRect();
        const move = e => {
          if (kind === 'sidebar') {
            const width = clamp(e.clientX - rect.left, 124, Math.min(320, rect.width - 600));
            root.style.setProperty('--sidebar-width', `${width}px`);
            localStorage.setItem('lenticulizer.sidebarWidth', String(width));
          } else {
            const width = clamp(rect.right - e.clientX, 250, Math.min(720, rect.width - 640));
            root.style.setProperty('--preview-width', `${width}px`);
            localStorage.setItem('lenticulizer.previewWidth', String(width));
          }
          requestViewerResize();
        };
        const end = () => {
          splitter.classList.remove('dragging');
          document.body.classList.remove('resizing');
          splitter.removeEventListener('pointermove', move);
          splitter.removeEventListener('pointerup', end);
          splitter.removeEventListener('pointercancel', end);
        };
        splitter.addEventListener('pointermove', move);
        splitter.addEventListener('pointerup', end);
        splitter.addEventListener('pointercancel', end);
      });
    }
    dragGlobal($('sidebarSplitter'), 'sidebar');
    dragGlobal($('previewSplitter'), 'preview');

    document.querySelectorAll('.local-splitter[data-splitter-for]').forEach(splitter => {
      const id = splitter.dataset.splitterFor;
      const host = $(id);
      if (!host) return;
      const saved = Number(localStorage.getItem(`lenticulizer.split.${id}`));
      if (Number.isFinite(saved)) host.style.setProperty('--split-left', `${clamp(saved, 25, 75)}%`);
      splitter.addEventListener('pointerdown', event => {
        event.preventDefault();
        splitter.setPointerCapture(event.pointerId);
        splitter.classList.add('dragging');
        document.body.classList.add('resizing');
        const rect = host.getBoundingClientRect();
        const move = e => {
          const pct = clamp((e.clientX - rect.left) / rect.width * 100, 25, 75);
          host.style.setProperty('--split-left', `${pct}%`);
          localStorage.setItem(`lenticulizer.split.${id}`, String(pct));
          requestViewerResize();
        };
        const end = () => {
          splitter.classList.remove('dragging');
          document.body.classList.remove('resizing');
          splitter.removeEventListener('pointermove', move);
          splitter.removeEventListener('pointerup', end);
          splitter.removeEventListener('pointercancel', end);
        };
        splitter.addEventListener('pointermove', move);
        splitter.addEventListener('pointerup', end);
        splitter.addEventListener('pointercancel', end);
      });
    });
  }

  /* ---------- Interactive WebGL viewer ---------- */

  const sharedView = { yaw: 0, pitch: 0, zoom: 1.0, panX: 0, panY: 0, mode: 'Optical Refraction Preview' };
  const liveViewers = [];

  function referenceProfileZ(u) {
    const samples = [0.0000,0.1700,0.4200,0.5400,0.6300,0.7000,0.7500,0.8000,0.8400,0.8800,0.9100,0.9300,0.9500,0.9650,0.9800,0.9900,1.0000];
    if (u <= 0) return samples[0];
    if (u >= 1) return samples[samples.length - 1];
    const fp = u * (samples.length - 1), i = Math.floor(fp), t = fp - i;
    return samples[i] + (samples[i + 1] - samples[i]) * t;
  }

  function conicSag(x, radius, k) {
    if (radius <= 0) return 0;
    const term = Math.max(0, 1 - (1 + k) * x * x / (radius * radius));
    const denom = radius * (1 + Math.sqrt(term));
    return Math.abs(denom) < 1e-7 ? 0 : x * x / denom;
  }

  function circularProfileZ(x, radius, hshape) {
    const inside = Math.max(0, radius * radius - x * x);
    const z = (Math.sqrt(inside) - (radius - hshape)) / Math.max(1e-9, hshape);
    return clamp(z, 0, 1);
  }

  function reliefBoundaries(views) {
    views = Math.max(2, Math.round(views));
    const center = (views - 1) * 0.5;
    const h = new Array(views + 1).fill(0);
    for (let i = 0; i < views; i++) h[i + 1] = h[i] + (center - i);
    const drift = h[views] - h[0];
    if (Math.abs(drift) > 1e-12) for (let i = 0; i <= views; i++) h[i] -= drift * i / views;
    const lo = Math.min(...h), hi = Math.max(...h), span = hi - lo;
    return span <= 1e-12 ? h : h.map(v => (v - lo) / span);
  }

  function reliefProfile(phase, views) {
    phase = wrap01(phase);
    views = Math.max(2, Math.round(views));
    const b = reliefBoundaries(views);
    const fp = phase * views;
    const facet = Math.min(views - 1, Math.floor(fp));
    const local = fp - facet;
    return b[facet] + (b[facet + 1] - b[facet]) * local;
  }

  function reliefFacetAngles(settings) {
    const views = Math.max(2, Math.round(Number(settings.views || sourceItems.length || 2)));
    const lpi = Math.max(.001, Number(settings.lpi || 24));
    const prism = Math.max(0, Number(settings.relief_prism_height_mm || .8));
    const pitch = 25.4 / lpi, facetWidth = pitch / views, b = reliefBoundaries(views);
    return new Array(views).fill(0).map((_, i) => -Math.atan(((b[i + 1] - b[i]) * prism) / Math.max(1e-12, facetWidth)) * 180 / Math.PI);
  }

  function resolvedProfile(settings) {
    if (settings.output_mode === 'Lens-Free Relief') return 'Lens-Free Relief';
    const p = String(settings.lens_profile || 'Auto Recommended');
    if (/Mathematically Optimal/i.test(p)) return 'Mathematically Optimal Aspheric';
    if (p === 'Reference Calibrated') return p;
    if (p === 'Aspheric' || p === 'Rounded / Circular' || p === 'Multi-facet / Prismatic' || p === 'Cosine') return p;
    if (/Linear/i.test(p)) return 'Linear / Triangular (experimental)';
    return 'Reference Calibrated';
  }

  function theoreticalProfileZ(xPx, pitchPx, ratio, baseFraction, ior) {
    if (pitchPx <= 0) return 0;
    const n = Math.max(1.000001, ior || 1.55);
    const oneMinusBase = 1 - clamp(baseFraction, 0, .999999);
    if (oneMinusBase <= 1e-7) return 0;
    let peakOverPitch = ratio / oneMinusBase;
    const minimum = .5 * Math.sqrt((n + 1) / (n - 1));
    if (peakOverPitch < minimum) peakOverPitch = minimum;
    const x = xPx / pitchPx, a = .5, c = (n - 1) * peakOverPitch, n2m1 = n*n - 1;
    const disc = Math.max(0, c*c - n2m1*x*x);
    const z = (c + n*Math.sqrt(disc)) / n2m1;
    const edgeDisc = Math.max(0, c*c - n2m1*a*a);
    const edge = (c + n*Math.sqrt(edgeDisc)) / n2m1;
    const denom = peakOverPitch - edge;
    return denom <= 1e-7 ? 0 : clamp((z - edge) / denom, 0, 1);
  }

  function profileValue(settings, phase, pitchSamples, ratio, baseFraction) {
    const profile = resolvedProfile(settings);
    if (profile === 'Lens-Free Relief') return reliefProfile(phase, settings.views || sourceItems.length || 2);
    const a = pitchSamples / 2;
    const hshape = Math.max(pitchSamples * ratio, pitchSamples * .001);
    const R = (a*a + hshape*hshape) / (2*hshape);
    const x = (wrap01(phase) - .5) * pitchSamples;
    if (profile === 'Reference Calibrated') {
      const u = 1 - Math.min(1, Math.abs(x) / a);
      return referenceProfileZ(u);
    }
    if (profile === 'Mathematically Optimal Aspheric') return theoreticalProfileZ(x, pitchSamples, ratio, baseFraction, Number(settings.ior || 1.55));
    if (profile === 'Cosine') return .5 * (1 + Math.cos(Math.PI * clamp(x / a, -1, 1)));
    if (profile === 'Linear / Triangular (experimental)') return 1 - Math.min(1, Math.abs(x) / a);
    if (profile === 'Aspheric') {
      const n = Math.max(1.000001, Number(settings.ior || 1.55)), k = -1/(n*n);
      const edgeSag = conicSag(a, R, k), xSag = conicSag(Math.abs(x), R, k);
      return edgeSag <= 1e-7 ? circularProfileZ(x, R, hshape) : 1 - clamp(xSag/edgeSag, 0, 1);
    }
    if (profile === 'Multi-facet / Prismatic') {
      const u = Math.min(1, Math.abs(x)/a), facets = Math.max(4, Math.round(Number(settings.views || 2))*2);
      const fp = u*facets, fi = Math.min(facets-1, Math.floor(fp)), local = fp-fi;
      const x0 = fi/facets*a, x1 = (fi+1)/facets*a;
      return circularProfileZ(x0,R,hshape) + (circularProfileZ(x1,R,hshape)-circularProfileZ(x0,R,hshape))*local;
    }
    return circularProfileZ(x, R, hshape);
  }

  function physicalViewBlend(phase, views) {
    const mapped = wrap01(phase), fp = mapped * views - .5, base = Math.floor(fp), blend = fp - Math.floor(fp);
    return { a: ((base % views) + views) % views, b: (((base + 1) % views) + views) % views, blend };
  }

  function viewerSelection(settings, state) {
    const paths = sourceItems.map(x => x.path).filter(Boolean);
    const fallback = (project && project.assets && project.assets.interlaced_image) || resultPreviewPath || selectedSourcePreviewPath || '';
    if (!paths.length) return { pathA: fallback, pathB: fallback, blend: 0, label: fallback ? 'Interlaced image' : 'No image' };
    if (paths.length === 1) return { pathA: paths[0], pathB: paths[0], blend: 0, label: 'Frame 1' };

    const vertical = String(settings.orientation || 'Vertical') !== 'Horizontal';
    const viewAngle = vertical ? state.yaw : state.pitch;
    const lpi = Math.max(.001, Number(settings.lpi || 24));
    const peak = settings.output_mode === 'Lens-Free Relief'
      ? Math.max(.001, Number(settings.relief_prism_height_mm || .8))
      : Math.max(.001, Number(settings.thickness_mm || settings.manual_thickness_mm || 1));
    const phaseOffset = Number(settings.phase_pitch || 0);
    const ior = Math.max(1.000001, Number(settings.ior || 1.55));

    if (settings.output_mode === 'Lens-Free Relief') {
      const angles = reliefFacetAngles(settings);
      if (paths.length === 2 && angles.length >= 2) {
        const denom = angles[1] - angles[0];
        const t = Math.abs(denom) < 1e-8 ? .5 : (-viewAngle - angles[0]) / denom;
        return { pathA: paths[0], pathB: paths[1], blend: clamp(t,0,1), label: `Frames 1-2 · blend ${clamp(t,0,1).toFixed(2)}` };
      }
      const spread = Math.max(1, Math.max(...angles) - Math.min(...angles));
      const fp = clamp(wrap01(.5 - viewAngle/spread) * paths.length - .5, 0, paths.length - 1);
      const a = Math.floor(fp), b = Math.min(paths.length-1,a+1), blend = fp-a;
      return { pathA: paths[a], pathB: paths[b], blend, label: `Frames ${a+1}-${b+1} · blend ${blend.toFixed(2)}` };
    }

    let pick;
    if (state.mode === 'Optical Refraction Preview') {
      const external = degToRad(viewAngle);
      const inside = Math.asin(clamp(Math.sin(external)/ior, -.999999, .999999));
      const pitchMm = 25.4/lpi, sampleShift = Math.tan(inside)*peak;
      const phase = wrap01(.5 + phaseOffset - sampleShift/Math.max(1e-8,pitchMm));
      pick = physicalViewBlend(phase, paths.length);
    } else {
      const spread = clamp(Number(settings.viewing_angle_deg || settings.custom_viewing_angle_deg || 60), 1, 175);
      const phase = wrap01(.5 + phaseOffset + viewAngle/spread);
      pick = physicalViewBlend(phase, paths.length);
    }
    return { pathA: paths[pick.a], pathB: paths[pick.b], blend: pick.blend, label: `Frames ${pick.a+1}-${pick.b+1} · blend ${pick.blend.toFixed(2)}` };
  }

  class Live3DViewer {
    constructor(canvas, emptyElement, infoElement = null) {
      this.canvas = canvas;
      this.empty = emptyElement;
      this.info = infoElement;
      this.gl = canvas ? (canvas.getContext('webgl', { antialias: true, alpha: false, preserveDrawingBuffer: false }) || canvas.getContext('experimental-webgl')) : null;
      this.project = null;
      this.vertices = [];
      this.uv = null;
      this.normals = null;
      this.indices = null;
      this.textureCache = new Map();
      this.textureKey = '';
      this.texA = null;
      this.texB = null;
      this.blend = 0;
      this.selectionLabel = '';
      this.textureToken = 0;
      this.dragMode = '';
      this.lastPointer = null;
      this.program = null;
      if (this.gl) this.initGl();
      this.bindInteraction();
      this.observer = new ResizeObserver(() => this.render());
      if (canvas) this.observer.observe(canvas);
    }

    initGl() {
      const gl = this.gl;
      const vsSource = `
        attribute vec4 aClip;
        attribute vec2 aUv;
        attribute float aShade;
        varying vec2 vUv;
        varying float vShade;
        void main(){ gl_Position=aClip; vUv=aUv; vShade=aShade; }
      `;
      const fsSource = `
        precision mediump float;
        uniform sampler2D uTexA;
        uniform sampler2D uTexB;
        uniform float uBlend;
        uniform float uReferenceStyle;
        varying vec2 vUv;
        varying float vShade;
        void main(){
          vec4 a=texture2D(uTexA,vUv);
          vec4 b=texture2D(uTexB,vUv);
          vec4 c=mix(a,b,clamp(uBlend,0.0,1.0));
          float light=0.88+0.12*clamp(vShade,0.0,1.0);
          if(uReferenceStyle>0.5){
            float shade=clamp(vShade,0.0,1.0);
            vec3 blue=vec3(0.38,0.68,0.91)*(0.22+0.78*shade);
            if(uReferenceStyle>2.5) blue=mix(vec3(0.11,0.14,0.17),vec3(0.80,0.91,1.0),pow(1.0-shade,2.0)*0.80+0.14);
            else if(uReferenceStyle>1.5) blue=mix(vec3(0.10,0.12,0.15),blue,0.62);
            gl_FragColor=vec4(blue,1.0);
          }else gl_FragColor=vec4(c.rgb*light,1.0);
        }
      `;
      const compile = (type, source) => {
        const sh = gl.createShader(type); gl.shaderSource(sh,source); gl.compileShader(sh);
        if (!gl.getShaderParameter(sh,gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
        return sh;
      };
      try {
        const p = gl.createProgram();
        gl.attachShader(p,compile(gl.VERTEX_SHADER,vsSource)); gl.attachShader(p,compile(gl.FRAGMENT_SHADER,fsSource)); gl.linkProgram(p);
        if (!gl.getProgramParameter(p,gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p));
        this.program = p;
        this.aClip = gl.getAttribLocation(p,'aClip'); this.aUv = gl.getAttribLocation(p,'aUv'); this.aShade = gl.getAttribLocation(p,'aShade');
        this.uTexA = gl.getUniformLocation(p,'uTexA'); this.uTexB = gl.getUniformLocation(p,'uTexB'); this.uBlend = gl.getUniformLocation(p,'uBlend');
        this.uReferenceStyle=gl.getUniformLocation(p,'uReferenceStyle');
        this.clipBuffer = gl.createBuffer(); this.uvBuffer = gl.createBuffer(); this.shadeBuffer = gl.createBuffer(); this.indexBuffer = gl.createBuffer();
        this.neutralTexture = this.makeSolidTexture(180,180,180);
        gl.enable(gl.DEPTH_TEST); gl.depthFunc(gl.LEQUAL); gl.disable(gl.CULL_FACE);
      } catch (err) {
        this.gl = null;
        if (this.empty) { this.empty.style.display='grid'; this.empty.querySelector('strong').textContent='WebGL preview unavailable'; this.empty.querySelector('span').textContent=err.message || String(err); }
      }
    }

    makeSolidTexture(r,g,b) {
      const gl=this.gl, tex=gl.createTexture(); gl.bindTexture(gl.TEXTURE_2D,tex);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([r,g,b,255]));
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR); gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      return tex;
    }

    bindInteraction() {
      if (!this.canvas) return;
      this.canvas.addEventListener('contextmenu', e => e.preventDefault());
      this.canvas.addEventListener('pointerdown', e => {
        if (e.button === 0) this.dragMode='orbit';
        else if (e.button === 1 || e.button === 2) this.dragMode='pan';
        else return;
        e.preventDefault();
        this.lastPointer={x:e.clientX,y:e.clientY};
        this.canvas.setPointerCapture(e.pointerId);
      });
      this.canvas.addEventListener('pointermove', e => {
        if (!this.dragMode || !this.lastPointer) return;
        const dx=e.clientX-this.lastPointer.x, dy=e.clientY-this.lastPointer.y; this.lastPointer={x:e.clientX,y:e.clientY};
        if (this.dragMode==='orbit') {
          sharedView.yaw += dx*.45; sharedView.pitch = clamp(sharedView.pitch + dy*.45,-82,82);
        } else { sharedView.panX += dx; sharedView.panY += dy; }
        renderAllViewers(true);
      });
      const end = e => {
        if (!this.dragMode) return;
        this.dragMode=''; this.lastPointer=null;
        try { this.canvas.releasePointerCapture(e.pointerId); } catch (_) {}
        renderAllViewers(false);
      };
      this.canvas.addEventListener('pointerup',end); this.canvas.addEventListener('pointercancel',end);
      this.canvas.addEventListener('wheel', e => {
        e.preventDefault();
        sharedView.zoom = clamp(sharedView.zoom * (e.deltaY < 0 ? 1.12 : 1/1.12), .35, 5);
        renderAllViewers(true);
      }, { passive:false });
    }

    setProject(next) {
      this.project = next || browserPreviewProject;
      this.rebuildGeometry();
      this.updateTextures();
      this.render();
    }

    referenceVisible() { return !!this.project?.assets?.reference_heightmap && !!this.project?.settings?.reference_heightmap_show; }
    importedGeometry() { return !!this.project?.assets?.reference_heightmap && (this.referenceVisible() || this.project?.settings?.workflow === 'Build from heightmap'); }
    settings() {
      const s=(this.project && this.project.settings)||browserPreviewProject.settings;
      return this.importedGeometry()?{...s,width_mm:s.reference_heightmap_width_mm,height_mm:s.reference_heightmap_height_mm,orientation:s.reference_heightmap_orientation}:s;
    }

    rebuildGeometry() {
      const s=this.settings(), vertical=String(s.orientation || 'Vertical') !== 'Horizontal';
      const width=Math.max(.01,Number(s.width_mm||100)), height=Math.max(.01,Number(s.height_mm||100)), lpi=Math.max(.001,Number(s.lpi||24));
      const peak=this.importedGeometry()?Math.max(.0001,Number(s.reference_heightmap_thickness_mm||1.86)):s.output_mode==='Lens-Free Relief' ? Math.max(.001,Number(s.relief_prism_height_mm||.8)) : Math.max(.001,Number(s.thickness_mm||s.manual_thickness_mm||1));
      const base=s.output_mode==='Lens-Free Relief' ? 0 : clamp(Number(s.base_mm ?? s.manual_base_mm ?? .3),0,peak);
      const rise=Math.max(0,peak-base), axisMm=vertical?width:height, lensCount=Math.max(1,axisMm/25.4*lpi);
      const imported=this.importedGeometry() ? this.project?.reference_heightmap_info?.[vertical?'profile_x':'profile_y'] : null;
      const hasProfile=Array.isArray(imported)&&imported.length>1;
      if(this.importedGeometry() && (!hasProfile || this.project?.reference_heightmap_info?.grayscale === false)){ this.vertices=new Float32Array();return; }
      const samples=hasProfile?imported.length:clamp(Math.ceil(lensCount*9),80,600), pitchSamples=samples/lensCount, ratio=rise/Math.max(1e-8,25.4/lpi), baseFraction=peak>0?base/peak:0, offset=Number(s.phase_pitch||0);
      const heights=new Float32Array(samples);
      for(let i=0;i<samples;i++) heights[i]=hasProfile?imported[vertical?i:samples-1-i]*peak:base + profileValue(s,i/pitchSamples+offset,pitchSamples,ratio,baseFraction)*rise;
      const verts=[], uvs=[], normals=[];
      for(let i=0;i<samples;i++){
        const a=i/(samples-1), z=heights[i]-peak*.5;
        const im=Math.max(0,i-1), ip=Math.min(samples-1,i+1), axis0=-axisMm*.5+im/(samples-1)*axisMm, axis1=-axisMm*.5+ip/(samples-1)*axisMm;
        const slope=(heights[ip]-heights[im])/Math.max(1e-8,axis1-axis0), inv=1/Math.sqrt(1+slope*slope);
        const nx=vertical?-slope*inv:0, ny=vertical?0:-slope*inv, nz=inv;
        if(vertical){
          const x=-width*.5+a*width;
          verts.push(x,-height*.5,z, x,height*.5,z); uvs.push(a,0,a,1);
        }else{
          const y=-height*.5+a*height;
          verts.push(-width*.5,y,z, width*.5,y,z); uvs.push(0,a,1,a);
        }
        normals.push(nx,ny,nz,nx,ny,nz);
      }
      const idx=[]; for(let i=0;i<samples-1;i++){const a=i*2,b=a+1,c=a+2,d=a+3;idx.push(a,c,d,a,d,b);}
      this.vertices=new Float32Array(verts); this.uv=new Float32Array(uvs); this.normals=new Float32Array(normals); this.indices=new Uint16Array(idx);
      this.maxDim=Math.max(width,height,peak*4,1); this.peak=peak; this.axisSamples=samples;
      if(this.gl){
        const gl=this.gl; gl.bindBuffer(gl.ARRAY_BUFFER,this.uvBuffer); gl.bufferData(gl.ARRAY_BUFFER,this.uv,gl.STATIC_DRAW);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,this.indexBuffer); gl.bufferData(gl.ELEMENT_ARRAY_BUFFER,this.indices,gl.STATIC_DRAW);
      }
    }

    loadTexture(path) {
      if (!this.gl || !path) return Promise.resolve(this.neutralTexture);
      const aspect=Math.max(.01,Number(this.settings().width_mm||100))/Math.max(.01,Number(this.settings().height_mm||100));
      const generatedPath=((this.project||{}).assets||{}).interlaced_image||''; const revision=path===generatedPath?((this.project&&this.project.revision)||assetRevisionToken()):0; const key=`${path}|${aspect.toFixed(5)}|${revision}`;
      if(this.textureCache.has(key)) return Promise.resolve(this.textureCache.get(key));
      return new Promise(resolve => {
        const img=new Image(); img.draggable=false;
        img.onload=()=>{
          try{
            const maxSide=2048; let w,h; if(aspect>=1){w=maxSide;h=Math.max(1,Math.round(maxSide/aspect));}else{h=maxSide;w=Math.max(1,Math.round(maxSide*aspect));}
            const c=document.createElement('canvas');c.width=w;c.height=h;const ctx=c.getContext('2d',{alpha:false});ctx.fillStyle='#fff';ctx.fillRect(0,0,w,h);
            const scale=Math.max(w/img.naturalWidth,h/img.naturalHeight),dw=img.naturalWidth*scale,dh=img.naturalHeight*scale,dx=(w-dw)/2,dy=(h-dh)/2;
            ctx.imageSmoothingEnabled=true;ctx.imageSmoothingQuality='high';ctx.drawImage(img,dx,dy,dw,dh);
            const gl=this.gl, tex=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,tex);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
            gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,c);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
            this.textureCache.set(key,tex);resolve(tex);
          }catch(_){resolve(this.neutralTexture);}
        };
        img.onerror=()=>resolve(this.neutralTexture); img.src=fileUrl(path,revision||'');
      });
    }

    async updateTextures() {
      if(!this.gl) return;
      if(this.referenceVisible()){++this.textureToken;this.textureKey='reference';this.texA=this.neutralTexture;this.texB=this.neutralTexture;this.blend=0;this.selectionLabel='Reference heightmap';this.render();return;}
      const selection=viewerSelection(this.settings(),sharedView), generatedPath=((this.project||{}).assets||{}).interlaced_image||'', revision=(this.project&&this.project.revision)||assetRevisionToken(), key=`${selection.pathA}|${selection.pathB}|${selection.pathA===generatedPath?revision:0}|${selection.pathB===generatedPath?revision:0}`;
      this.blend=selection.blend;this.selectionLabel=selection.label;
      if(key===this.textureKey){this.render();return;}
      this.textureKey=key; const token=++this.textureToken;
      const [a,b]=await Promise.all([this.loadTexture(selection.pathA),this.loadTexture(selection.pathB)]);
      if(token!==this.textureToken)return;this.texA=a;this.texB=b;this.render();
    }

    render() {
      if(!this.canvas || !this.gl || !this.program) return;
      const gl=this.gl, rect=this.canvas.getBoundingClientRect(), dpr=Math.min(2,window.devicePixelRatio||1), w=Math.max(2,Math.round(rect.width*dpr)), h=Math.max(2,Math.round(rect.height*dpr));
      if(this.canvas.width!==w||this.canvas.height!==h){this.canvas.width=w;this.canvas.height=h;}
      gl.viewport(0,0,w,h);gl.clearColor(24/255,29/255,34/255,1);gl.clearDepth(1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
      if(!this.vertices?.length){if(this.empty){this.empty.style.display='grid';this.empty.querySelector('strong').textContent='Heightmap preview unavailable';this.empty.querySelector('span').textContent=this.project?.reference_heightmap_info?.message||'Reading heightmap...';}return;}
      const hasImage=!!(this.importedGeometry() && this.project?.reference_heightmap_info?.profile_x?.length) || !!((sourceItems.length&&sourceItems[0].path)||((this.project||{}).assets||{}).interlaced_image||selectedSourcePreviewPath);
      if(this.empty)this.empty.style.display=hasImage?'none':'grid';
      if(!hasImage)return;

      const yaw=degToRad(sharedView.yaw),pitch=degToRad(sharedView.pitch),cy=Math.cos(yaw),sy=Math.sin(yaw),cp=Math.cos(pitch),sp=Math.sin(pitch),cameraDistance=Math.max(1,this.maxDim*2), baseScale=Math.min(w,h)*.78/Math.max(.001,this.maxDim)*sharedView.zoom;
      const panX=sharedView.panX*dpr,panY=sharedView.panY*dpr, clips=new Float32Array((this.vertices.length/3)*4), shades=new Float32Array(this.vertices.length/3);
      const lx=-.30,ly=-.40,lz=.86,ll=Math.sqrt(lx*lx+ly*ly+lz*lz),nlx=lx/ll,nly=ly/ll,nlz=lz/ll;
      let ci=0;
      for(let i=0,v=0;i<this.vertices.length;i+=3,v++){
        const x=this.vertices[i],y=this.vertices[i+1],z=this.vertices[i+2];
        const x1=x*cy+z*sy,z1=-x*sy+z*cy,y2=y*cp-z1*sp,z2=y*sp+z1*cp;
        const denom=Math.max(cameraDistance*.35,cameraDistance-z2),persp=cameraDistance/denom;
        const sx=w*.5+panX+x1*baseScale*persp, syScreen=h*.53+panY-y2*baseScale*persp;
        const ndcX=sx/w*2-1,ndcY=1-syScreen/h*2,wn=denom/cameraDistance;
        const depth=clamp((denom-cameraDistance*.35)/(cameraDistance*1.7),0,1)*2-1;
        clips[ci++]=ndcX*wn;clips[ci++]=ndcY*wn;clips[ci++]=depth*wn;clips[ci++]=wn;
        let nx=this.normals[i],ny=this.normals[i+1],nz=this.normals[i+2];
        const nx1=nx*cy+nz*sy,nz1=-nx*sy+nz*cy,ny2=ny*cp-nz1*sp,nz2=ny*sp+nz1*cp;
        shades[v]=clamp(Math.abs(nx1*nlx+ny2*nly+nz2*nlz),0,1);
      }
      gl.useProgram(this.program);
      gl.bindBuffer(gl.ARRAY_BUFFER,this.clipBuffer);gl.bufferData(gl.ARRAY_BUFFER,clips,gl.DYNAMIC_DRAW);gl.enableVertexAttribArray(this.aClip);gl.vertexAttribPointer(this.aClip,4,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ARRAY_BUFFER,this.uvBuffer);gl.enableVertexAttribArray(this.aUv);gl.vertexAttribPointer(this.aUv,2,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ARRAY_BUFFER,this.shadeBuffer);gl.bufferData(gl.ARRAY_BUFFER,shades,gl.DYNAMIC_DRAW);gl.enableVertexAttribArray(this.aShade);gl.vertexAttribPointer(this.aShade,1,gl.FLOAT,false,0,0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER,this.indexBuffer);
      gl.activeTexture(gl.TEXTURE0);gl.bindTexture(gl.TEXTURE_2D,this.texA||this.neutralTexture);gl.uniform1i(this.uTexA,0);
      gl.activeTexture(gl.TEXTURE1);gl.bindTexture(gl.TEXTURE_2D,this.texB||this.texA||this.neutralTexture);gl.uniform1i(this.uTexB,1);gl.uniform1f(this.uBlend,this.blend||0);
      gl.uniform1f(this.uReferenceStyle,this.referenceVisible()?({OPAQUE:1,TINTED:2,CLEAR:3}[this.settings().reference_heightmap_display_style]||1):0);
      gl.drawElements(gl.TRIANGLES,this.indices.length,gl.UNSIGNED_SHORT,0);
      if(this.info){const s=this.settings(),angle=(String(s.orientation||'Vertical')==='Horizontal'?sharedView.pitch:sharedView.yaw);this.info.textContent=`${sharedView.mode} · ${this.selectionLabel} · View ${angle>=0?'+':''}${angle.toFixed(1)} deg · ${Number(s.lpi||0).toFixed(3).replace(/\.000$/,'')} LPI · 50 mm camera target`;}
    }
  }

  function updateViewers(next) { liveViewers.forEach(v => v && v.setProject(next || project || browserPreviewProject)); }
  function requestViewerResize() { requestAnimationFrame(() => liveViewers.forEach(v => v && v.render())); }
  function renderAllViewers(interactive) {
    liveViewers.forEach(v => { if(v){v.updateTextures();v.render();} });
    if(!interactive) updateViewerInfoMode();
  }

  function viewingSpread() {
    const s=(project&&project.settings)||browserPreviewProject.settings;
    if(s.output_mode==='Lens-Free Relief'){const a=reliefFacetAngles(s);return a.length?Math.max(...a)-Math.min(...a):30;}
    return clamp(Number(s.viewing_angle_deg||s.custom_viewing_angle_deg||60),1,175);
  }

  function setViewPreset(direction) {
    const s=liveViewers[0]?.settings()||(project&&project.settings)||browserPreviewProject.settings, half=clamp(viewingSpread()*.42,8,55);
    if(String(s.orientation||'Vertical')==='Horizontal'){sharedView.yaw=0;sharedView.pitch=direction*half;}else{sharedView.yaw=direction*half;sharedView.pitch=0;}
    sharedView.zoom=1;sharedView.panX=0;sharedView.panY=0;renderAllViewers(false);
  }
  function frontView(){sharedView.yaw=0;sharedView.pitch=0;sharedView.zoom=1;sharedView.panX=0;sharedView.panY=0;renderAllViewers(false);}

  function updateViewerButtonLabels(){
    const horizontal=(project?.settings?.reference_heightmap_show ? project.settings.reference_heightmap_orientation : controls.orientation.value)==='Horizontal';
    if($('side3dLeft')) $('side3dLeft').textContent=horizontal?'Top':'Left';
    if($('side3dRight')) $('side3dRight').textContent=horizontal?'Bottom':'Right';
  }
  function updateViewerInfoMode(){
    const s=(project&&project.settings)||browserPreviewProject.settings;
    if(s.output_mode==='Lens-Free Relief' && sharedView.mode!=='View Effect Approximation') sharedView.mode='View Effect Approximation';
    renderAllViewers(true);
  }

  async function startCore() {
    const result = await api.startBackend();
    if (result.ok) {
      updateBackendStatus(true, 'Processing ready');
      setStatus('Integrated processing is ready.');
    } else {
      updateBackendStatus(false, 'Processing unavailable');
      setStatus(result.error || 'Integrated processing could not be initialized.');
    }
  }

  function activatePage(name) {
    document.querySelectorAll('.nav-item').forEach(b => b.classList.toggle('active', b.dataset.page === name));
    document.querySelectorAll('.page').forEach(p => p.classList.toggle('active', p.dataset.page === name));
    requestViewerResize();
  }

  function setupNavigation() {
    document.querySelectorAll('.nav-item').forEach(button => button.addEventListener('click', () => activatePage(button.dataset.page)));
  }

  async function addImagesFromDialog(navigate = true) {
    const items = await api.addImages();
    if (!items || !items.length) return;
    for (const item of items) {
      if (sourceItems.length >= 8) break;
      if (!sourceItems.some(x => (x.path || '').toLowerCase() === item.path.toLowerCase())) sourceItems.push(item);
    }
    if (currentWorkflow !== 'Build from heightmap') setWorkflow('Build from source frames'); syncViewsToSourceCount(); renderSources(); updateControlStates(true); queueWrite('rebuild-pair');
    if (navigate) activatePage('sources');
  }

  async function importExistingInterlaced(navigate = true) {
    const item = await api.importInterlaced();
    if (!item) return;
    setWorkflow('Use existing interlaced image');
    selectedSourcePreviewPath = item.path;
    resultPreviewPath = item.path;
    showSidePreviewPath(item.path);
    showResultPreviewPath(item.path);
    if(project){project.assets=project.assets||{};project.assets.interlaced_image=item.path;project.assets.heightmap='';}
    showHeightmapPreviewPath('');
    updateControlStates(true); updateSourceActionState(); updateViewers(project); setStatus(`Imported ${item.name}. Existing-interlaced workflow selected automatically.`);
    if(navigate) activatePage('sources');
  }

  async function exportGeneratedAsset(kind) {
    const result = await api.exportAsset(kind);
    if (result && result.ok) setStatus(`${kind === 'heightmap' ? 'Heightmap' : 'Interlaced image'} exported to ${result.path}.`);
    else if (result && !result.canceled) setStatus(result.error || `Could not export ${kind}.`);
  }

  async function requestGeneratePair() {
    await startCore();
    if (currentWorkflow !== 'Use existing interlaced image') {
      $('resultInterlacedPath').textContent = 'Rebuilding...';
      $('resultHeightmapPath').textContent = 'Waiting for interlaced image...';
    } else {
      $('resultHeightmapPath').textContent = 'Rebuilding...';
    }
    const updated = await publishNow('generate-pair');
    if (updated) setStatus(currentWorkflow === 'Build from heightmap' ? 'Generating the interlaced image and a copy of the imported heightmap...' : currentWorkflow === 'Build from source frames'
      ? 'Generating the interlaced image and matching 16-bit heightmap as one transaction...'
      : 'Using the imported interlaced image and regenerating its matching 16-bit heightmap...');
  }

  async function exportBothGeneratedAssets() {
    const result = await api.exportBothAssets();
    if (result && result.ok) setStatus(`Interlaced image and heightmap exported together to ${result.folder}.`);
    else if (result && !result.canceled) setStatus(result.error || 'Could not export the generated asset pair.');
  }

  function testExportSignature(value) {
    const assets = value?.assets || {};
    const generation = value?.generation || {};
    return JSON.stringify({
      revision: Number(value?.revision || 0),
      interlaced_image: assets.interlaced_image || '',
      heightmap: assets.heightmap || '',
      generation_status: generation.status || '',
      generation_input_revision: generation.input_revision ?? null,
      settings: value?.settings || {}
    });
  }

  async function fetchAssetBytes(path, revision) {
    const response = await fetch(fileUrl(path, revision), { cache: 'no-store', credentials: 'same-origin' });
    if (!response.ok) throw new Error(`Could not read ${path.split(/[\\/]/).pop() || 'generated image'} (${response.status}).`);
    return new Uint8Array(await response.arrayBuffer());
  }

  function suggestedTestFilename() {
    const d = new Date(), pad = n => String(n).padStart(2,'0');
    return `Lenticulizer_Test_${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}.zip`;
  }

  async function saveTestZip(bytes, suggestedName, expectedSignature) {
    if ('showSaveFilePicker' in window) {
      let handle;
      try {
        handle = await window.showSaveFilePicker({
          suggestedName,
          types: [{ description: 'Lenticulizer labeled test set', accept: { 'application/zip': ['.zip'] } }]
        });
      } catch (error) {
        if (error?.name === 'AbortError') return { canceled: true };
        throw error;
      }
      const latest = await api.readProject();
      if (testExportSignature(latest) !== expectedSignature) throw new Error('The project changed while the Save dialog was open. Review the current output and export the labeled test set again.');
      const writable = await handle.createWritable();
      try { await writable.write(new Blob([bytes], { type: 'application/zip' })); await writable.close(); }
      catch (error) { try { await writable.abort(); } catch (_) {} throw error; }
      return { canceled: false, path: handle.name || suggestedName };
    }

    const latest = await api.readProject();
    if (testExportSignature(latest) !== expectedSignature) throw new Error('The project changed while the labeled test set was being prepared. Review the current output and retry.');
    const url = URL.createObjectURL(new Blob([bytes], { type: 'application/zip' }));
    try {
      const link = document.createElement('a');
      link.href = url; link.download = suggestedName; link.style.display = 'none';
      document.body.appendChild(link); link.click(); link.remove();
    } finally { setTimeout(() => URL.revokeObjectURL(url), 30000); }
    return { canceled: false, path: suggestedName };
  }

  async function exportLabeledTestSet() {
    try {
      if (!globalThis.LenticulizerTestOutput) throw new Error('The labeled test export component is unavailable. Reopen Lenticulizer and retry.');
      const current = await api.readProject();
      const assets = current?.assets || {};
      const generation = current?.generation || {};
      if (!assets.interlaced_image || !assets.heightmap) throw new Error('Generate the matching interlaced image and heightmap before exporting a labeled test set.');
      if (generation.status && generation.status !== 'ready') throw new Error('Wait for the current image and heightmap generation to finish successfully before exporting a labeled test set.');
      const signature = testExportSignature(current);
      setStatus('Preparing labeled test set...');
      const [colorBytes, heightmapBytes] = await Promise.all([
        fetchAssetBytes(assets.interlaced_image, current.revision || 0),
        fetchAssetBytes(assets.heightmap, current.revision || 0)
      ]);
      const created = new Date().toISOString();
      const result = await globalThis.LenticulizerTestOutput.createTestSet(
        colorBytes, heightmapBytes, current.settings || {}, ($('testOutputName')?.value || '').trim(), bootstrap?.version || '3.0.0-alpha.32', created
      );
      const latest = await api.readProject();
      if (testExportSignature(latest) !== signature) throw new Error('The project changed while the labeled test set was being prepared. Review the current output and retry.');
      const saved = await saveTestZip(result.zip, suggestedTestFilename(), signature);
      if (saved.canceled) { setStatus('Labeled test export canceled.'); return; }
      const mm = result.plan?.canvas_size_mm || [];
      const sizeText = mm.length >= 2 ? ` Test canvas: ${Number(mm[0]).toFixed(2)} x ${Number(mm[1]).toFixed(2)} mm.` : '';
      setStatus(`Labeled test set exported as ${saved.path}.${sizeText}`);
    } catch (error) {
      setStatus(`Could not export labeled test set: ${error?.message || error}`);
    }
  }

  function showGeneratedAsset(kind) {
    const assets = (project && project.assets) || {};
    const p = kind === 'heightmap' ? assets.heightmap : assets.interlaced_image;
    if (p) api.showPath(p);
    else setStatus(`No ${kind === 'heightmap' ? 'heightmap' : 'interlaced image'} has been generated yet.`);
  }

  function numericFallbackFor(el) {
    const s = (project && project.settings) || browserPreviewProject.settings;
    if (el === controls.widthMm) return Number(s.width_mm || 100) / (displayUnit === 'in' ? 25.4 : 1);
    if (el === controls.heightMm) return Number(s.height_mm || 100) / (displayUnit === 'in' ? 25.4 : 1);
    if (el === controls.lpi) return Number(s.lpi || 24);
    if (el === controls.views) return Number(s.views || sourceItems.length || 2);
    if (el === controls.pixelsPerLens) return Number(s.pixels_per_lenticule || 60);
    if (el === controls.manualThickness) return Number(s.manual_thickness_mm || 1);
    if (el === controls.ior) return Number(s.ior || 1.55);
    if (el === controls.manualBase) return Number(s.manual_base_mm ?? .3);
    if (el === controls.customAngle) return Number(s.custom_viewing_angle_deg || 44);
    if (el === controls.reliefHeight) return Number(s.relief_prism_height_mm || .8);
    if (el === controls.backingMm) return Number(s.backing_saved_mm || s.backing_mm || 5);
    return 0;
  }

  function normalizeNumericInput(el) {
    if (!isNumericInput(el)) return true;
    const raw = String(el.value || '').trim().replace(',', '.');
    let value = Number(raw);
    let min = el.min !== '' ? Number(el.min) : -Infinity;
    let max = el.max !== '' ? Number(el.max) : Infinity;
    if (el === controls.ior) { min = 1.001; max = 3.0; }
    if (!Number.isFinite(value)) {
      value = numericFallbackFor(el);
      el.value = String(value);
      setStatus(`${el.previousElementSibling ? el.previousElementSibling.textContent : 'Value'} was not a valid number and was restored.`);
      return false;
    }
    if (Number.isFinite(min) && value < min) value = min;
    if (Number.isFinite(max) && value > max) value = max;
    if (el === controls.views) value = Math.round(value);
    if (el === controls.pixelsPerLens) value = Math.round(value);
    el.value = String(value);
    return true;
  }

  function isNumericInput(el) { return !!el && el.tagName === 'INPUT' && el.type === 'number'; }

  function numericDraftIsUsable(el) {
    if (!isNumericInput(el)) return false;
    const raw = String(el.value || '').trim().replace(',', '.');
    if (!raw || raw === '-' || raw === '+' || raw.endsWith('e') || raw.endsWith('E') || raw.endsWith('e-') || raw.endsWith('E-') || raw.endsWith('e+') || raw.endsWith('E+')) return false;
    const value = Number(raw);
    if (!Number.isFinite(value)) return false;
    if (el === controls.ior) return value >= 1.001 && value <= 3.0;
    if (el === controls.customAngle) return value > 0 && value < 179;
    if (el === controls.views) return value >= 1 && value <= 8;
    if (el === controls.phase) return value >= -0.5 && value <= 0.5;
    if (el.min !== '' && Number.isFinite(Number(el.min)) && value < Number(el.min)) return false;
    if (el.max !== '' && Number.isFinite(Number(el.max)) && value > Number(el.max)) return false;
    return true;
  }

  function markEditing(el, editing) {
    if (!el) return;
    if (editing) el.dataset.userEditing = '1';
    else delete el.dataset.userEditing;
  }

  function bindControls() {
    document.querySelectorAll('input[name="settings-mode"]').forEach(option => {
      option.addEventListener('change', () => {
        if (!option.checked || option.value === controls.settingsMode.value) return;
        controls.settingsMode.value = option.value;
        controls.settingsMode.dispatchEvent(new Event('change', { bubbles: true }));
      });
    });
    Object.values(controls).forEach(el => {
      if (!el) return;
      if (isNumericInput(el)) {
        el.addEventListener('focus', () => markEditing(el, true));
        el.addEventListener('blur', () => { normalizeNumericInput(el); markEditing(el, false); });
        el.addEventListener('keydown', event => {
          if (event.key === 'Enter') { event.preventDefault(); el.blur(); }
        });
        el.addEventListener('input', () => {
          if (el.disabled || el.readOnly || !numericDraftIsUsable(el)) return;
          updateControlStates(false);
          queueWrite(rebuildPriorityForControl(el));
          const base = project || browserPreviewProject;
          updateViewers({ ...base, settings: { ...(base.settings || {}), ...settingsPatch().settings } });
        });
      }
      const event = el.type === 'range' ? 'input' : 'change';
      el.addEventListener(event, () => {
        if (isNumericInput(el) && !normalizeNumericInput(el)) return;
        if (el === controls.units) {
          const newUnit = controls.units.value === 'in' ? 'in' : 'mm';
          if (newUnit !== displayUnit) {
            const factor = displayUnit === 'mm' && newUnit === 'in' ? (1 / 25.4) : 25.4;
            controls.widthMm.value = (num(controls.widthMm, 100) * factor).toFixed(newUnit === 'in' ? 4 : 2).replace(/0+$/, '').replace(/\.$/, '');
            controls.heightMm.value = (num(controls.heightMm, 100) * factor).toFixed(newUnit === 'in' ? 4 : 2).replace(/0+$/, '').replace(/\.$/, '');
            displayUnit = newUnit;
          }
        }
        if (el === controls.phase) $('phaseValue').textContent = `${num(el,0) >= 0 ? '+' : ''}${num(el,0).toFixed(3)} pitch`;
        if (el === controls.outputMode) {
          const relief = el.value === 'Lens-Free Relief';
          $('lensSettingsCard').classList.toggle('hidden', relief); $('reliefSettingsCard').classList.toggle('hidden', !relief);
                sharedView.mode = relief ? 'View Effect Approximation' : 'Optical Refraction Preview';
        }
        updateControlStates(true);
        if (el === controls.orientation) { renderSources(); updateViewerButtonLabels(); }
        queueWrite(rebuildPriorityForControl(el));
        updateViewers({ ...(project || browserPreviewProject), settings: { ...((project&&project.settings)||browserPreviewProject.settings), ...settingsPatch().settings } });
      });
    });

    if ($('analyzeButton')) $('analyzeButton').addEventListener('click', async () => {
      await startCore(); const updated = await publishNow('analyze');
      if (updated) setStatus('Analyzing the interlaced image.');
    });
    if ($('calibrationButton')) $('calibrationButton').addEventListener('click', async () => {
      await startCore(); const updated = await publishNow('calibration');
      if (updated) setStatus('Generating calibration coupons for the selected folder.');
    });
    if ($('openBlenderButton')) $('openBlenderButton').addEventListener('click', async () => {
      await startCore(); const updated = await publishNow('blender-open'); if (updated) setStatus('Opening the current project in Blender...');
    });
    if ($('exportBlenderButton')) $('exportBlenderButton').addEventListener('click', async () => {
      await startCore(); const updated = await publishNow('blender-export'); if (updated) setStatus('Portable Blender package export requested.');
    });
    if ($('resetBlenderButton')) $('resetBlenderButton').addEventListener('click', async () => {
      await startCore(); const updated = await publishNow('blender-reset'); if (updated) setStatus('Blender scene reset requested.');
    });

    $('projectAddImagesButton').addEventListener('click', () => addImagesFromDialog(true));
    $('addImagesButton').addEventListener('click', () => addImagesFromDialog(false));
    $('importInterlacedButton').addEventListener('click', () => importExistingInterlaced(true));
    $('importInterlacedImagesButton').addEventListener('click', () => importExistingInterlaced(true));
    $('clearImagesButton').addEventListener('click', () => { sourceItems = []; if (currentWorkflow === 'Build from source frames') controls.views.value = ''; renderSources(); updateControlStates(true); queueWrite('rebuild-pair'); });

    $('generatePairButton').addEventListener('click', requestGeneratePair);
    if ($('opticsGeneratePairButton')) $('opticsGeneratePairButton').addEventListener('click', requestGeneratePair);
    if ($('imagesViewOutputButton')) $('imagesViewOutputButton').addEventListener('click', () => activatePage('output'));
    if ($('opticsViewOutputButton')) $('opticsViewOutputButton').addEventListener('click', () => activatePage('output'));
    $('syncBlenderButton').addEventListener('click', async () => {
      await startCore();
      const updated = await publishNow('blender-sync');
      if (updated) setStatus('Published a new shared-project revision for Blender.');
    });

    if ($('outputGeneratePairButton')) $('outputGeneratePairButton').addEventListener('click', requestGeneratePair);
    if ($('outputShowInterlacedButton')) $('outputShowInterlacedButton').addEventListener('click', () => showGeneratedAsset('interlaced'));
    if ($('outputShowHeightmapButton')) $('outputShowHeightmapButton').addEventListener('click', () => showGeneratedAsset('heightmap'));
    if ($('outputExportInterlacedButton')) $('outputExportInterlacedButton').addEventListener('click', () => exportGeneratedAsset('interlaced'));
    if ($('outputExportHeightmapButton')) $('outputExportHeightmapButton').addEventListener('click', () => exportGeneratedAsset('heightmap'));
    if ($('outputExportBothButton')) $('outputExportBothButton').addEventListener('click', exportBothGeneratedAssets);
    if ($('exportTestSetButton')) $('exportTestSetButton').addEventListener('click', exportLabeledTestSet);
    $('openSessionButton').addEventListener('click', () => bootstrap && api.openPath(bootstrap.sessionDir));
    $('showAddonButton').addEventListener('click', () => bootstrap && api.showPath(bootstrap.blenderAddon));
    if ($('runtimeNoticesButton')) $('runtimeNoticesButton').addEventListener('click', () => api.runtimeNotices && api.runtimeNotices());
    if ($('helpRuntimeNoticesButton')) $('helpRuntimeNoticesButton').addEventListener('click', () => api.runtimeNotices && api.runtimeNotices());

    $('previewImageTab').addEventListener('click', () => {
      $('previewImageTab').classList.add('active'); $('preview3dTab').classList.remove('active');
      $('sideImagePane').classList.add('active'); $('side3dPane').classList.remove('active');
    });
    $('preview3dTab').addEventListener('click', () => {
      $('preview3dTab').classList.add('active'); $('previewImageTab').classList.remove('active');
      $('side3dPane').classList.add('active'); $('sideImagePane').classList.remove('active'); requestViewerResize(); renderAllViewers(false);
    });

    if($('side3dFront')) $('side3dFront').addEventListener('click',frontView);
    if($('side3dLeft')) $('side3dLeft').addEventListener('click',()=>setViewPreset(-1));
    if($('side3dRight')) $('side3dRight').addEventListener('click',()=>setViewPreset(1));
  }

  function preventDocumentSelectionArtifacts() {
    document.addEventListener('dragstart', event => {
      if (event.target.closest && event.target.closest('.source-card')) return;
      event.preventDefault();
    });
    document.addEventListener('selectstart', event => {
      const t=event.target;
      if (t && (t.matches('input, textarea, [contenteditable="true"]') || t.closest('input, textarea, [contenteditable="true"]'))) return;
      event.preventDefault();
    });
  }

  async function init() {
    window.addEventListener('unhandledrejection', event => {
      setStatus(`Action failed: ${event.reason?.message || event.reason || 'Unknown error'}`);
      event.preventDefault();
    });
    setupNavigation(); bindControls(); bindReferenceControls(); setupSourceDropZone(); setupSplitters(); setupUpdates(); preventDocumentSelectionArtifacts();

    liveViewers.push(new Live3DViewer($('side3dCanvas'), $('side3dEmpty')));

    bootstrap = await api.bootstrap();
    renderUpdateStatus(bootstrap.update || await api.updateStatus());
    if ($('helpAppVersion')) $('helpAppVersion').textContent = `Lenticulizer 3D ${bootstrap.version || '3.0.0-alpha.32'}`;
    if(bootstrap.uiTesting) window.__lenticulizerDiagnostics=Object.freeze({view:()=>({...sharedView}),geometry:()=>({samples:liveViewers[0].axisSamples,imported:liveViewers[0].importedGeometry()})});
    $('sessionName').textContent = bootstrap.sessionDir.split(/[\\/]/).pop();
    $('projectPathLabel').textContent = bootstrap.projectPath;
    project = bootstrap.project;
    sourceItems = ((project.assets && project.assets.source_frames) || []).map(p => ({ path: p, name: p.split(/[\\/]/).pop(), url: fileUrl(p) }));
    renderSources(); updateFromProject(project); updateViewerInfoMode();

    if (bootstrap.backendExists) {
      updateBackendStatus(false, 'Processing ready');
      setStatus('Initializing project...');
      await startCore();
    } else {
      updateBackendStatus(false, 'UI preview');
      setStatus('Interface preview only. Open Lenticulizer.exe on Windows to process images.');
    }

    let lastCommandResultId = null;
    api.onProjectUpdated(next => {
      const currentRevision = Number(project && project.revision || 0);
      const nextRevision = Number(next && next.revision || 0);
      if (!next.project_switched && nextRevision < currentRevision) return;
      if (next.project_switched) {
        clearTimeout(writeTimer); clearTimeout(solveTimer); ++outgoingBuildSequence;
        ++solveSequence; appliedSolveSequence = 0; lastSolvedSettings = null;
        settingsDirty = false; deferredProject = null;
        bootstrap = { ...bootstrap, projectPath: next.active_project_path, sessionDir: next.active_session_dir };
        $('sessionName').textContent = bootstrap.sessionDir.split(/[\\/]/).pop();
      }
      if (settingsDirty) {
        deferredProject = next;
        const draft = settingsPatch();
        updateFromProject({ ...next, settings: { ...(project && project.settings), ...draft.settings }, assets: { ...next.assets, source_frames: draft.assets.source_frames } });
      } else updateFromProject(next);
      if (next.changed_by === 'app') {
        const generation = next.generation || {};
        const command = next.command_request?.id === next.command_result?.id ? next.command_result : null;
        if (command && command.id !== lastCommandResultId) {
          lastCommandResultId = command.id;
          setStatus(command.status === 'failed' ? `Action failed: ${command.error}` : `${command.message || 'Action complete.'}${command.path ? ` ${command.path}` : ''}`);
        } else if (generation.status === 'failed') setStatus(`Generation failed: ${generation.error || 'Check the current settings.'} The previous output files are retained.`);
        else if (generation.status === 'waiting-for-sources') setStatus('Add at least two source images to generate the matching output pair.');
        else if (generation.status === 'waiting-for-interlace') setStatus('Import an interlaced image to generate its matching heightmap.');
        else setStatus(`Completed project revision ${next.revision}.`);
      }
    });
    api.onBackendStatus(status => updateBackendStatus(status.running, status.running ? 'Processing ready' : 'Processing stopped'));
    api.onUpdateStatus(status => renderUpdateStatus(status));
    window.addEventListener('resize', requestViewerResize);
  }

  init().catch(err => setStatus(`Startup error: ${err.message || err}`));
})();
