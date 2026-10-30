"""Optional labeled test exports. No project/source mutation or optical calculations.
The original filtered PNG scanlines are kept intact; only new bottom rows are added.
"""
from __future__ import annotations
import binascii, hashlib, json, math, os, re, struct, tempfile, unicodedata, zlib
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile, ZIP_STORED

MAX_RAW = 512 * 1024 * 1024
SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Original compact 5x7 glyph drawings used solely for test labels. No system font needed.
GLYPHS = {
' ':['00000']*7,
'A':['01110','10001','10001','11111','10001','10001','10001'],
'B':['11110','10001','10001','11110','10001','10001','11110'],
'C':['01111','10000','10000','10000','10000','10000','01111'],
'D':['11110','10001','10001','10001','10001','10001','11110'],
'E':['11111','10000','10000','11110','10000','10000','11111'],
'F':['11111','10000','10000','11110','10000','10000','10000'],
'G':['01111','10000','10000','10111','10001','10001','01111'],
'H':['10001','10001','10001','11111','10001','10001','10001'],
'I':['11111','00100','00100','00100','00100','00100','11111'],
'J':['00111','00010','00010','00010','10010','10010','01100'],
'K':['10001','10010','10100','11000','10100','10010','10001'],
'L':['10000','10000','10000','10000','10000','10000','11111'],
'M':['10001','11011','10101','10101','10001','10001','10001'],
'N':['10001','11001','10101','10011','10001','10001','10001'],
'O':['01110','10001','10001','10001','10001','10001','01110'],
'P':['11110','10001','10001','11110','10000','10000','10000'],
'Q':['01110','10001','10001','10001','10101','10010','01101'],
'R':['11110','10001','10001','11110','10100','10010','10001'],
'S':['01111','10000','10000','01110','00001','00001','11110'],
'T':['11111','00100','00100','00100','00100','00100','00100'],
'U':['10001','10001','10001','10001','10001','10001','01110'],
'V':['10001','10001','10001','10001','10001','01010','00100'],
'W':['10001','10001','10001','10101','10101','10101','01010'],
'X':['10001','10001','01010','00100','01010','10001','10001'],
'Y':['10001','10001','01010','00100','00100','00100','00100'],
'Z':['11111','00001','00010','00100','01000','10000','11111'],
'0':['01110','10001','10011','10101','11001','10001','01110'],
'1':['00100','01100','00100','00100','00100','00100','01110'],
'2':['01110','10001','00001','00010','00100','01000','11111'],
'3':['11110','00001','00001','01110','00001','00001','11110'],
'4':['00010','00110','01010','10010','11111','00010','00010'],
'5':['11111','10000','10000','11110','00001','00001','11110'],
'6':['01110','10000','10000','11110','10001','10001','01110'],
'7':['11111','00001','00010','00100','01000','01000','01000'],
'8':['01110','10001','10001','01110','10001','10001','01110'],
'9':['01110','10001','10001','01111','00001','00001','01110'],
'.':['00000','00000','00000','00000','00000','00110','00110'],
',':['00000','00000','00000','00000','00110','00110','00100'],
':':['00000','00110','00110','00000','00110','00110','00000'],
'-':['00000','00000','00000','11111','00000','00000','00000'],
'+':['00000','00100','00100','11111','00100','00100','00000'],
'/':['00001','00010','00010','00100','01000','01000','10000'],
'|':['00100']*7,
'(':['00010','00100','01000','01000','01000','00100','00010'],
')':['01000','00100','00010','00010','00010','00100','01000'],
'%':['11001','11010','00100','00100','01000','10110','00110'],
'_':['00000','00000','00000','00000','00000','00000','11111'],
'?':['01110','10001','00001','00010','00100','00000','00100'],
'=':['00000','00000','11111','00000','11111','00000','00000'],
'#':['01010','11111','01010','01010','11111','01010','00000'],
}

def _chunk(kind, value):
    return struct.pack('>I', len(value))+kind+value+struct.pack('>I', binascii.crc32(kind+value)&0xffffffff)

