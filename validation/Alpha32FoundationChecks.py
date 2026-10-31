from pathlib import Path
from html.parser import HTMLParser
import ast, hashlib, json, re, tomllib, zipfile

root=Path(__file__).resolve().parent.parent

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

# Identity/version/resources.
program=(root/'app/Program.cs').read_text(encoding='utf-8')
assert '3.0.0-alpha.33' in program
csproj=(root/'Lenticulizer.csproj').read_text(encoding='utf-8')
assert 'Lenticulizer_3D_Blender_Addon_v1.18.43.zip' in csproj
assert 'ui/src/test-output.js' in csproj
assert '<RuntimeFrameworkVersion>10.0.11</RuntimeFrameworkVersion>' in csproj
assert json.loads((root/'global.json').read_text())['sdk']['version']=='10.0.400'

# Exact last user-supplied Blender baseline and current add-on.
baseline=root/'backend/Lenticular-Builder.blend'
assert sha(baseline)=='54154ce98dae6b232ef486886ecdaf61f5370510abe9c247ad712d002ca99897'
addon_zip=root/'blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip'
assert sha(addon_zip)=='975854f306081f4f374acd02b361bc3130b8c349bdfa685b343246bfe775fdd0'
addon=root/'blender/Lenticulizer_Blender_Addon_v1.18.43'
manifest=tomllib.loads((addon/'blender_manifest.toml').read_text())
assert manifest['version']=='1.18.43' and manifest['id']=='lenticular_blender_sync'
for p in addon.glob('*.py'): ast.parse(p.read_text(encoding='utf-8'))
with zipfile.ZipFile(addon_zip) as z:
    expected={'README.txt','__init__.py','blender_manifest.toml','heightmap_analysis.py','test_output.py'}
    assert set(z.namelist())==expected
    for name in expected: assert z.read(name)==(addon/name).read_bytes()

# Runtime tests must verify the same current add-on embedded in the desktop app.
runtime_tests=(root/'validation/RuntimeTests/RuntimeTests.cs').read_text(encoding='utf-8')
assert 'blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip' in runtime_tests
assert 'blender/Lenticulizer_Blender_Addon_v1.18.38.zip' not in runtime_tests
assert 'blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip' in [item['path'] for item in json.loads((root/'vendor/FixedRuntime/manifest.json').read_text(encoding='utf-8'))['files']]

# Alpha 28 backing contract reconstruction: zero is a valid disabled effective value,
# remembered thickness remains separate, and portable Blender omits the support object at zero.
rules=(root/'backend/Core/SettingsRules.cs').read_text(encoding='utf-8')
assert 'backing >= 0' in rules and 'backing > 0' not in rules[rules.find('backing >= 0')-100:rules.find('backing >= 0')+100]
blender_script=(root/'backend/Core/BlenderScript.cs').read_text(encoding='utf-8')
assert 'if backing_m > 0:' in blender_script
default=json.loads((root/'app/default-project.json').read_text())
assert default['settings']['backing_enabled'] is True
assert default['settings']['backing_saved_mm']>0

# Preserved Alpha 29/31 interface contracts.
html=(root/'ui/src/index.html').read_text(encoding='utf-8')
class DOM(HTMLParser):
    def __init__(self): super().__init__(); self.ids=[]
    def handle_starttag(self,tag,attrs): self.ids += [v for k,v in attrs if k=='id']
d=DOM(); d.feed(html)
assert len(d.ids)==len(set(d.ids))
for id_ in ['compactNavButton','togglePreviewButton','sourceThumbSize','manualThicknessField','manualBaseField','customAngleField','backingThicknessField','backingEnabled','imagesViewOutputButton','opticsViewOutputButton','opticsGeneratePairButton','testOutputName','exportTestSetButton']:
    assert id_ in d.ids,id_
renderer=(root/'ui/src/renderer.js').read_text(encoding='utf-8')
for text in ['lenticulizer.navCompact','lenticulizer.previewHidden','lenticulizer.sourceThumbSize','exportLabeledTestSet','showSaveFilePicker','backing_saved_mm','isNumericInput']:
    assert text in renderer,text
assert "connect-src 'self'" in html
assert '<script src="test-output.js"></script>' in html

# Preserved Alpha 31 download path: browser-generated ZIPs are allowed, while app navigation/new windows stay blocked.
window=(root/'app/AppWindow.cs').read_text(encoding='utf-8')
assert 'core.DownloadStarting' in window and 'e.Handled = false' in window
assert 'NavigationStarting' in window and 'e.Cancel = true' in window
assert 'NewWindowRequested' in window and 'e.Handled = true' in window

# Fixed runtime: same exact current baseline/add-on payload and internally consistent manifest.
runtime=root/'vendor/FixedRuntime/runtime.zip'; rm=json.loads((root/'vendor/FixedRuntime/manifest.json').read_text())
assert sha(runtime)==rm['archive_sha256'] and runtime.stat().st_size==rm['archive_bytes']
with zipfile.ZipFile(runtime) as z:
    assert len([i for i in z.infolist() if not i.is_dir()])==len(rm['files'])==557
    assert z.read('Lenticular-Builder.blend')==baseline.read_bytes()
    assert z.read('blender/Lenticulizer_3D_Blender_Addon_v1.18.43.zip')==addon_zip.read_bytes()
    assert not any('v1.18.38' in n or 'v1.18.39' in n for n in z.namelist())

# Current, non-historical build/test scripts must target the current add-on.
for rel in ['packaging/pack_runtime.py','validation/DesktopHeightmapContractChecks.py','validation/HeightmapFixtures.py','validation/BlenderHeightmapChecks.py']:
    t=(root/rel).read_text(encoding='utf-8')
    assert '1.18.39' not in t and '1.18.43' in t,rel

print('PASS: Alpha 32 foundation preserves the Alpha 31 behavior/resources while using the current version identity and fixed runtime.')
