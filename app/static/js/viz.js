import {CONFIG} from './config.js?v=0.6';
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const TWO_PI=2*Math.PI;
const css=(name, fallback)=>getComputedStyle(document.documentElement).getPropertyValue(name).trim()||fallback;
const point=(angle,r)=>[Math.cos(angle)*r,Math.sin(angle)*r];
const rgbaColors=()=>[css('--cyan','#4fd9e8'),css('--aqua','#32c7d0'),css('--teal','#1ea8b3'),css('--mint','#b9e86a'),css('--yellow','#f0d64d'),css('--amber','#f2b134')];

/** A visual replay of archived measurements, not a measured evolution of quantum states. */
export class GnosisViz {
  constructor(el){
    this.el=el;this.reading=null;this.phase='now';this.token=0;this.hexagrams=[];this.isHardware=true;
    this.reduceMotion=window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.ambient=false;this.ambientTimer=null;
    this.colors=rgbaColors();this.build();
  }
  build(){
    this.el.replaceChildren();
    this.svg=d3.select(this.el).append('svg').attr('viewBox','-345 -345 690 690')
      .attr('role','presentation').attr('focusable','false');
    const root=this.svg.append('g');
    this.hanzi=root.append('text').attr('class','background-hanzi').attr('x',0).attr('y',0)
      .attr('text-anchor','middle').attr('dominant-baseline','central')
      .attr('font-family','var(--font-cn)').attr('font-weight',900)
      .attr('fill','var(--text)').attr('opacity',css('--char-opacity','.095')).text('易');
    // The 64 miniature hexagrams alone establish the outer circumference.
    root.append('circle').attr('r',291).attr('class','ring-guideline faint');
    this.traceGroup=root.append('g').attr('class','radial-traces');
    this.traces=[];
    for(let i=0;i<24;i++){
      const angle=-Math.PI/2+TWO_PI*(i+.5)/24;
      const [x1,y1]=point(angle,284),[x2,y2]=point(angle,289);
      this.traces.push(this.traceGroup.append('line')
        .attr('x1',x1).attr('y1',y1).attr('x2',x2).attr('y2',y2)
        .attr('stroke',this.colors[i%this.colors.length]).attr('stroke-width',i%4===3?2.7:1.45)
        .attr('stroke-linecap','round').attr('opacity',.18).node());
    }
    this.outer=root.append('g').attr('class','outer-hexagram-ring');
    this.drawOuter([]);
    this.qubitsGroup=root.append('g').attr('class','qubit-ring');
    this.qubits=[];
    for(let i=0;i<24;i++){
      const angle=-Math.PI/2+TWO_PI*(i+.5)/24;
      const [x,y]=point(angle,273);
      const isMove=(i%4===3);
      const node=this.qubitsGroup.append('rect')
        .attr('x',x-5.3).attr('y',y-5.3).attr('width',10.6).attr('height',10.6)
        .attr('rx',0).attr('fill','var(--paper)').attr('stroke','var(--ring-muted)')
        .attr('stroke-width',isMove?1.5:1).node();
      const label=isMove?`Line ${Math.floor(i/4)+1}, moving indicator`:
        `Line ${Math.floor(i/4)+1}, coin ${i%4+1}`;
      d3.select(node).append('title').text(label);
      this.qubits.push({node,angle,isMove,line:Math.floor(i/4),which:i%4});
    }
    // A quiet circular hairline inside the qubit ring keeps the centerpiece crisp.
    root.append('circle').attr('r',258).attr('class','ring-guideline faint');
    this.hexGroup=root.append('g').attr('class','central-hexagram');
    this.rows=[];
    const lineWidth=398,gap=26,thickness=23;
    for(let i=0;i<6;i++){
      const y=160-i*64;
      const row=this.hexGroup.append('g').attr('transform',`translate(0,${y})`).attr('opacity',0);
      const left=row.append('rect').attr('height',thickness).attr('y',-thickness/2).attr('fill','var(--hex-ink)');
      const right=row.append('rect').attr('height',thickness).attr('y',-thickness/2).attr('fill','var(--hex-ink)');
      this.rows.push({row,left,right,width:lineWidth,gap,baseY:y});
    }
    this.setHanzi('易',false);
  }
  setHexagrams(hexagrams){this.hexagrams=hexagrams.slice().sort((a,b)=>a.number-b.number);this.drawOuter(this.hexagrams);}
  drawOuter(hexagrams){
    this.outer.selectAll('*').remove();
    hexagrams.forEach((h,j)=>{
      const angle=-Math.PI/2+TWO_PI*j/64;
      const [x,y]=point(angle,324);
      // Local +Y is the bottom (first line) of each miniature hexagram.
      // Rotate that direction inward, toward the center of the instrument.
      const rotationDeg=(angle+Math.PI/2)*180/Math.PI;
      const mark=this.outer.append('g').attr('class','outer-glyph').attr('data-number',h.number)
        .attr('transform',`translate(${x},${y}) rotate(${rotationDeg})`);
      const bits=h.bits;
      // 25.5 × 24.25 units: a compact, near-square six-line glyph.
      // Line 1 is drawn at the lower (inward-facing) side of the symbol.
      const glyphWidth=25.5, glyphHeight=2.85, glyphGap=3.8;
      const halfWidth=(glyphWidth-glyphGap)/2;
      for(let i=0;i<6;i++){
        const y0=10.5-i*4.28;
        if(bits[i]==='1'){
          mark.append('rect').attr('x',-glyphWidth/2).attr('y',y0).attr('width',glyphWidth).attr('height',glyphHeight).attr('class','glyph-line');
        }else{
          mark.append('rect').attr('x',-glyphWidth/2).attr('y',y0).attr('width',halfWidth).attr('height',glyphHeight).attr('class','glyph-line');
          mark.append('rect').attr('x',glyphGap/2).attr('y',y0).attr('width',halfWidth).attr('height',glyphHeight).attr('class','glyph-line');
        }
      }
      mark.append('title').text(`#${h.number} ${h.title}`);
    });
  }
  activeGlyph(number){
    this.outer.selectAll('.outer-glyph').classed('is-active',h=>false)
      .classed('is-active',function(){return Number(this.getAttribute('data-number'))===Number(number);});
  }
  setHanzi(chinese,animate=true){
    const text=chinese||'易', length=[...text].length;
    const apply=()=>this.hanzi.text(text).attr('font-size',length===1?590:length===2?380:280)
      .attr('textLength',length===1?595:635).attr('lengthAdjust','spacingAndGlyphs');
    this.hanzi.interrupt();
    if(animate&&!this.reduceMotion){
      this.hanzi.transition().duration(720).attr('opacity',0).on('end',()=>{
        apply();this.hanzi.transition().duration(1200).attr('opacity',css('--char-opacity','.095'));
      });
    }else{apply();this.hanzi.attr('opacity',css('--char-opacity','.095'));}
  }
  /** Stops all outstanding transitions and invalidates asynchronous replay. */
  cancel(){
    this.token++;
    this.ambient=false;
    if(this.ambientTimer!==null){clearTimeout(this.ambientTimer);this.ambientTimer=null;}
    this.rows.forEach(r=>{r.row.interrupt();r.left.interrupt();r.right.interrupt();});
    this.hanzi.interrupt();
    this.qubits.forEach(q=>d3.select(q.node).interrupt());
    this.traces.forEach(t=>d3.select(t).interrupt());
    this.hexGroup.classed('is-ambient',false);
  }

