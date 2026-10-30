"""Linear grayscale heightmap analysis. No Blender state or color management."""
import math
import struct
import zlib
from pathlib import Path
import numpy as np


def detect_period(full, coarse=False):
    full = np.asarray(full, dtype=np.float64)
    step = max(1, math.ceil(len(full) / 4096)) if coarse else 1
    a = np.array([full[i:i + step].mean() for i in range(0, min(len(full),4096*step), step)])
    a -= a.mean()
    n = len(a)
    limit = min(n // 3, 2048)
    if limit < 4:
        return 0.0, 0.0, 0.0
    square = np.concatenate(([0.0], np.cumsum(a * a)))
    corr = np.zeros(limit + 1)
    for lag in range(1, limit + 1):
        corr[lag] = np.dot(a[:-lag], a[lag:]) / max(1e-20, math.sqrt(max(0, square[n-lag] * (square[n]-square[lag]))))
    peaks = [k for k in range(3, limit) if corr[k] >= corr[k-1] and corr[k] > corr[k+1]]
    best = max((corr[k] for k in peaks), default=0)
    chosen = next((k for k in peaks if corr[k] >= max(.86, best-.045)), 0)
    if not chosen:
        return detect_period(full, True) if not coarse and len(full)>4096 else (0.0,0.0,0.0)
    denom = corr[chosen-1] - 2*corr[chosen] + corr[chosen+1]
    pitch = (chosen + (.5*(corr[chosen-1]-corr[chosen+1])/denom if abs(denom)>1e-12 else 0))*step
    lo, hi = float(full.min()), float(full.max())
    centers, heights = [], []
    i = 1
    while i < len(full)-1:
        if full[i] < lo+.85*(hi-lo) or full[i] <= full[i-1]:
            i += 1
            continue
        end = i
        while end+1 < len(full) and abs(full[end+1]-full[i]) < 1e-12:
            end += 1
        if end >= len(full)-1 or full[end] <= full[end+1]:
            i += 1
            continue
        center = (i+end)*.5
        if end == i:
            d = full[i-1]-2*full[i]+full[i+1]
            if abs(d) > 1e-12:
                center += float(np.clip(.5*(full[i-1]-full[i+1])/d, -.5, .5))
        if centers and center-centers[-1] < pitch*.55:
            if full[i] > heights[-1]:
                centers[-1], heights[-1] = center, float(full[i])
        else:
            centers.append(center)
            heights.append(float(full[i]))
        i = end+1
    if len(centers) < 3:
        return pitch, 0.0, 0.0
    ids = np.concatenate(([0.0],np.cumsum(np.rint(np.diff(centers)/pitch))))
    sx, sy, sxx, sxy = ids.sum(), sum(centers), (ids*ids).sum(), np.dot(ids, centers)
    count = len(centers)
    div = count*sxx-sx*sx
    if div <= 0:
        return pitch, 0.0, 0.0
    fitted = (count*sxy-sx*sy)/div
    origin = (sy-fitted*sx)/count
    if abs(fitted-pitch) > pitch*.12:
        return pitch, 0.0, 0.0
    error = np.square(np.array(centers)-(origin+ids*fitted)).mean()
    confidence = float(np.clip(corr[chosen]*(1-math.sqrt(error)/max(1, fitted)*5), 0, 1))
    phase = ((1-origin/fitted) % 1)-.5
    return float(fitted), float(phase), confidence


def analyze_axes(x, y, width, height, metadata=None, grayscale=True, bit_depth=16, minimum=None, maximum=None):
    x, y = np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64)
    vx, vy = float(np.var(x)), float(np.var(y))
    vx = 0.0 if vx < 1e-14 else vx
    vy = 0.0 if vy < 1e-14 else vy
    vertical = vx >= vy
    ratio = max(vx, vy) / max(1e-14, min(vx, vy))
    pitch, phase, confidence = detect_period(x if vertical else y)
    lo = min(float(x.min()), float(y.min())) if minimum is None else minimum
    hi = max(float(x.max()), float(y.max())) if maximum is None else maximum
    ok = bool(grayscale and hi-lo > .0001 and ratio >= 9 and pitch >= 3 and confidence >= .80)
    message = ('Detected repeating lens profiles. Verify physical size and white-level height before printing.' if ok else
               'The image contains color. Import a grayscale lens heightmap.' if not grayscale else
               'The heightmap is flat. Lens spacing cannot be detected.' if hi-lo <= .0001 else
               'Both axes vary. Automatic lens direction is ambiguous; choose Manual and verify direction, pitch and registration.' if ratio < 9 else
               'A reliable repeating lens profile was not found. Choose Manual and verify direction, pitch and registration.')
    def preview(a):
        return a[np.rint(np.linspace(0, len(a)-1, min(8192,len(a)))).astype(int)].tolist()
    result = dict(algorithm='lens-profile-v1', ok=ok, width_px=int(width), height_px=int(height), bit_depth=int(bit_depth),
                  width_mm=0.0, height_mm=0.0, scale_mm=0.0, minimum=float(lo), maximum=float(hi),
                  orientation='Vertical' if vertical else 'Horizontal', pitch_px=pitch, phase_pitch=phase,
                  confidence=confidence if ok else min(.49,confidence), message=message,
                  profile_x=preview(x), profile_y=preview(y), grayscale=bool(grayscale))
    result.update(metadata or {})
    return result


