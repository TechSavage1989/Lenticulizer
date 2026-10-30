from pathlib import Path
from html.parser import HTMLParser
import re,ast,tomllib,zipfile
root=Path(__file__).resolve().parent.parent
class DOM(HTMLParser):
 def __init__(self):super().__init__();self.ids=[]
 def handle_starttag(self,tag,attrs):
  self.ids.extend(v for k,v in attrs if k=='id')
dom=DOM();dom.feed((root/'ui/src/index.html').read_text())
assert len(dom.ids)==len(set(dom.ids)), 'Duplicate HTML ids'
script=(root/'ui/src/renderer.js').read_text()
refs=set(re.findall(r"\$\('([^']+)'\)",script))
# These four optional legacy preview elements are guarded in the existing renderer.
optional={'heightmapResultImage','heightmapResultPlaceholder','resultImage','resultPlaceholder'}
assert not refs-set(dom.ids)-optional
assert 'yaw: 0, pitch: 0' in script
update=script[script.index('    setProject(next) {'):script.index('    referenceVisible()')]
assert 'frontView' not in update and 'sharedView.' not in update
for name in ['referenceWidth','referenceHeight','referenceScale','referenceOrientation','referenceDetection','referencePitch','referencePhase','referenceStyle','referenceBuildButton','referencePreviewButton']:
 assert name in dom.ids
bridge=(root/'ui/src/bridge.js').read_text();native=(root/'app/AppWindow.cs').read_text()
for method in ['heightmap:import','heightmap:analyze']:
 assert method in bridge and method in native
assert 'reference_heightmap' in (root/'app/IntegratedProject.cs').read_text()
addon=root/'blender/Lenticulizer_Blender_Addon_v1.18.43'
manifest=tomllib.loads((addon/'blender_manifest.toml').read_text())
assert manifest['schema_version']=='1.0.0' and manifest['version']=='1.18.43' and manifest['id']=='lenticular_blender_sync'
for p in addon.glob('*.py'):ast.parse(p.read_text())
with zipfile.ZipFile(root/'blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip') as z:
 assert set(z.namelist())=={'blender_manifest.toml','__init__.py','heightmap_analysis.py','test_output.py','README.txt'}
 for name in z.namelist():assert z.read(name)==(addon/name).read_bytes(), 'Stale bundled add-on source'
print('PASS: desktop DOM and bridge wiring; Front default with preserved rotation; extension identity, manifest and bundled Python source consistency.')