def read_png(data: bytes):
    if not data.startswith(SIGNATURE):
        raise ValueError('Export the current generated pair as PNG before making a labeled test set.')
    pos=8;chunks=[];idat=[];ihdr=None;ppm=None;ended=False
    while pos+12<=len(data):
        n=struct.unpack_from('>I',data,pos)[0];typ=data[pos+4:pos+8];pos+=8
        if n>len(data)-pos-4: raise ValueError('Incomplete PNG file.')
        value=data[pos:pos+n];crc=struct.unpack_from('>I',data,pos+n)[0];pos+=n+4
        if (binascii.crc32(typ+value)&0xffffffff)!=crc:raise ValueError('PNG checksum failed. Regenerate the pair and retry.')
        if typ==b'IHDR':
            if ihdr is not None or len(value)!=13:raise ValueError('Invalid PNG header.')
            ihdr=value
        elif typ==b'IDAT':idat.append(value)
        elif typ==b'pHYs' and len(value)==9 and value[8]==1:ppm=struct.unpack('>II',value[:8])
        elif typ==b'IEND':ended=True;break
        else:chunks.append((typ,value))
    if not ended or ihdr is None:raise ValueError('Incomplete PNG file.')
    w,h,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',ihdr)
    if not w or not h or depth not in (8,16) or color not in (0,2,4,6) or compression or filtering or interlace:
        raise ValueError('This test export needs a non-interlaced 8/16-bit PNG. Generate the output pair first.')
    if ppm and (ppm[0]<=0 or ppm[1]<=0):raise ValueError('Invalid PNG print resolution.')
    channels={0:1,2:3,4:2,6:4}[color];bpp=channels*(depth//8);row=w*bpp;expected=(row+1)*h
    if expected>MAX_RAW:raise ValueError('This image is too large for a labeled test export. Use a smaller test print.')
    inflater=zlib.decompressobj();filtered=inflater.decompress(b''.join(idat),expected+1)
    if len(filtered)!=expected or not inflater.eof or inflater.unused_data:raise ValueError('Invalid PNG image data.')
    if any(filtered[i*(row+1)]>4 for i in range(h)):raise ValueError('Invalid PNG filter.')
    return dict(w=w,h=h,depth=depth,color=color,bpp=bpp,row=row,filtered=filtered,chunks=chunks,ppm=ppm,sha256=hashlib.sha256(data).hexdigest())

def _value(s,k,fallback=None):
    v=s.get(k,fallback)
    try:
        v=float(v)
        return v if math.isfinite(v) else None
    except (ValueError,TypeError):return None

def _f(v,digits=3):
    if v is None:return 'N/A'
    return f'{float(v):.{digits}f}'.rstrip('0').rstrip('.') if digits else str(int(v))

def printable(value):
    value=unicodedata.normalize('NFKD',str(value)).encode('ascii','ignore').decode().upper()
    return ''.join(c if c in GLYPHS else '?' for c in value)

def _wrap(value, count):
    words=printable(value).split(); lines=[];line=''
    for word in words:
        if line and len(line)+len(word)+1>count:lines.append(line);line=''
        while len(word)>count:
            if line:lines.append(line);line=''
            lines.append(word[:count]);word=word[count:]
        if word:line=(line+' '+word).strip()
    if line:lines.append(line)
    return lines or ['']

def describe(settings, color, heightmap, name='', version='', created=None):
    if (color['w'],color['h'])!=(heightmap['w'],heightmap['h']):raise ValueError('The current image and heightmap have different pixel sizes. Regenerate both before exporting a test set.')
    a,b=color['ppm'],heightmap['ppm']
    if a and b and any(abs(x-y)>max(1,abs(x)*0.00001) for x,y in zip(a,b)):raise ValueError('The current pair has different print resolutions. Regenerate both before exporting a test set.')
    ppm=a or b
    if not ppm:
        wmm=_value(settings,'width_mm');hmm=_value(settings,'height_mm')
        if not wmm or not hmm or wmm<=0 or hmm<=0:raise ValueError('Set the physical print size before exporting a test set.')
        ppm=(max(1,round(color['w']*1000/wmm)),max(1,round(color['h']*1000/hmm)))
    dpi=(ppm[0]*.0254,ppm[1]*.0254);mm=(color['w']/ppm[0]*1000,color['h']/ppm[1]*1000)
    created=created or datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    name=' '.join(str(name).split())[:64]
    relief=str(settings.get('output_mode','')).upper() in ('LENS-FREE RELIEF','LENS_FREE_RELIEF','RELIEF')
    direction=str(settings.get('orientation','Vertical'))
    mode='LENS-FREE RELIEF' if relief else 'LENTICULAR LENS'
    backing=_value(settings,'backing_mm',0) or 0;enabled=settings.get('backing_enabled',backing>0) and backing>0
    raster=_f(dpi[0],2) if abs(dpi[0]-dpi[1])<.01 else f'{_f(dpi[0],2)} X {_f(dpi[1],2)}'
    lines=[f'TEST PRINT | {name or created}',
           f'{mode} | {direction} | {_f(_value(settings,"views"),0)} VIEWS',
           f'LPI {_f(_value(settings,"lpi"))} | PHASE {_f(_value(settings,"phase_pitch",0))} PITCH',
           f'PRINTER DPI {_f(_value(settings,"printer_dpi"),0)} | RASTER DPI {raster}',
           f'ACTIVE SIZE {_f(mm[0],2)} X {_f(mm[1],2)} MM']
    if str(settings.get('workflow','')).upper() in ('BUILD FROM HEIGHTMAP','HEIGHTMAP'):
        lines.append('IMPORTED HEIGHTMAP | HEIGHT SCALE '+_f(_value(settings,'reference_heightmap_thickness_mm'))+' MM')
        lines.append('REFERENCE PHASE '+_f(_value(settings,'reference_heightmap_phase_pitch',0))+' PITCH')
    elif relief:
        lines.append('PRISM HEIGHT '+_f(_value(settings,'relief_prism_height_mm',_value(settings,'thickness_mm')))+' MM')
    else:
        lines.append('IOR '+_f(_value(settings,'ior'))+' | ANGLE '+_f(_value(settings,'viewing_angle_deg'),1)+' DEG')
        lines.append('LENS '+_f(_value(settings,'thickness_mm'))+' MM | BASE '+_f(_value(settings,'base_mm'))+' MM')
        lines.append('PROFILE: '+str(settings.get('lens_profile','N/A')))
    lines.append('BACKING: '+(_f(backing)+' MM' if enabled else 'OFF'))
    lines.append(('LENTICULIZER '+version+' | '+(created if name else 'TEST COPY')))
    # Physical glyph cap height is approx. 2 mm; each label is independently
    # rasterized at X and Y resolution so non-square pixels do not stretch text.
    sx=max(1,math.floor(ppm[0]*.002/7+.5));sy=max(1,math.floor(ppm[1]*.002/7+.5))
    pad_x=max(2,math.floor(ppm[0]*.0015+.5));pad_y=max(2,math.floor(ppm[1]*.0015+.5))
    count=(color['w']-2*pad_x)//(6*sx)
    if count<12:raise ValueError('This print is too narrow for a readable settings footer. Use a test print at least about 25 mm wide.')
    wrapped=[part for ln in lines for part in _wrap(ln,count)]
    fh=2*pad_y+len(wrapped)*10*sy
    if (color['w']*(color['h']+fh)*max(color['bpp'],heightmap['bpp']))>MAX_RAW:raise ValueError('The labeled image is too large. Use a smaller test print.')
    return dict(schema=1,test_only=True,name=name,created_utc=created,software='Lenticulizer '+version,
                active_area_px=[0,0,color['w'],color['h']],active_size_mm=list(mm),
                canvas_size_px=[color['w'],color['h']+fh],canvas_size_mm=[mm[0],(color['h']+fh)/ppm[1]*1000],
                pixels_per_metre=list(ppm),raster_dpi=list(dpi),footer_height_px=fh,
                footer_height_mm=fh/ppm[1]*1000,label_lines=wrapped,
                glyph_scale=[sx,sy],padding=[pad_x,pad_y],settings=dict(settings),
                source_sha256=dict(interlaced=color['sha256'],heightmap=heightmap['sha256']),
                heightmap_bit_depth=heightmap['depth'],heightmap_footer='Zero height; no raised text',
                print_instruction='Print BOTH test images at the saved physical size / 100% scale, with the same top-left origin. Do not fit-to-page. Do not use the clean heightmap with the enlarged test image.')

def _footer_rows(image, plan, is_heightmap):
    w=image['w'];h=plan['footer_height_px'];bpp=image['bpp'];depth=image['depth'];channels={0:1,2:3,4:2,6:4}[image['color']]
    size=channels*(depth//8);black=bytearray(size)
    if image['color'] in (4,6):black[-depth//8:]=b'\xff'*(depth//8)
    white=b'\xff'*size; black=bytes(black)
    sx,sy=plan['glyph_scale'];padx,pady=plan['padding'];stride=w*bpp+1
    for y in range(h):
        row=bytearray(black*w if is_heightmap else white*w)
        if not is_heightmap:
            relative=y-pady;line=relative//(10*sy);gy=(relative%(10*sy))//sy
            if relative>=0 and 0<=line<len(plan['label_lines']) and gy<7:
                for ci,ch in enumerate(plan['label_lines'][line]):
                    glyph=GLYPHS.get(ch,GLYPHS['?'])[gy];x=padx+ci*6*sx
                    for gx,ink in enumerate(glyph):
                        if ink=='1':row[(x+gx*sx)*bpp:(x+(gx+1)*sx)*bpp]=black*sx
        yield b'\0'+row

def append_footer(image,plan,is_heightmap=False):
    total_h=image['h']+plan['footer_height_px'];compressor=zlib.compressobj(6)
    compressed=[compressor.compress(image['filtered'])]
    for row in _footer_rows(image,plan,is_heightmap):compressed.append(compressor.compress(row))
    compressed.append(compressor.flush());compressed=b''.join(compressed)
    output=[SIGNATURE,_chunk(b'IHDR',struct.pack('>IIBBBBB',image['w'],total_h,image['depth'],image['color'],0,0,0))]
    # Retain source colour/profile information and safe ancillary chunks. Do not
    # copy stale project-dimension metadata onto the new enlarged test canvas.
    for kind,value in image['chunks']:
        if kind in (b'iCCP',b'sRGB',b'gAMA',b'cHRM',b'sBIT',b'tRNS',b'bKGD') or (kind == b'tEXt' and value.startswith(b'LenticulizerHeightScaleMm\0')):output.append(_chunk(kind,value))
    output.append(_chunk(b'pHYs',struct.pack('>IIB',*plan['pixels_per_metre'],1)))
    summary={k:plan[k] for k in ('schema','test_only','active_area_px','canvas_size_px','canvas_size_mm','heightmap_footer')}
    output.append(_chunk(b'tEXt',b'LenticulizerTest\0'+json.dumps(summary,separators=(',',':')).encode('ascii')))
    for p in range(0,len(compressed),1024*1024):output.append(_chunk(b'IDAT',compressed[p:p+1024*1024]))
    output.append(_chunk(b'IEND',b''));return b''.join(output)

def create_test_set(color_bytes,heightmap_bytes,settings,name='',version='',created=None):
    color=read_png(color_bytes);heightmap=read_png(heightmap_bytes)
    if heightmap['color'] not in (0,4):raise ValueError('The heightmap must be a grayscale PNG. Regenerate/export the matching heightmap first.')
    plan=describe(settings,color,heightmap,name,version,created)
    outputs={'Test_Interlaced.png':append_footer(color,plan),'Test_Heightmap.png':append_footer(heightmap,plan,True)}
    outputs['Test_Settings.json']=(json.dumps(plan,indent=2,ensure_ascii=True)+'\n').encode()
    outputs['PRINT_README.txt']=(
        'LENTICULIZER LABELED TEST SET\n\n'+plan['print_instruction']+'\n\n'
        'Test_Interlaced.png: original artwork plus a settings footer BELOW the active image.\n'
        'Test_Heightmap.png: matching enlarged height/depth map; the added footer is zero.\n'
        'The original active pixel rectangle is unchanged in both files. No artwork was rescaled.\n'
        'Text is printed only in the colour image. It is NOT raised geometry in the heightmap.\n'
        'The original project assets, reference images, materials and scene remain unchanged.\n'
        'Do not reimport these test exports as normal interlaced/reference-heightmap assets.\n\n'
        f'Active size: {_f(plan["active_size_mm"][0],2)} x {_f(plan["active_size_mm"][1],2)} mm\n'
        f'TEST CANVAS: {_f(plan["canvas_size_mm"][0],2)} x {_f(plan["canvas_size_mm"][1],2)} mm\n'
        f'Heightmap bit depth: {plan["heightmap_bit_depth"]}\n\n'+ '\n'.join(plan['label_lines'])+'\n').encode('utf8')
    return outputs,plan

def write_test_zip(destination,outputs,protected_paths=()):
    """Atomic write: a failed/canceled export cannot partially replace a test ZIP."""
    path=Path(destination).expanduser().resolve()
    if any(path==Path(p).expanduser().resolve() for p in protected_paths if p):raise ValueError('Choose a new test ZIP filename, not a project/source file.')
    if path.suffix.lower()!='.zip':raise ValueError('Choose a .zip filename for the labeled test set.')
    fd,temp=tempfile.mkstemp(prefix='.lenticulizer-test-',suffix='.tmp',dir=str(path.parent));os.close(fd)
    try:
        with ZipFile(temp,'w',ZIP_STORED) as z:
            for name,data in outputs.items():z.writestr(name,data)
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