  /**
   * Unrevealed visual state. Random changes are purely decorative Math.random()
   * choices, NEVER a simulation or leak of the selected IBM shot.
   * Reduced-motion users receive one static, low-opacity placeholder.
   */
  startAmbient(){
    this.cancel();
    this.ambient=true;
    this.resetQubits();
    this.setHanzi('易',false);
    this.activeGlyph(null);
    this.hexGroup.classed('is-ambient',true);

    const paint=()=>{
      if(!this.ambient)return;
      if(document.visibilityState==='visible' || this.reduceMotion){
        this.rows.forEach((r,i)=>{
          if(!this.reduceMotion && Math.random()>.72)return;
          const solid=this.reduceMotion?(i%2===0):(Math.random()>.5);
          const half=(r.width-r.gap)/2;
          const duration=this.reduceMotion?0:CONFIG.ambientMorphMs;
          const jitter=this.reduceMotion?0:(Math.random()-.5)*13;
          r.row.transition().duration(duration)
            .attr('transform',`translate(0,${r.baseY+jitter})`)
            .attr('opacity',this.reduceMotion?.13:.09+Math.random()*.08);
          r.left.transition().duration(duration)
            .attr('x',-r.width/2).attr('width',solid?r.width:half)
            .attr('fill','var(--ring-muted)');
          r.right.transition().duration(duration)
            .attr('x',solid?r.width/2:r.gap/2).attr('width',solid?0:half)
            .attr('fill','var(--ring-muted)');
        });
      }
      if(!this.reduceMotion){
        this.ambientTimer=setTimeout(paint,CONFIG.ambientIntervalMs);
      }
    };
    paint();
  }

