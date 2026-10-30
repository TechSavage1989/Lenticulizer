"""Exercise actual add-on callbacks and project codec with Blender API doubles.
This does not replace a Blender viewport run.
"""
from pathlib import Path
from types import ModuleType,SimpleNamespace
import sys,importlib.util,json,hashlib,tempfile,copy
root=Path(__file__).resolve().parent.parent

def module(name):
 m=ModuleType(name);sys.modules[name]=m;return m
bpy=module('bpy');bpy.__path__=[]
bpy.utils=module('bpy.utils');bpy.utils.__path__=[];bpy.utils.previews=module('bpy.utils.previews')
bpy.props=module('bpy.props');bpy.types=module('bpy.types')
class Collection(list):
 def add(self):
  item=SimpleNamespace(path='',display_name='');self.append(item);return item
for name in ['Operator','Panel','PropertyGroup','UIList','FileHandler','OperatorFileListElement']:
 setattr(bpy.types,name,type(name,(),{}))
def prop(**kw):
 if 'default' in kw:return kw['default']
 if 'items' in kw and not callable(kw['items']):return kw['items'][0][0]
 return 0.0
for name in ['BoolProperty','EnumProperty','FloatProperty','IntProperty','PointerProperty','StringProperty']:
 setattr(bpy.props,name,prop)
bpy.props.CollectionProperty=lambda **kw:Collection()
bpy_extras=module('bpy_extras');bpy_extras.__path__=[]
io=module('bpy_extras.io_utils');io.ExportHelper=type('ExportHelper',(),{});io.ImportHelper=type('ImportHelper',(),{})
v=module('bpy_extras.view3d_utils');v.location_3d_to_region_2d=lambda *args:None
mathutils=module('mathutils');mathutils.Vector=lambda x:x;mathutils.Matrix=lambda x:x
bpy.app=SimpleNamespace(version=(5,0,0),handlers=SimpleNamespace(persistent=lambda fn:fn))
bpy.path=SimpleNamespace(abspath=lambda p:p)
bpy.data=SimpleNamespace(filepath='',images=SimpleNamespace(),collections=SimpleNamespace(get=lambda name:None),objects=SimpleNamespace(get=lambda name:None))
path=root/'blender/Lenticulizer_Blender_Addon_v1.18.43/__init__.py'
spec=importlib.util.spec_from_file_location('lenticulizer_test_addon',path,submodule_search_locations=[str(path.parent)])
a=importlib.util.module_from_spec(spec);sys.modules[spec.name]=a;spec.loader.exec_module(a)
settings=SimpleNamespace(**copy.deepcopy(a.LenticularSyncSettings.__annotations__))
settings.source_frames=Collection();settings.source_frame_index=0
bpy.context=SimpleNamespace(scene=SimpleNamespace(lenticular_sync=settings))
checks=0
def check(v,message):
 global checks
 checks+=1
 assert v,message
folder=root/'validation/heightmap-fixtures'
fixture=folder/'Horizontal_39_0_triangle.png'
with tempfile.TemporaryDirectory() as temp:
 settings.project_file=str(Path(temp)/'project.json')
 settings.reference_heightmap_path=str(fixture)
 settings.reference_heightmap_width_mm=80.0;settings.reference_heightmap_height_mm=50.0;settings.reference_heightmap_thickness_mm=2.0
 settings.reference_heightmap_detection='Automatic';settings.reference_heightmap_display_style='TINTED'
 settings.workflow='HEIGHTMAP'
 for i in range(3):settings.source_frames.add().path=str(fixture)
 info=a._analyze_reference_heightmap(settings)
 a._apply_imported_heightmap_settings(settings)
 check(settings.orientation=='HORIZONTAL','detected orientation drives project')
 check(settings.views==3 and settings.width_mm==80 and settings.height_mm==50,'source count and physical dimensions')
 check(abs(settings.lpi-997*25.4/(50*39))<1e-6,'LPI derived from actual map axis')
 check(abs(settings.thickness_mm-info['maximum']*2)<1e-10,'height scale applied once')
 check(abs(settings.base_mm-info['minimum']*2)<1e-10,'heightmap valley retained')
 samples=a._surface_from_settings(settings)
 raw=a.heightmap_tools.read_png(fixture)
 check(samples==list(raw[1][::-1]),'horizontal Blender mesh reverses raw top-down row order once')
 settings.reference_heightmap_show=True
 a._state['dirty_scope']='reference'
 project=a._current_project_dict(settings)
 check(project['settings']['workflow']=='Build from heightmap','shared workflow label')
 check(project['settings']['reference_heightmap_orientation']=='Horizontal','shared orientation format')
 check(project['assets']['reference_heightmap']==str(fixture),'shared reference asset')
 check(project['settings']['reference_heightmap_show'] is True,'shared reference visibility')
 check(project['reference_heightmap_info']==info,'shared detected samples and phase')
 settings.reference_heightmap_path='';settings.reference_heightmap_show=False;settings.reference_heightmap_display_style='OPAQUE'
 a._apply_project_to_settings(settings,project)
 check(settings.workflow=='HEIGHTMAP' and settings.reference_heightmap_path==str(fixture),'pull restores workflow and asset')
 check(settings.reference_heightmap_show and settings.reference_heightmap_display_style=='TINTED','pull restores preview style')
 check(settings.orientation=='HORIZONTAL' and abs(settings.base_mm-info['minimum']*2)<1e-6,'automatic pull does not replace imported geometry')
 # Style changes must sync without requesting production or moving viewports.
 a._apply_reference_display_style=lambda settings:None
 for flag in ['pending_interlace','pending_heightmap','pending_lens','pending_texture','app_rebuild_pair_requested','app_rebuild_heightmap_requested']:a._state[flag]=False
 a._update_reference_display_style(settings,bpy.context)
 check(a._state['dirty_scope']=='reference','style callback syncs reference scope')
 check(not any(a._state[f] for f in ['pending_interlace','pending_heightmap','pending_lens','pending_texture']),'style does not queue generation')
 # Geometry changes request both assets.
 settings.reference_heightmap_width_mm=72
 a._reference_heightmap_changed(settings,bpy.context)
 check(a._state['pending_interlace'] and a._state['pending_heightmap'],'heightmap setting queues complete pair')
 check(a._state['app_rebuild_pair_requested'],'Blender requests app regeneration')
 before=hashlib.sha256(fixture.read_bytes()).hexdigest()
 output=a._generate_heightmap_file(settings,Path(temp)/'copied.png')
 check(hashlib.sha256(fixture.read_bytes()).hexdigest()==before,'export preserves original bytes')
 copied=a.heightmap_tools.read_png(output)
 check(list(copied[0])==list(raw[0]) and list(copied[1])==list(raw[1]),'export preserves exact height samples')
 check(abs(copied[4]['scale_mm']-2)<1e-9,'export includes white-level scale')
 try:a._generate_heightmap_file(settings,fixture);raise AssertionError('original overwritten')
 except ValueError:pass
 check(hashlib.sha256(fixture.read_bytes()).hexdigest()==before,'same-file export is blocked')
 # Manual calibration remains authoritative and syncs both ways.
 settings.reference_heightmap_detection='Manual';settings.reference_heightmap_pitch_px=40.125;settings.reference_heightmap_phase_pitch=.19
 a._analyze_reference_heightmap(settings)
 check(settings.reference_heightmap_pitch_px==40.125 and settings.reference_heightmap_phase_pitch==.19,'manual detection survives analysis refresh')
 check(len(settings.source_frames)==3,'preview and analysis preserve source order')
