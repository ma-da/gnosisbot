/**
 * Narrow, clickable archival similarity ribbon.
 * Its groups are computed from line-pattern distance, NOT measured wave interference
 * and NOT a probability distribution over future readings.
 */
const css=(name,fallback)=>getComputedStyle(document.documentElement).getPropertyValue(name).trim()||fallback;
export class GnosisInterference {
  constructor(el,onSelect){this.el=el;this.onSelect=onSelect;this.svg=null;this.selected=null;}
  render(clusters,selectedIndex){
    this.el.replaceChildren();
    const palette=[css('--red','#d43b36'),css('--magenta','#cc315b'),css('--coral','#e96b3c'),
      css('--gold','#bb9236'),css('--teal','#1ea8b3'),css('--cyan','#4fd9e8')];
    this.svg=d3.select(this.el).append('svg').attr('viewBox','0 0 1000 160')
      .attr('preserveAspectRatio','none').attr('role','group')
      .attr('aria-label','Archived IBM readings grouped by similarity. Select a pulse to inspect its reading.');
    const defs=this.svg.append('defs');
    const glow=defs.append('filter').attr('id','gnosis-spectrum-glow')
      .attr('x','-70%').attr('y','-150%').attr('width','240%').attr('height','400%');
    glow.append('feGaussianBlur').attr('stdDeviation',3);
    this.svg.append('line').attr('x1',9).attr('x2',991).attr('y1',80).attr('y2',80)
      .attr('stroke','var(--light)').attr('stroke-width',1);
    const gap=14,available=980-gap*(clusters.length-1);
    const weights=clusters.map(c=>19+Math.max(1,c.size)*4.8);
    const sum=weights.reduce((a,b)=>a+b,0);
    let start=10;
				
				// Global vertical envelope for the interference field.
				//
				// Left edge:   0.5x original height
				// Center:      2.0x original height
				// Right edge:  0.5x original height
				//
				// Smooth, symmetric taper independent of cluster boundaries.
				const heightEnvelope = (x) => {
						const t = Math.max(0, Math.min(1, (x - 10) / 980));
						const wave = Math.sin(Math.PI * t);

						return 0.5 + 1.5 * wave * wave;
				};				
				
    clusters.forEach((cluster,ci)=>{
						const span = available * weights[ci] / sum;
						const left = start;
						const end = left + span;
						const color = palette[ci % palette.length];

						function selectNearestReading(event) {
								const [mouseX] = d3.pointer(event, this.svg.node());

								const usableWidth = Math.max(1, span - 9);
								const fraction = Math.max(
										0,
										Math.min(
												0.999999,
												(mouseX - left - 4.5) / usableWidth
										)
								);

								const memberIndex = Math.floor(
										fraction * cluster.members.length
								);

								const selected = cluster.members[memberIndex];

								if (selected) {
										this.onSelect(selected.index);
								}
						}
      const g=this.svg.append('g').attr('class','interference-cluster');
      // Touch-sized cluster surface behind individually clickable pulses.
						g.append('rect')
								.attr('x', left)
								.attr('y', 8)
								.attr('width', span)
								.attr('height', 144)
								.attr('fill', 'transparent')
								.attr('pointer-events', 'all')
								.attr('role', 'button')
								.attr('tabindex', 0)
								.attr(
										'aria-label',
										`Explore ${cluster.size} similar archived readings`
								)
								.style('cursor', 'pointer')
								.on('click', selectNearestReading)
								.on('keydown', event => {
										if (event.key === 'Enter' || event.key === ' ') {
												event.preventDefault();
												this.onSelect(cluster.medoid.index);
										}
								});
      const center=(start+end)/2;
						const halo = g.append('ellipse')
								.attr('cx', center)
								.attr('cy', 80)
								.attr('rx', Math.max(2, span * .30))
								.attr(
										'ry',
										(4 + Math.log2(cluster.size + 1) * 2) *
												heightEnvelope(center)
								)
        .attr('fill',color).attr('opacity',.10).attr('filter','url(#gnosis-spectrum-glow)').style('pointer-events','none');
      cluster.members.forEach((m,j)=>{
        const spread=span-9,
          x=start+4.5+((j+.5)/cluster.members.length)*spread;
        const peak=Math.sin(Math.PI*((j+.5)/cluster.members.length));
        const wobble=(Math.sin((m.index+1)*8.197)*.5+.5);
								// Preserve existing cluster density and shot variation.
								const baseHeight =
										10 +
										peak * (18 + Math.min(18, cluster.size * 1.2)) +
										wobble * 9;

								// Apply smooth global taper.
								const height = baseHeight * heightEnvelope(x);

								// Center the pulse vertically in the expanded SVG.
								const y1 = 80 - height / 2;
								const y2 = 80 + height / 2;
        const pulse=g.append('line').attr('class','interference-pulse').attr('data-index',m.index)
          .attr('x1',x).attr('x2',x+Math.sin(m.index*1.37)*1.8)
          .attr('y1',y1).attr('y2',y2)
          .attr('stroke',color).attr('stroke-width',cluster.size<4?2.3:1.9)
          .attr('stroke-linecap','round').attr('opacity',.62)
          .attr('role','button').attr('tabindex',0)
          .attr('aria-label',`Explore archived reading ${m.index+1}; ${m.now} becomes ${m.becoming}; ${m.matches} of 6 computed flags agree`)
          .on('click',()=>this.onSelect(m.index))
          .on('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.onSelect(m.index);}});
        pulse.append('title').text(`Archived shot ${m.index+1} · ${m.now} → ${m.becoming} · ${m.matches}/6 flags agree`);
      });
      start=end+gap;
    });
    this.setSelection(selectedIndex);
  }
  setSelection(index){
    this.selected=index;
    if(!this.svg)return;
    this.svg.selectAll('.interference-pulse').each(function(){
      const active=Number(this.getAttribute('data-index'))===index;
      d3.select(this).classed('is-selected',active)
        .attr('stroke-width',active?4.4:1.9).attr('opacity',active?1:.62);
    });
  }
  clear(){this.el.replaceChildren();this.svg=null;}
}