  clear(){
    this.cancel();this.reading=null;
    this.rows.forEach(r=>r.row.attr('opacity',0).attr('transform',`translate(0,${r.baseY})`));
    this.resetQubits();this.setHanzi('易',false);this.activeGlyph(null);
  }
  resetQubits(){
    this.qubits.forEach(q=>d3.select(q.node).attr('fill','var(--paper)').attr('stroke','var(--ring-muted)').attr('stroke-width',q.isMove?1.5:1));
    this.traces.forEach((t,i)=>{
      const angle=this.qubits[i].angle,[x,y]=point(angle,289);
      d3.select(t).attr('x2',x).attr('y2',y).attr('opacity',.12);
    });
  }
  /** Hold an archived reading privately until explicit user reveal. */
  setData(reading,{hardware=true,ambient=false}={}){
    this.cancel();this.reading=reading;this.isHardware=hardware;this.phase='now';
    this.rows.forEach(r=>r.row.attr('opacity',0).attr('transform',`translate(0,${r.baseY})`));
    this.resetQubits();this.setHanzi('易',false);this.activeGlyph(null);
    if(ambient)this.startAmbient();
  }
  drawRow(i,bit,phase,duration){
    const r=this.rows[i],moving=this.reading.moving_positions_bottom_to_top.includes(i+1);
    const color=moving?css('--gold','#bb9236'):css('--hex-ink','#202526');
    const solid=bit==='1',half=(r.width-r.gap)/2;
    const trans=this.reduceMotion?0:duration;
    const left=r.left.interrupt().transition().duration(trans).ease(d3.easeCubicInOut);
    const right=r.right.interrupt().transition().duration(trans).ease(d3.easeCubicInOut);
    left.attr('x',-r.width/2).attr('width',solid?r.width:half).attr('fill',color);
    right.attr('x',solid?r.width/2:r.gap/2).attr('width',solid?0:half).attr('fill',color);
    r.row.transition().duration(trans).attr('opacity',1);
  }
  settleQubit(i,animate){
    if(!this.reading)return;
    const q=this.qubits[i],line=this.reading.lines[q.line];
    const bit=q.isMove ? Number(Boolean(line.moving_flag_physically_measured??line.moving_classically_verified)) : Number(line.coin_bits[q.which]);
    const mismatch=q.isMove&&this.isHardware&&!line.moving_flag_agrees;
    const color=mismatch?css('--coral','#e96b3c'):
      q.isMove?(bit?css('--gold','#bb9236'):css('--muted','#707779')):
      bit?css('--teal','#1ea8b3'):css('--blue','#3698aa');
    d3.select(q.node).interrupt().transition().duration(this.reduceMotion?0:animate?220:0)
      .attr('fill',color).attr('stroke',mismatch?css('--magenta','#cc315b'):color);
    const extra=(bit?14:0)+((q.line*11+q.which*7)%20)+(q.isMove&&bit?9:0);
    const length=16+extra, [x,y]=point(q.angle,289+length);
    d3.select(this.traces[i]).interrupt().transition().duration(this.reduceMotion?0:animate?310:0)
      .attr('x2',x).attr('y2',y).attr('opacity',q.isMove&&bit?.92:.53)
      .attr('stroke',color);
  }
  showPhase(phase,animate=true){
    if(!this.reading)return;
    this.cancel();this.phase=phase;
    this.rows.forEach(r=>r.row.attr('transform',`translate(0,${r.baseY})`));
    const bits=(phase==='now'?this.reading.now_bits_bottom_to_top:this.reading.becoming_bits_bottom_to_top);
    this.setHanzi(this.reading[phase].chinese,animate);
    this.activeGlyph(this.reading[phase].king_wen_number);
    this.rows.forEach((row,i)=>this.drawRow(i,bits[i],phase,animate?CONFIG.morphMs:0));
    this.qubits.forEach((_,i)=>this.settleQubit(i,false));
  }
  /**
   * User-triggered Now assembly. This intentionally NEVER calls Becoming.
   * Returns false if another reading/mode interrupted the animation.
   */
  async revealNow(){
    if(!this.reading)return false;
    this.cancel();
    const id=this.token,rd=this.reading;
    this.phase='now';this.resetQubits();
    this.rows.forEach(r=>r.row.attr('opacity',0).attr('transform',`translate(0,${r.baseY})`));
    this.setHanzi(rd.now.chinese,false);
    this.activeGlyph(rd.now.king_wen_number);
    if(this.reduceMotion){this.showPhase('now',false);return true;}
    await pause(CONFIG.revealStartDelay);
    for(let line=0;line<6;line++){
      if(this.token!==id)return false;
      for(let bit=0;bit<3;bit++){
        const idx=line*4+bit,q=this.qubits[idx];
        d3.select(q.node).interrupt().attr('fill',this.colors[(line+bit)%this.colors.length]);
        this.settleQubit(idx,true);
        await pause(CONFIG.coinPulseMs);
        if(this.token!==id)return false;
      }
      this.settleQubit(line*4+3,true);
      this.drawRow(line,rd.now_bits_bottom_to_top[line],'now',CONFIG.lineRevealMs);
      await pause(CONFIG.lineRevealMs);
    }
    return this.token===id;
  }
}
