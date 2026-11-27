"""Question-free, deterministic private certificate PNG; fixed renderer v1."""
from pathlib import Path
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

VERSION='gnosis.png.v2'
FONT_ROOT=Path('/usr/share/fonts/truetype')
FONTS={'regular':FONT_ROOT/'dejavu/DejaVuSans.ttf','bold':FONT_ROOT/'dejavu/DejaVuSans-Bold.ttf','mono':FONT_ROOT/'dejavu/DejaVuSansMono.ttf','rune':FONT_ROOT/'noto/NotoSansRunic-Regular.ttf'}
INK='#202527'; TEAL='#146C68'; GOLD='#BB9236'; PAPER='#FAF9F5'; MUTED='#425B5B'

def font(size,kind='regular'):
    return ImageFont.truetype(str(FONTS[kind]),size)

def check_fonts():
    for kind in FONTS: font(30,kind)
    f=font(50,'rune'); masks=[bytes(f.getmask(chr(i))) for i in range(0x16a0,0x16a1)]
    if masks[0]==bytes(f.getmask('\uffff')): raise RuntimeError('Runic font unavailable')

def render(p, digest):
    im=Image.new('RGB',(1200,1500),PAPER); d=ImageDraw.Draw(im)
    def text(x,y,s,size=26,kind='regular',color=INK,anchor=None):
        d.text((x,y),str(s),font=font(size,kind),fill=color,anchor=anchor)
    def wrap(s,width,size,kind='regular'):
        out=[]; line=''; f=font(size,kind)
        for word in str(s).split():
            candidate=(line+' '+word).strip()
            if line and d.textlength(candidate,font=f)>width: out.append(line); line=word
            else: line=candidate
        if line:out.append(line)
        return out
    def paragraph(x,y,s,width,size=25,kind='regular',color=MUTED,center=False,maxlines=6):
        lines=wrap(s,width,size,kind)
        if len(lines)>maxlines:raise ValueError('certificate_text_overflow')
        for line in lines:
            if d.textlength(line,font=font(size,kind))>width:raise ValueError('certificate_text_overflow')
            text(x,y,line,size,kind,color,'mt' if center else None); y+=size+8
        return y
    d.rectangle((30,30,1170,1470),outline=TEAL,width=3)
    d.rectangle((44,44,1156,1456),outline=GOLD,width=1)
    text(75,70,'GNOSIS.BOT',32,'bold',TEAL);text(1125,78,'READING RECORD',21,'mono',MUTED,'ra')
    d.line((75,120,1125,120),fill=GOLD,width=3)
    hardware=p['kind']=='quantum_hardware'
    if hardware:
        text(600,153,'Certificate of',51,'bold',INK,'mt');text(600,215,'Quantum Authenticity',51,'bold',INK,'mt')
    else:text(600,180,'Gnosis Reading Certificate',48,'bold',INK,'mt')
    subtitle=p['method_label']
    if hardware and p['source'].get('logical_qubits'):
        subtitle += ' · '+str(p['source']['logical_qubits'])+' Logical Qubits'
    size=28
    while d.textlength(subtitle,font=font(size,'bold'))>1040 and size>19:size-=1
    text(600,292,subtitle,size,'bold' if hardware and p['source'].get('logical_qubits') else 'regular',TEAL,'mt')
    d.line((75,340,1125,340),fill=TEAL,width=2)
    r=p['reading']; fmt=r['format']
    if fmt=='iching.v1':
        sides=[('NOW',r['now']),('BECOMING',r['becoming'])]
        for i,(role,h) in enumerate(sides):
            cx=335+530*i
            text(cx,377,role,23,'mono',TEAL,'mt')
            for j,bit in enumerate(reversed(h['bits_bottom_to_top'])):
                y=432+j*32
                if bit:d.rectangle((cx-124,y,cx+124,y+18),fill=INK)
                else:
                    d.rectangle((cx-124,y,cx-17,y+18),fill=INK);d.rectangle((cx+17,y,cx+124,y+18),fill=INK)
                if i==0 and 6-j in r['moving_positions']:d.ellipse((cx+139,y+1,cx+155,y+17),fill=GOLD)
            text(cx,642,f"HEXAGRAM {h['number']:02d}",22,'mono',TEAL,'mt')
            title_size=31
            while len(wrap(h['title'],460,title_size,'bold'))>2 and title_size>23:title_size-=1
            y=paragraph(cx,681,h['title'],460,title_size,'bold',INK,True,3)
            cap_size=25
            while y+12+len(wrap(h['one_liner'],450,cap_size))*(cap_size+8)>908 and cap_size>18:cap_size-=1
            if y+12+len(wrap(h['one_liner'],450,cap_size))*(cap_size+8)>908:raise ValueError('certificate_caption_overflow')
            paragraph(cx,y+12,h['one_liner'],450,cap_size,'regular',MUTED,True,6)
        text(600,925,'Changing lines: '+(', '.join(map(str,r['moving_positions'])) if r['moving_positions'] else 'None'),25,'mono',TEAL,'mt')
    else:
        rows=r['draws'] if fmt=='runes_pouch.v1' else r['recognized']
        if not rows: paragraph(600,550,'No qualifying rune formation recognized',950,38,'bold',INK,True)
        else:
            cols=3 if len(rows)<=3 else 4 if len(rows)<=12 else 6
            nrows=(len(rows)+cols-1)//cols; cellw=1040/cols; cellh=540/nrows
            for idx,x in enumerate(rows):
                cx=80+cellw*(idx%cols+0.5); y=365+cellh*(idx//cols)
                if 'position' in x: text(cx,y,x['position'].upper(),20,'mono',TEAL,'mt');y+=36
                glyphsize=min(124,int(cellh*.29));text(cx,y,x['glyph'],glyphsize,'rune',INK,'mt');y+=glyphsize+12
                fs=25 if nrows<=2 else 18
                y=paragraph(cx,y,x['name'],cellw-16,fs,'bold',INK,True,2)
                cap_size=21 if nrows<=2 else 14
                bottom=365+cellh*(idx//cols+1)-5
                while y+3+len(wrap(x['one_liner'],cellw-16,cap_size))*(cap_size+8)>bottom and cap_size>12:cap_size-=1
                if y+3+len(wrap(x['one_liner'],cellw-16,cap_size))*(cap_size+8)>bottom:raise ValueError('certificate_rune_caption_overflow')
                paragraph(cx,y+3,x['one_liner'],cellw-16,cap_size,'regular',MUTED,True,5)
            if r.get('compounds'):
                # Full compounds preserved in signed payload; fail closed rather than truncate names.
                paragraph(600,913,'Compounds: '+'; '.join(' + '.join(c) for c in r['compounds']),1040,17,'regular',MUTED,True,3)
    d.line((75,980,1125,980),fill=GOLD,width=2)
    text(75,1005,'SOURCE & VERIFICATION',23,'bold',TEAL)
    s=p['source']; y=1043
    lines=[s['label'],'Reading completed (UTC): '+p['reading_completed_at']]
    if hardware:
        lines += ['Backend: '+s['backend']+'   |   IBM job: '+s['ibm_job_id']]
        if s.get('batch_id'):lines += ['Batch: '+s['batch_id']+' / index '+str(s['sample_index_zero_based'])]
        if s.get('submitted_at'):lines += ['Hardware submitted (UTC): '+s['submitted_at']]
        if s.get('acquired_at'):lines += ['Hardware acquired (UTC): '+s['acquired_at']]
        elif s.get('staged_at'):lines += ['Result staged (UTC): '+s['staged_at']]
        lines += ['Circuit: '+s['circuit_version']+' | SHA-256 '+s['circuit_sha256'][:16]+'…']
        if s.get('logical_qubits'):lines += [str(s['logical_qubits'])+' logical qubits'+(' / '+str(s['shots_per_casting'])+' shots per casting' if 'shots_per_casting' in s else '')]
        if s.get('measured_shots'):lines += [str(s['measured_shots'])+' measured shots; medoid selection']
    for line in lines:y=paragraph(75,y,line,1050,19,'regular',INK,maxlines=2)
    if y>1323:raise ValueError('certificate_provenance_overflow')
    text(75,1328,'GQTP checkpoint '+str(p['integrity']['checkpoint_size'])+'  |  Gnosis-signed record',20,'mono',TEAL)
    text(75,1361,'SHA-256 '+digest,19,'mono',INK)
    text(75,1395,'Documents recorded provenance; not an IBM-issued certificate or prediction guarantee.',17,'regular',MUTED)
    out=BytesIO();im.save(out,format='PNG',compress_level=9);return out.getvalue()
