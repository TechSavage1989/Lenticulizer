using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;

namespace Lenticulizer.Core
{
    // Append a replacement first IFD. Existing strips/tiles and their offsets
    // remain byte-for-byte intact; only the output copy's metadata changes.
    public static class TiffHeightmapMetadata
    {
        public static void Annotate(string path,int width,int height,double widthMm,double heightMm,double scaleMm)
        {
            using(var file=new FileStream(path,FileMode.Open,FileAccess.ReadWrite,FileShare.None))
            {
                byte[] head=new byte[8];file.ReadExactly(head);bool little=head[0]==73&&head[1]==73;
                if(!little&&!(head[0]==77&&head[1]==77))throw new InvalidDataException("Invalid TIFF byte order.");
                uint Read(byte[] b,int offset,int count) { uint value=0;for(int i=0;i<count;i++)value=(value<<8)|b[offset+(little?count-1-i:i)];return value; }
                byte[] Bytes(uint value,int count) { var b=new byte[count];for(int i=0;i<count;i++){b[little?i:count-1-i]=(byte)value;value>>=8;}return b; }
                void Put(uint value,int count){file.Write(Bytes(value,count));}
                byte[] Entry(int tag,int type,uint count,uint value)
                {return Bytes((uint)tag,2).Concat(Bytes((uint)type,2)).Concat(Bytes(count,4)).Concat(Bytes(value,4)).ToArray();}
                if(Read(head,2,2)!=42)throw new NotSupportedException("BigTIFF output metadata is not supported. Convert the heightmap to a standard TIFF or grayscale PNG first.");
                uint ifd=Read(head,4,4);if(ifd<8||ifd+2>file.Length)throw new InvalidDataException("Invalid TIFF directory.");
                file.Position=ifd;byte[] size=new byte[2];file.ReadExactly(size);int count=(int)Read(size,0,2);
                if(count>4096||ifd+2L+count*12L+4>file.Length)throw new InvalidDataException("Invalid TIFF directory size.");
                var entries=new List<byte[]>();string description="";
                for(int i=0;i<count;i++)
                {
                    byte[] entry=new byte[12];file.ReadExactly(entry);int tag=(int)Read(entry,0,2);
                    if(tag==270&&Read(entry,2,2)==2)
                    {
                        uint length=Read(entry,4,4);long here=file.Position;
                        if(length<=1048576)
                        {
                            byte[] value;
                            if(length<=4)value=entry.Skip(8).Take((int)length).ToArray();
                            else{uint offset=Read(entry,8,4);if(offset+length>file.Length)throw new InvalidDataException("Invalid TIFF description.");file.Position=offset;value=new byte[length];file.ReadExactly(value);}
                            description=Encoding.UTF8.GetString(value).TrimEnd('\0');
                        }
                        file.Position=here;
                    }
                    else if(tag!=282&&tag!=283&&tag!=296)entries.Add(entry);
                }
                byte[] next=new byte[4];file.ReadExactly(next);
                description=string.Join("\n",description.Split('\n').Where(line=>!line.StartsWith("LenticulizerHeightScaleMm="))).TrimEnd();
                description+=(description.Length>0?"\n":"")+"LenticulizerHeightScaleMm="+scaleMm.ToString("0.######",CultureInfo.InvariantCulture)+"\0";
                file.Position=file.Length;if((file.Position&1)!=0)file.WriteByte(0);
                uint Rational(double value)
                {
                    uint offset=checked((uint)file.Position);uint den=(uint)Math.Clamp(Math.Floor(uint.MaxValue/Math.Max(value,1)),1,1000000);
                    Put(checked((uint)Math.Round(value*den)),4);Put(den,4);return offset;
                }
                uint x=Rational(width*25.4/widthMm),y=Rational(height*25.4/heightMm);
                uint desc=checked((uint)file.Position);byte[] text=Encoding.UTF8.GetBytes(description);file.Write(text);
                if((file.Position&1)!=0)file.WriteByte(0);
                uint replacement=checked((uint)file.Position);
                entries.Add(Entry(282,5,1,x));entries.Add(Entry(283,5,1,y));
                byte[] units=Entry(296,3,1,0);Array.Copy(Bytes(2,2),0,units,8,2);entries.Add(units);
                entries.Add(Entry(270,2,(uint)text.Length,desc));
                Put((uint)entries.Count,2);foreach(var e in entries.OrderBy(e=>Read(e,0,2)))file.Write(e);file.Write(next);
                file.Position=4;Put(replacement,4);file.Flush(true);
            }
        }
    }
}