# Exercise the real Blender raster builder, including bottom-up buffer serialization.
import numpy as np
from PIL import Image
class Pixels:
 def __init__(self,data):self.data=np.array(data,dtype=np.float32).ravel()
 def foreach_get(self,dst):dst[:]=self.data
 def foreach_set(self,src):self.data=np.array(src,dtype=np.float32)
class FakeImage:
 def __init__(self,w,h,rgba):self.size=(w,h);self.pixels=Pixels(np.tile(rgba,(w*h,1)));self.filepath_raw='';self.file_format='PNG'
 def save(self):pass  # The actual add-on's PNG writer immediately replaces this file.
class Images(dict):
 def load(self,path,check_existing=True):return self[str(path)]
 def new(self,name,width,height,**kw):
  image=FakeImage(width,height,[0,0,0,1]);self[name]=image;return image
 def remove(self,image):
  for key in list(self):
   if self[key] is image:del self[key]
images=Images();bpy.data.images=images
check(a._crop_rect_for_aspect(800,800,1600,1000)==(0.0,150.0,800.0,500.0),'physical aspect crop preserves artwork shape')
with tempfile.TemporaryDirectory() as temp:
 settings.project_file=str(Path(temp)/'project.json');settings.source_frames.clear()
 colors=[(1,0,0,1),(1,1,0,1),(0,0,1,1)]
 for i,color in enumerate(colors):
  path=Path(temp)/f'frame{i}.png';Image.new('RGB',(8,8),tuple(int(v*255) for v in color[:3])).save(path)
  images[str(path)]=FakeImage(8,8,color);settings.source_frames.add().path=str(path)
 for direction in ['Vertical','Horizontal']:
  path=folder/f'{direction}_39_0_triangle.png'
  settings.reference_heightmap_path=str(path);settings.reference_heightmap_detection='Automatic';settings.workflow='HEIGHTMAP';settings.phase_pitch=0
  info=a._analyze_reference_heightmap(settings);a._apply_imported_heightmap_settings(settings)
  result,w,h,pitch=a._build_interlaced_image(settings)
  output=np.array(Image.open(result))
  expected=a.heightmap_tools.stripe_indices(w if direction=='Vertical' else h,settings.reference_heightmap_pitch_px,settings.reference_heightmap_phase_pitch,3)
  actual=output[h//2,:,:] if direction=='Vertical' else output[:,w//2,:]
  colorbytes=np.array(colors)*255
  check(np.array_equal(actual,colorbytes[expected]),f'{direction}: actual PNG rows match detected registration and source order')
  check((w,h)==(info['width_px'],info['height_px']),f'{direction}: no imported raster resizing')
  before=hashlib.sha256(path.read_bytes()).hexdigest()
  generated=a._generate_working_heightmap(settings)
  check(generated!=path and hashlib.sha256(path.read_bytes()).hexdigest()==before,f'{direction}: paired output preserves import')
  check(a.heightmap_tools.read_png(generated)[2:4]==(w,h),f'{direction}: generated pair dimensions match')
print(f'PASS: {checks} actual Blender add-on callback, project round-trip, geometry, export and file-preservation checks using API doubles. Blender viewport execution remains a Windows/Blender check.')