def png_chunks(path):
    with open(path, 'rb') as f:
        if f.read(8) != b'\x89PNG\r\n\x1a\n':
            raise ValueError('Invalid PNG signature')
        while True:
            head = f.read(8)
            if len(head) != 8:
                raise ValueError('Truncated PNG')
            size, name = struct.unpack('>I4s', head)
            if size > 268435456:
                raise ValueError('PNG chunk is too large')
            data, crc = f.read(size), f.read(4)
            if len(data) != size or len(crc) != 4:
                raise ValueError('Truncated PNG chunk')
            yield name, data
            if name == b'IEND':
                break


def read_png(path):
    """Return exact center axes plus range/metadata, ignoring display gamma."""
    width = height = depth = color = 0
    packed = bytearray()
    metadata = {}
    palette = None
    for name, data in png_chunks(path):
        if name == b'IHDR':
            width,height,depth,color,comp,filt,interlace = struct.unpack('>IIBBBBB',data)
            if width < 2 or height < 2 or width > 100000 or height > 100000 or width*height > 100000000:
                raise ValueError('Heightmaps must have 2 or more pixels per side and at most 100 million pixels')
            if interlace or comp or filt:
                raise NotImplementedError('This PNG needs Blender image decoding')
        elif name == b'IDAT':
            packed.extend(data)
        elif name == b'pHYs' and len(data) == 9:
            px,py,unit = struct.unpack('>IIB',data)
            if unit == 1 and px and py:
                metadata.update(width_mm=width*1000/px,height_mm=height*1000/py)
        elif name == b'tEXt' and data.startswith(b'LenticulizerHeightScaleMm\0'):
            try: metadata['scale_mm'] = float(data.split(b'\0',1)[1])
            except ValueError: pass
        elif name == b'PLTE':
            palette = np.frombuffer(data,dtype=np.uint8).reshape(-1,3)
    channels = {0:1,2:3,3:1,4:2,6:4}.get(color,0)
    if not channels or depth not in (1,2,4,8,16) or (depth < 8 and color not in (0,3)):
        raise NotImplementedError('Unsupported PNG heightmap format')
    bpp, stride = max(1,channels*depth//8), (width*channels*depth+7)//8
    raw = zlib.decompress(packed)
    if len(raw) != (stride+1)*height:
        raise ValueError('Incorrect PNG data length')
    x_axis = y_axis = None
    y_axis = np.zeros(height)
    previous = np.zeros(stride,dtype=np.uint8)
    low,high,grayscale = 1.0,0.0,True
    for y in range(height):
        start = y*(stride+1)
        row = np.frombuffer(raw,dtype=np.uint8,count=stride,offset=start+1).copy()
        kind = raw[start]
        if kind == 1:
            for c in range(bpp): row[c::bpp] = np.cumsum(row[c::bpp],dtype=np.uint64).astype(np.uint8)
        elif kind == 2:
            row = np.add(row,previous,dtype=np.uint8)
        elif kind in (3,4):
            for i in range(stride):
                a,b,c = int(row[i-bpp]) if i>=bpp else 0,int(previous[i]),int(previous[i-bpp]) if i>=bpp else 0
                if kind == 3: predict = (a+b)//2
                else:
                    p=a+b-c; pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                    predict = a if pa<=pb and pa<=pc else b if pb<=pc else c
                row[i] = (int(row[i])+predict)&255
        elif kind != 0:
            raise ValueError('Invalid PNG filter')
        if depth < 8:
            values = np.array([(int(row[i*depth//8]) >> (8-depth-i*depth%8)) & ((1<<depth)-1) for i in range(width)])
            if color == 3:
                rgb=palette[values]; values=rgb[:,0]/255.0
                grayscale &= bool(np.all(rgb[:,0]==rgb[:,1]) and np.all(rgb[:,0]==rgb[:,2]))
            else: values=values/((1<<depth)-1)
        elif color == 3:
            rgb=palette[row];values=rgb[:,0]/255.0
            grayscale &= bool(np.all(rgb[:,0]==rgb[:,1]) and np.all(rgb[:,0]==rgb[:,2]))
        else:
            samples=np.frombuffer(row.tobytes(),dtype='>u2' if depth==16 else np.uint8).reshape(width,channels).astype(np.float64)/((1<<depth)-1)
            values=samples[:,0]
            if color in (2,6): grayscale &= bool(np.max(np.abs(samples[:,:3]-values[:,None]))<=1/255)
        low, high = min(low,float(values.min())),max(high,float(values.max()))
        if y==height//2: x_axis=values.copy()
        y_axis[y]=values[width//2]
        previous=row
    return x_axis,y_axis,width,height,metadata,grayscale,depth,low,high


def analyze_png(path):
    return analyze_axes(*read_png(path))


def write_chunk(f, name, data):
    f.write(struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff))


def copy_heightmap(source, destination, width_mm, height_mm, scale_mm):
    """Preserve sample bytes. Only annotate the output copy, never the source."""
    source,destination = Path(source),Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('The imported heightmap cannot be overwritten')
    if source.suffix.lower() != '.png':
        import shutil
        shutil.copyfile(source,destination)
        annotate_tiff(destination,width_mm,height_mm,scale_mm)
        return destination
    chunks=list(png_chunks(source))
    w,h=struct.unpack('>II',next(data for name,data in chunks if name==b'IHDR')[:8])
    with destination.open('wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        for name,data in chunks:
            if name == b'pHYs' or (name==b'tEXt' and data.startswith(b'LenticulizerHeightScaleMm\0')):
                continue
            write_chunk(f,name,data)
            if name == b'IHDR':
                write_chunk(f,b'pHYs',struct.pack('>IIB',round(w*1000/width_mm),round(h*1000/height_mm),1))
                write_chunk(f,b'tEXt',b'LenticulizerHeightScaleMm\0'+format(scale_mm,'.6f').encode('ascii'))
    return destination


def stripe_indices(count, pitch, phase, views, relief=False, bottom_up=False):
    axis=np.arange(count,dtype=np.float64)
    if bottom_up: axis=count-1-axis
    stripe=np.floor(np.mod(axis/pitch+phase,1)*views+1e-7).astype(np.int32)
    stripe=np.clip(stripe,0,views-1)
    return stripe if relief else views-1-stripe


def tiff_size_metadata(path):
    """Read explicit TIFF resolution tags; never assume a default DPI."""
    result = {}
    try:
        with open(path,'rb') as f:
            order=f.read(2)
            if order not in (b'II',b'MM'): return result
            e='<' if order==b'II' else '>'
            if struct.unpack(e+'H',f.read(2))[0]!=42: return result
            offset=struct.unpack(e+'I',f.read(4))[0]
            f.seek(offset); count=struct.unpack(e+'H',f.read(2))[0]
            tags={}
            for i in range(min(count,4096)):
                entry=f.read(12)
                if len(entry)!=12:break
                tag,kind,n,value=struct.unpack(e+'HHII',entry)
                if tag==258 and kind==3 and 1<=n<=8:
                    here=f.tell()
                    if n*2<=4:data=entry[8:8+n*2]
                    else:f.seek(value);data=f.read(n*2)
                    f.seek(here)
                    result['bit_depth']=max(struct.unpack(e+'H'*n,data))
                if tag==270 and kind==2 and n<=1048576:
                    here=f.tell()
                    if n<=4:data=entry[8:8+n]
                    else:f.seek(value);data=f.read(n)
                    f.seek(here)
                    for line in data.rstrip(b'\0').decode('utf-8',errors='replace').split('\n'):
                        if line.startswith('LenticulizerHeightScaleMm='):
                            try:result['scale_mm']=float(line.split('=',1)[1])
                            except ValueError:pass
                if n!=1: continue
                if kind==3: tags[tag]=struct.unpack(e+'H',entry[8:10])[0]
                elif kind==4:tags[tag]=value
                elif kind==5:
                    here=f.tell();f.seek(value);a,b=struct.unpack(e+'II',f.read(8));f.seek(here)
                    if b:tags[tag]=a/b
            unit=tags.get(296,2)
            if tags.get(282,0)>0 and tags.get(283,0)>0 and tags.get(256,0)>0 and tags.get(257,0)>0 and unit in (2,3):
                mm=25.4 if unit==2 else 10.0
                result.update(width_mm=tags[256]*mm/tags[282],height_mm=tags[257]*mm/tags[283])
    except (OSError,ValueError,struct.error):
        pass
    return result


def annotate_tiff(path, width_mm, height_mm, scale_mm):
    """Append a first IFD, preserving original pixel strips and tile offsets."""
    with open(path,'r+b') as f:
        head=f.read(8)
        if head[:2] not in (b'II',b'MM'):raise ValueError('Invalid TIFF byte order')
        e='<' if head[:2]==b'II' else '>'
        if struct.unpack(e+'H',head[2:4])[0]!=42:
            raise ValueError('Convert BigTIFF to a standard TIFF or grayscale PNG before building')
        f.seek(struct.unpack(e+'I',head[4:])[0]);count=struct.unpack(e+'H',f.read(2))[0]
        if count>4096:raise ValueError('Invalid TIFF directory size')
        entries=[];description='';dims={}
        for i in range(count):
            entry=f.read(12);tag,kind,n,value=struct.unpack(e+'HHII',entry)
            if tag in (256,257) and n==1:
                dims[tag]=struct.unpack(e+'H',entry[8:10])[0] if kind==3 else value
            if tag==270 and kind==2:
                here=f.tell()
                if n>1048576:raise ValueError('TIFF description is too large')
                if n<=4:data=entry[8:8+n]
                else:f.seek(value);data=f.read(n)
                description=data.rstrip(b'\0').decode('utf-8',errors='replace');f.seek(here)
            elif tag not in (282,283,296):entries.append(entry)
        next_ifd=f.read(4)
        if len(next_ifd)!=4 or not dims.get(256) or not dims.get(257):raise ValueError('Invalid TIFF dimensions')
        description='\n'.join(line for line in description.split('\n') if not line.startswith('LenticulizerHeightScaleMm=')).rstrip()
        description+= ('\n' if description else '')+f'LenticulizerHeightScaleMm={scale_mm:.6f}\0'
        def align():
            if f.tell()%2:f.write(b'\0')
        f.seek(0,2);align()
        def rational(value):
            offset=f.tell();den=min(1000000,max(1,math.floor(0xffffffff/max(value,1))))
            f.write(struct.pack(e+'II',round(value*den),den));return offset
        x,y=rational(dims[256]*25.4/width_mm),rational(dims[257]*25.4/height_mm)
        desc=f.tell();data=description.encode('utf-8');f.write(data);align();replacement=f.tell()
        entries.extend([struct.pack(e+'HHII',282,5,1,x),struct.pack(e+'HHII',283,5,1,y),struct.pack(e+'HHI',296,3,1)+struct.pack(e+'H',2)+b'\0\0',struct.pack(e+'HHII',270,2,len(data),desc)])
        entries.sort(key=lambda entry:struct.unpack(e+'H',entry[:2])[0])
        f.write(struct.pack(e+'H',len(entries))+b''.join(entries)+next_ifd)
        f.seek(4);f.write(struct.pack(e+'I',replacement));f.flush()


def png_size_metadata(path):
    result={};w=h=0
    for name,data in png_chunks(path):
        if name==b'IHDR':w,h=struct.unpack('>II',data[:8]);result['bit_depth']=data[8]
        elif name==b'pHYs' and len(data)==9:
            x,y,unit=struct.unpack('>IIB',data)
            if unit==1 and x and y:result.update(width_mm=w*1000/x,height_mm=h*1000/y)
        elif name==b'tEXt' and data.startswith(b'LenticulizerHeightScaleMm\0'):
            try:result['scale_mm']=float(data.split(b'\0',1)[1])
            except ValueError:pass
    return result
