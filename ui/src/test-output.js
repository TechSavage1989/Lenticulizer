(() => {
  'use strict';
  const MAX_RAW = 512 * 1024 * 1024;
  const SIGNATURE = new Uint8Array([137,80,78,71,13,10,26,10]);
  const enc = new TextEncoder();
  const dec = new TextDecoder('latin1');

  const GLYPHS = {
    ' ':['00000','00000','00000','00000','00000','00000','00000'],
    A:['01110','10001','10001','11111','10001','10001','10001'], B:['11110','10001','10001','11110','10001','10001','11110'],
    C:['01111','10000','10000','10000','10000','10000','01111'], D:['11110','10001','10001','10001','10001','10001','11110'],
    E:['11111','10000','10000','11110','10000','10000','11111'], F:['11111','10000','10000','11110','10000','10000','10000'],
    G:['01111','10000','10000','10111','10001','10001','01111'], H:['10001','10001','10001','11111','10001','10001','10001'],
    I:['11111','00100','00100','00100','00100','00100','11111'], J:['00111','00010','00010','00010','10010','10010','01100'],
    K:['10001','10010','10100','11000','10100','10010','10001'], L:['10000','10000','10000','10000','10000','10000','11111'],
    M:['10001','11011','10101','10101','10001','10001','10001'], N:['10001','11001','10101','10011','10001','10001','10001'],
    O:['01110','10001','10001','10001','10001','10001','01110'], P:['11110','10001','10001','11110','10000','10000','10000'],
    Q:['01110','10001','10001','10001','10101','10010','01101'], R:['11110','10001','10001','11110','10100','10010','10001'],
    S:['01111','10000','10000','01110','00001','00001','11110'], T:['11111','00100','00100','00100','00100','00100','00100'],
    U:['10001','10001','10001','10001','10001','10001','01110'], V:['10001','10001','10001','10001','10001','01010','00100'],
    W:['10001','10001','10001','10101','10101','10101','01010'], X:['10001','10001','01010','00100','01010','10001','10001'],
    Y:['10001','10001','01010','00100','00100','00100','00100'], Z:['11111','00001','00010','00100','01000','10000','11111'],
    '0':['01110','10001','10011','10101','11001','10001','01110'], '1':['00100','01100','00100','00100','00100','00100','01110'],
    '2':['01110','10001','00001','00010','00100','01000','11111'], '3':['11110','00001','00001','01110','00001','00001','11110'],
    '4':['00010','00110','01010','10010','11111','00010','00010'], '5':['11111','10000','10000','11110','00001','00001','11110'],
    '6':['01110','10000','10000','11110','10001','10001','01110'], '7':['11111','00001','00010','00100','01000','01000','01000'],
    '8':['01110','10001','10001','01110','10001','10001','01110'], '9':['01110','10001','10001','01111','00001','00001','01110'],
    '.':['00000','00000','00000','00000','00000','00110','00110'], ',':['00000','00000','00000','00000','00110','00110','00100'],
    ':':['00000','00110','00110','00000','00110','00110','00000'], '-':['00000','00000','00000','11111','00000','00000','00000'],
    '+':['00000','00100','00100','11111','00100','00100','00000'], '/':['00001','00010','00010','00100','01000','01000','10000'],
    '|':['00100','00100','00100','00100','00100','00100','00100'], '(':['00010','00100','01000','01000','01000','00100','00010'],
    ')':['01000','00100','00010','00010','00010','00100','01000'], '%':['11001','11010','00100','00100','01000','10110','00110'],
    '_':['00000','00000','00000','00000','00000','00000','11111'], '?':['01110','10001','00001','00010','00100','00000','00100'],
    '=':['00000','00000','11111','00000','11111','00000','00000'], '#':['01010','11111','01010','01010','11111','01010','00000']
  };

  const crcTable = (() => {
    const table = new Uint32Array(256);
    for (let n=0;n<256;n++) { let c=n; for(let k=0;k<8;k++) c=(c&1)?(0xedb88320^(c>>>1)):(c>>>1); table[n]=c>>>0; }
    return table;
  })();
  function crc32(bytes) { let c=0xffffffff; for(const b of bytes) c=crcTable[(c^b)&255]^(c>>>8); return (c^0xffffffff)>>>0; }
  function concat(parts) { const len=parts.reduce((n,p)=>n+p.length,0), out=new Uint8Array(len); let o=0; for(const p of parts){out.set(p,o);o+=p.length;} return out; }
  function be32(n){const b=new Uint8Array(4),v=new DataView(b.buffer);v.setUint32(0,n>>>0,false);return b;}
  function le16(n){const b=new Uint8Array(2),v=new DataView(b.buffer);v.setUint16(0,n&65535,true);return b;}
  function le32(n){const b=new Uint8Array(4),v=new DataView(b.buffer);v.setUint32(0,n>>>0,true);return b;}
  function ascii(s){return enc.encode(s);}
  function typeText(bytes){return String.fromCharCode(bytes[0],bytes[1],bytes[2],bytes[3]);}
  function chunk(kind,value){const k=ascii(kind);return concat([be32(value.length),k,value,be32(crc32(concat([k,value])))]);}
  function samePrefix(a,b){if(a.length<b.length)return false;for(let i=0;i<b.length;i++)if(a[i]!==b[i])return false;return true;}
  async function transform(bytes, mode) {
    const stream = mode==='inflate' ? new DecompressionStream('deflate') : new CompressionStream('deflate');
    const result = await new Response(new Blob([bytes]).stream().pipeThrough(stream)).arrayBuffer();
    return new Uint8Array(result);
  }
  async function sha256Hex(bytes){const hash=new Uint8Array(await crypto.subtle.digest('SHA-256',bytes));return Array.from(hash,b=>b.toString(16).padStart(2,'0')).join('');}

  async function readPng(input) {
    const data=input instanceof Uint8Array?input:new Uint8Array(input);
    if(!samePrefix(data,SIGNATURE))throw new Error('Export the current generated pair as PNG before making a labeled test set.');
    let pos=8,ihdr=null,ppm=null,ended=false;const chunks=[],idat=[];
    while(pos+12<=data.length){
      const view=new DataView(data.buffer,data.byteOffset+pos);const n=view.getUint32(0,false),typ=data.slice(pos+4,pos+8);pos+=8;
      if(n>data.length-pos-4)throw new Error('Incomplete PNG file.');
      const value=data.slice(pos,pos+n),crc=new DataView(data.buffer,data.byteOffset+pos+n,4).getUint32(0,false);pos+=n+4;
      if(crc32(concat([typ,value]))!==crc)throw new Error('PNG checksum failed. Regenerate the pair and retry.');
      const kind=typeText(typ);
      if(kind==='IHDR'){if(ihdr||value.length!==13)throw new Error('Invalid PNG header.');ihdr=value;}
      else if(kind==='IDAT')idat.push(value);
      else if(kind==='pHYs'&&value.length===9&&value[8]===1){const v=new DataView(value.buffer,value.byteOffset,value.byteLength);ppm=[v.getUint32(0,false),v.getUint32(4,false)];}
      else if(kind==='IEND'){ended=true;break;}
      else chunks.push([kind,value]);
    }
    if(!ended||!ihdr)throw new Error('Incomplete PNG file.');
    const h=new DataView(ihdr.buffer,ihdr.byteOffset,ihdr.byteLength),w=h.getUint32(0,false),height=h.getUint32(4,false),depth=h.getUint8(8),color=h.getUint8(9),compression=h.getUint8(10),filtering=h.getUint8(11),interlace=h.getUint8(12);
    if(!w||!height||![8,16].includes(depth)||![0,2,4,6].includes(color)||compression||filtering||interlace)throw new Error('This test export needs a non-interlaced 8/16-bit PNG. Generate the output pair first.');
    if(ppm&&(ppm[0]<=0||ppm[1]<=0))throw new Error('Invalid PNG print resolution.');
    const channels={0:1,2:3,4:2,6:4}[color],bpp=channels*(depth/8),row=w*bpp,expected=(row+1)*height;
    if(expected>MAX_RAW)throw new Error('This image is too large for a labeled test export. Use a smaller test print.');
    const filtered=await transform(concat(idat),'inflate');
    if(filtered.length!==expected)throw new Error('Invalid PNG image data.');
    for(let y=0;y<height;y++)if(filtered[y*(row+1)]>4)throw new Error('Invalid PNG filter.');
    return {w,h:height,depth,color,bpp,row,filtered,chunks,ppm,sha256:await sha256Hex(data)};
  }

  function nvalue(s,k,fallback=null){const n=Number(s?.[k]??fallback);return Number.isFinite(n)?n:null;}
  function fmt(v,digits=3){if(v==null)return'N/A';if(!digits)return String(Math.round(v));return Number(v).toFixed(digits).replace(/0+$/,'').replace(/\.$/,'');}
  function printable(value){return String(value??'').normalize('NFKD').replace(/[^\x00-\x7F]/g,'').toUpperCase().split('').map(c=>GLYPHS[c]?c:'?').join('');}
  function wrap(value,count){const words=printable(value).split(/\s+/).filter(Boolean),lines=[];let line='';for(let word of words){if(line&&line.length+word.length+1>count){lines.push(line);line='';}while(word.length>count){if(line){lines.push(line);line='';}lines.push(word.slice(0,count));word=word.slice(count);}if(word)line=(line+' '+word).trim();}if(line)lines.push(line);return lines.length?lines:[''];}

  function describe(settings,color,heightmap,name='',version='',created=''){
    if(color.w!==heightmap.w||color.h!==heightmap.h)throw new Error('The current image and heightmap have different pixel sizes. Regenerate both before exporting a test set.');
    const a=color.ppm,b=heightmap.ppm;if(a&&b&&a.some((x,i)=>Math.abs(x-b[i])>Math.max(1,Math.abs(x)*.00001)))throw new Error('The current pair has different print resolutions. Regenerate both before exporting a test set.');
    let ppm=a||b;
    if(!ppm){const wmm=nvalue(settings,'width_mm'),hmm=nvalue(settings,'height_mm');if(!(wmm>0&&hmm>0))throw new Error('Set the physical print size before exporting a test set.');ppm=[Math.max(1,Math.round(color.w*1000/wmm)),Math.max(1,Math.round(color.h*1000/hmm))];}
    const dpi=[ppm[0]*.0254,ppm[1]*.0254],mm=[color.w/ppm[0]*1000,color.h/ppm[1]*1000];
    created=created||new Date().toISOString().replace('T',' ').replace(/:\d\d\.\d\d\dZ$/,' UTC');name=String(name||'').trim().replace(/\s+/g,' ').slice(0,64);
    const relief=String(settings.output_mode||'').toUpperCase().replaceAll('_',' ')==='LENS-FREE RELIEF',direction=String(settings.orientation||'Vertical'),mode=relief?'LENS-FREE RELIEF':'LENTICULAR LENS';
    const backing=nvalue(settings,'backing_mm',0)||0,enabled=settings.backing_enabled!==false&&backing>0,raster=Math.abs(dpi[0]-dpi[1])<.01?fmt(dpi[0],2):`${fmt(dpi[0],2)} X ${fmt(dpi[1],2)}`;
    const lines=[`TEST PRINT | ${name||created}`,`${mode} | ${direction} | ${fmt(nvalue(settings,'views'),0)} VIEWS`,`LPI ${fmt(nvalue(settings,'lpi'))} | PHASE ${fmt(nvalue(settings,'phase_pitch',0))} PITCH`,`PRINTER DPI ${fmt(nvalue(settings,'printer_dpi'),0)} | RASTER DPI ${raster}`,`ACTIVE SIZE ${fmt(mm[0],2)} X ${fmt(mm[1],2)} MM`];
    if(['BUILD FROM HEIGHTMAP','HEIGHTMAP'].includes(String(settings.workflow||'').toUpperCase())){lines.push(`IMPORTED HEIGHTMAP | HEIGHT SCALE ${fmt(nvalue(settings,'reference_heightmap_thickness_mm'))} MM`);lines.push(`REFERENCE PHASE ${fmt(nvalue(settings,'reference_heightmap_phase_pitch',0))} PITCH`);}
    else if(relief)lines.push(`PRISM HEIGHT ${fmt(nvalue(settings,'relief_prism_height_mm',nvalue(settings,'thickness_mm')))} MM`);
    else{lines.push(`IOR ${fmt(nvalue(settings,'ior'))} | ANGLE ${fmt(nvalue(settings,'viewing_angle_deg'),1)} DEG`);lines.push(`LENS ${fmt(nvalue(settings,'thickness_mm'))} MM | BASE ${fmt(nvalue(settings,'base_mm'))} MM`);lines.push(`PROFILE: ${settings.lens_profile||'N/A'}`);}
    lines.push(`BACKING: ${enabled?fmt(backing)+' MM':'OFF'}`);lines.push(`LENTICULIZER ${version} | ${name?created:'TEST COPY'}`);
    const sx=Math.max(1,Math.floor(ppm[0]*.002/7+.5)),sy=Math.max(1,Math.floor(ppm[1]*.002/7+.5)),padX=Math.max(2,Math.floor(ppm[0]*.0015+.5)),padY=Math.max(2,Math.floor(ppm[1]*.0015+.5)),count=Math.floor((color.w-2*padX)/(6*sx));
    if(count<12)throw new Error('This print is too narrow for a readable settings footer. Use a test print at least about 25 mm wide.');
    const wrapped=lines.flatMap(x=>wrap(x,count)),fh=2*padY+wrapped.length*10*sy;if(color.w*(color.h+fh)*Math.max(color.bpp,heightmap.bpp)>MAX_RAW)throw new Error('The labeled image is too large. Use a smaller test print.');
    return {schema:1,test_only:true,name,created_utc:created,software:'Lenticulizer '+version,active_area_px:[0,0,color.w,color.h],active_size_mm:mm,canvas_size_px:[color.w,color.h+fh],canvas_size_mm:[mm[0],(color.h+fh)/ppm[1]*1000],pixels_per_metre:ppm,raster_dpi:dpi,footer_height_px:fh,footer_height_mm:fh/ppm[1]*1000,label_lines:wrapped,glyph_scale:[sx,sy],padding:[padX,padY],settings:{...settings},source_sha256:{interlaced:color.sha256,heightmap:heightmap.sha256},heightmap_bit_depth:heightmap.depth,heightmap_footer:'Zero height; no raised text',print_instruction:'Print BOTH test images at the saved physical size / 100% scale, with the same top-left origin. Do not fit-to-page. Do not use the clean heightmap with the enlarged test image.'};
  }

  function footerRaw(image,plan,isHeightmap){
    const {w,bpp,depth,color}=image,channels={0:1,2:3,4:2,6:4}[color],sample=depth/8,size=channels*sample;
    const black=new Uint8Array(size);if(color===4||color===6)black.fill(255,size-sample);const white=new Uint8Array(size);white.fill(255);
    const [sx,sy]=plan.glyph_scale,[padX,padY]=plan.padding,rows=[];
    for(let y=0;y<plan.footer_height_px;y++){
      const row=new Uint8Array(1+w*bpp);row[0]=0;
      for(let x=0;x<w;x++)row.set(isHeightmap?black:white,1+x*bpp);
      if(!isHeightmap){const relative=y-padY,line=Math.floor(relative/(10*sy)),gy=Math.floor(((relative%(10*sy))+(10*sy))%(10*sy)/sy);if(relative>=0&&line>=0&&line<plan.label_lines.length&&gy<7){for(let ci=0;ci<plan.label_lines[line].length;ci++){const glyph=GLYPHS[plan.label_lines[line][ci]]||GLYPHS['?'],x0=padX+ci*6*sx;for(let gx=0;gx<5;gx++)if(glyph[gy][gx]==='1')for(let xx=0;xx<sx;xx++){const px=x0+gx*sx+xx;if(px<w)row.set(black,1+px*bpp);}}}}
      rows.push(row);
    }
    return concat(rows);
  }

  async function appendFooter(image,plan,isHeightmap=false){
    const compressed=await transform(concat([image.filtered,footerRaw(image,plan,isHeightmap)]),'deflate');
    const ihdr=new Uint8Array(13),v=new DataView(ihdr.buffer);v.setUint32(0,image.w,false);v.setUint32(4,image.h+plan.footer_height_px,false);v.setUint8(8,image.depth);v.setUint8(9,image.color);v.setUint8(10,0);v.setUint8(11,0);v.setUint8(12,0);
    const out=[SIGNATURE,chunk('IHDR',ihdr)],safe=new Set(['iCCP','sRGB','gAMA','cHRM','sBIT','tRNS','bKGD']);
    for(const [kind,value] of image.chunks){if(safe.has(kind)||(kind==='tEXt'&&dec.decode(value).startsWith('LenticulizerHeightScaleMm\0')))out.push(chunk(kind,value));}
    const phys=new Uint8Array(9),pv=new DataView(phys.buffer);pv.setUint32(0,plan.pixels_per_metre[0],false);pv.setUint32(4,plan.pixels_per_metre[1],false);phys[8]=1;out.push(chunk('pHYs',phys));
    const summary={schema:plan.schema,test_only:true,active_area_px:plan.active_area_px,canvas_size_px:plan.canvas_size_px,canvas_size_mm:plan.canvas_size_mm,heightmap_footer:plan.heightmap_footer};out.push(chunk('tEXt',concat([ascii('LenticulizerTest\0'),ascii(JSON.stringify(summary))])));
    for(let o=0;o<compressed.length;o+=1024*1024)out.push(chunk('IDAT',compressed.slice(o,o+1024*1024)));out.push(chunk('IEND',new Uint8Array()));return concat(out);
  }

  function zipBytes(files,date=new Date()){
    const locals=[],centrals=[];let offset=0;const dosTime=((date.getHours()&31)<<11)|((date.getMinutes()&63)<<5)|((date.getSeconds()/2)&31),dosDate=(((date.getFullYear()-1980)&127)<<9)|(((date.getMonth()+1)&15)<<5)|(date.getDate()&31);
    for(const [name,data0] of Object.entries(files)){const data=data0 instanceof Uint8Array?data0:new Uint8Array(data0),nameBytes=ascii(name),crc=crc32(data),local=concat([le32(0x04034b50),le16(20),le16(0),le16(0),le16(dosTime),le16(dosDate),le32(crc),le32(data.length),le32(data.length),le16(nameBytes.length),le16(0),nameBytes,data]);locals.push(local);
      const central=concat([le32(0x02014b50),le16(20),le16(20),le16(0),le16(0),le16(dosTime),le16(dosDate),le32(crc),le32(data.length),le32(data.length),le16(nameBytes.length),le16(0),le16(0),le16(0),le16(0),le32(0),le32(offset),nameBytes]);centrals.push(central);offset+=local.length;}
    const centralData=concat(centrals),end=concat([le32(0x06054b50),le16(0),le16(0),le16(centrals.length),le16(centrals.length),le32(centralData.length),le32(offset),le16(0)]);return concat([...locals,centralData,end]);
  }

  async function createTestSet(colorBytes,heightmapBytes,settings,name='',version='',created=''){
    const color=await readPng(colorBytes),heightmap=await readPng(heightmapBytes);if(![0,4].includes(heightmap.color))throw new Error('The heightmap must be a grayscale PNG. Regenerate/export the matching heightmap first.');
    const plan=describe(settings,color,heightmap,name,version,created),outputs={'Test_Interlaced.png':await appendFooter(color,plan,false),'Test_Heightmap.png':await appendFooter(heightmap,plan,true)};
    outputs['Test_Settings.json']=ascii(JSON.stringify(plan,null,2)+'\n');outputs['PRINT_README.txt']=enc.encode(`LENTICULIZER LABELED TEST SET\n\n${plan.print_instruction}\n\nTest_Interlaced.png: original artwork plus a settings footer BELOW the active image.\nTest_Heightmap.png: matching enlarged height/depth map; the added footer is zero.\nThe original active pixel rectangle is unchanged in both files. No artwork was rescaled.\nText is printed only in the colour image. It is NOT raised geometry in the heightmap.\nThe original project assets, reference images, materials and scene remain unchanged.\nDo not reimport these test exports as normal interlaced/reference-heightmap assets.\n\nActive size: ${fmt(plan.active_size_mm[0],2)} x ${fmt(plan.active_size_mm[1],2)} mm\nTEST CANVAS: ${fmt(plan.canvas_size_mm[0],2)} x ${fmt(plan.canvas_size_mm[1],2)} mm\nHeightmap bit depth: ${plan.heightmap_bit_depth}\n\n${plan.label_lines.join('\n')}\n`);
    return {outputs,plan,zip:zipBytes(outputs)};
  }

  globalThis.LenticulizerTestOutput=Object.freeze({readPng,describe,appendFooter,createTestSet,zipBytes,crc32});
})();
