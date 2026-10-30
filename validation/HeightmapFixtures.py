"""Cross-language fixtures, PNG filter coverage and immutable source checks."""
from pathlib import Path
import sys,importlib.util,json,zlib,struct,hashlib
import numpy as np
root=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('heightmap_tools',root/'blender/Lenticulizer_Blender_Addon_v1.18.43/heightmap_analysis.py')
hm=importlib.util.module_from_spec(spec);spec.loader.exec_module(hm)
folder=root/'validation/heightmap-fixtures';folder.mkdir(exist_ok=True)
cases=[]
def png(path,values,depth=16,physical=True,filter_mode=0,rgb=False):
 h,w=values.shape
 raw=bytearray();previous=None;bpp=(2 if depth==16 else 1)*(3 if rgb else 1)
 for row in values:
  a=np.repeat(row[:,None],3,axis=1) if rgb else row
  line=np.rint(a*((1<<depth)-1)).astype('>u2' if depth==16 else np.uint8).tobytes()
  previous=bytes(len(line)) if previous is None else previous
  filtered=bytearray(len(line))
  for i,v in enumerate(line):
   a=line[i-bpp] if i>=bpp else 0;b=previous[i];c=previous[i-bpp] if i>=bpp else 0
   p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
   pred=[0,a,b,(a+b)//2,a if pa<=pb and pa<=pc else b if pb<=pc else c][filter_mode]
   filtered[i]=(v-pred)&255
  raw.append(filter_mode);raw.extend(filtered);previous=line
 with path.open('wb') as f:
  f.write(b'\x89PNG\r\n\x1a\n')
  hm.write_chunk(f,b'IHDR',struct.pack('>IIBBBBB',w,h,depth,2 if rgb else 0,0,0,0))
  if physical:
   hm.write_chunk(f,b'pHYs',struct.pack('>IIB',10000,10000,1))
   hm.write_chunk(f,b'tEXt',b'LenticulizerHeightScaleMm\0' + b'1.72')
  hm.write_chunk(f,b'IDAT',zlib.compress(raw));hm.write_chunk(f,b'IEND',b'')
for orientation in ('Vertical','Horizontal'):
 for pitch,phase,shape in [(8,0,'cosine'),(13,.123,'cosine'),(24,-.321,'triangle'),(39,0,'triangle'),(27.125,.173,'cosine'),(63.25,-.27,'cosine')]:
  count=997;t=(np.arange(count)/pitch+phase)%1
  profile=.2+.7*((.5-.5*np.cos(2*np.pi*t)) if shape=='cosine' else 1-abs(t*2-1))
  values=np.tile(profile,(41,1)) if orientation=='Vertical' else np.tile(profile[:,None],(1,41))
  path=folder/f'{orientation}_{pitch}_{phase}_{shape}.png';png(path,values)
  before=hashlib.sha256(path.read_bytes()).hexdigest();info=hm.analyze_png(path)
  assert info['ok'],(path,info)
  assert info['orientation']==orientation
  assert abs(info['pitch_px']-pitch)<.012,(path,info['pitch_px'])
  assert abs(((info['phase_pitch']-phase+.5)%1)-.5)<.015,(path,info['phase_pitch'])
  out=folder/('copy_'+path.name);hm.copy_heightmap(path,out,80,50,2.1)
  assert hashlib.sha256(path.read_bytes()).hexdigest()==before
  original_data=hm.read_png(path);copied_data=hm.read_png(out)
  assert np.array_equal(original_data[0],copied_data[0]) and np.array_equal(original_data[1],copied_data[1])
  assert abs(copied_data[4]['scale_mm']-2.1)<1e-9
  assert [data for name,data in hm.png_chunks(path) if name==b'IDAT']==[data for name,data in hm.png_chunks(out) if name==b'IDAT']
  # Verify automatic registration and all source counts with exact supplied calibration.
  stripe={}
  for views in (2,3,5,8):
   stripe[str(views)]=hm.stripe_indices(count,pitch,phase,views).tolist()
   assert np.array_equal(hm.stripe_indices(count,pitch,phase,views,bottom_up=True)[::-1],stripe[str(views)])
  cases.append(dict(file=path.name,expected=info,true_pitch=pitch,true_phase=phase,stripes=stripe,sha256=before))
# Wide production maps must not alias short pitches through downsampling.
for pitch in (8.25,13,24.5,39,2000):
 count=30001;phase=.137;t=np.arange(count)/pitch+phase
 profile=.2+.7*(.5-.5*np.cos(2*np.pi*t));values=np.tile(profile,(3,1))
 path=folder/f'wide_{pitch}.png';png(path,values)
 info=hm.analyze_png(path)
 assert info['ok'] and abs(info['pitch_px']-pitch)<.005,(path,info['pitch_px'],info['confidence'])
 assert abs(((info['phase_pitch']-phase+.5)%1)-.5)<.002
 cases.append(dict(file=path.name,expected=info))
# Exact raw values across PNG filters and bit depths, grayscale RGB included.
for depth in (8,16):
 for filt in range(5):
  phase=(np.arange(233)/19)%1;v=np.tile(.1+.8*(.5-.5*np.cos(2*np.pi*phase)),(27,1))
  path=folder/f'filter_{depth}_{filt}.png';png(path,v,depth=depth,filter_mode=filt,rgb=filt==4,physical=False)
  info=hm.analyze_png(path);assert info['ok'] and info['bit_depth']==depth
  assert np.array_equal(np.array(info['profile_x']),np.rint(v[13]*((1<<depth)-1))/((1<<depth)-1))
  cases.append(dict(file=path.name,expected=info))
for name,values in [('flat',np.ones((89,97))*.4),('grid',.5+.2*np.cos(np.arange(97)[None,:]*2*np.pi/17)+.2*np.cos(np.arange(89)[:,None]*2*np.pi/17)),('noise',np.random.default_rng(321).uniform(.1,.9,(89,97)))]:
 path=folder/(name+'.png');png(path,values,physical=False);info=hm.analyze_png(path);assert not info['ok'];cases.append(dict(file=path.name,expected=info))
# TIFF metadata edits preserve both endiannesses, samples and existing descriptions.
from PIL import Image, TiffImagePlugin
for order in ('little','big'):
 pixels=np.rint(np.tile(.2+.7*(.5-.5*np.cos(2*np.pi*np.arange(997)/39)),(17,1))*65535).astype('<u2' if order=='little' else '>u2')
 path=folder/f'tiff_{order}.tif';image=Image.fromarray(pixels)
 tags=TiffImagePlugin.ImageFileDirectory_v2();tags[270]='Existing description'
 image.save(path,dpi=(600,300),tiffinfo=tags)
 before=hashlib.sha256(path.read_bytes()).hexdigest();out=folder/f'tiff_{order}_copy.tif'
 hm.copy_heightmap(path,out,82,61,2.15)
 assert hashlib.sha256(path.read_bytes()).hexdigest()==before
 with Image.open(out) as result:
  assert np.array_equal(np.array(result),pixels)
  assert str(result.tag_v2[270]).startswith('Existing description')
 meta=hm.tiff_size_metadata(out)
 assert abs(meta['width_mm']-82)<1e-5 and abs(meta['height_mm']-61)<1e-5 and abs(meta['scale_mm']-2.15)<1e-9,meta
(folder/'cases.json').write_text(json.dumps(cases,separators=(',',':')))
print(f'PASS: {len(cases)} Python heightmap fixtures; pitch, phase, direction, filters, bit depths, metadata, stripe polarity, immutable source and unchanged compressed samples.')
