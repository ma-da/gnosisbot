/**
 * gnosis.bot homepage | Fibonacci quarter-disc navigation mosaic.
 *
 * Each colored tile is a FILLED 90-degree sector of a circle, rather than a
 * stroked arc. The seven non-overlapping Fibonacci squares (13, 8, 5, 3,
 * 2, 1, 1 units) follow the standard golden-rectangle tiling. Every sector
 * occupies one of these squares and has an independent link destination.
 *
 * This is a geometric illustration, not a claim about physical quantum
 * computation. Adjust colors and tile gaps below without changing HTML.
 */

// Add routes as the applications are created, e.g. 2: '/future-app.html'.
const SPIRAL_DESTINATIONS = Object.freeze({
  1: null,
  2: null,
  3: null,
  4: null,
  5: null,
  6: null,
  7: null,
});

const SPIRAL_TOOLTIPS = Object.freeze({
  1: "Explore · Application 01",
  2: "Explore · Application 02",
  3: "Explore · Application 03",
  4: "Explore · Application 04",
  5: "Explore · Application 05",
  6: "Explore · Application 06",
  7: "Explore · Application 07",
});

// CERN-inspired / gnosis.bot palette: gold, blue, coral, mint, magenta.
const SPIRAL_COLORS = Object.freeze([
  '#61c9a9', '#4fd9e8', '#e96b3c', '#f0d64d',
  '#cc315b', '#4467e6', '#f2b134',
]);

const SVG_NS = 'http://www.w3.org/2000/svg';
const SPIRAL_VIEWBOX = Object.freeze({ width: 520, height: 286 });
const SPIRAL_GRID = Object.freeze({ width: 21, height: 13 });
const SPIRAL_PADDING_Y = 24;

// Tiling coordinates are Fibonacci units; not pixels.
// NW = upper-left quadrant, etc. Order goes from outside to inside.
const FIBONACCI_TILES = Object.freeze([
  { x:  0, y:  0, size: 13, quadrant: 'nw' },
  { x: 13, y:  0, size:  8, quadrant: 'ne' },
  { x: 16, y:  8, size:  5, quadrant: 'se' },
  { x: 13, y: 10, size:  3, quadrant: 'sw' },
  { x: 13, y:  8, size:  2, quadrant: 'nw' },
  { x: 15, y:  8, size:  1, quadrant: 'ne' },
  { x: 15, y:  9, size:  1, quadrant: 'se' },
]);

function svgElement(name, attributes = {}) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attributes)) {
    el.setAttribute(key, String(value));
  }
  return el;
}

/**
 * Create a closed SVG wedge from a circle center, two perpendicular radii,
 * and a true circular arc. The inset leaves narrow background-colored gaps.
 */
function quarterDiscPath(tile, scale, originX, originY) {
  const side = tile.size * scale;
  const inset = Math.min(6, Math.max(1.6, side * 0.045));
  const x = originX + tile.x * scale + inset;
  const y = originY + tile.y * scale + inset;
  const r = side - inset * 2;
  const right = x + r;
  const bottom = y + r;
  const f = n => Number(n.toFixed(3));

  // SVG's sweep flag 1 means clockwise in screen coordinates.
  const geometry = {
    nw: { center: [right, bottom], start: [right, y], end: [x, bottom], sweep: 0 },
    ne: { center: [x, bottom], start: [x, y], end: [right, bottom], sweep: 1 },
    se: { center: [x, y], start: [right, y], end: [x, bottom], sweep: 1 },
    sw: { center: [right, y], start: [right, bottom], end: [x, y], sweep: 1 },
  }[tile.quadrant];

  const [cx, cy] = geometry.center.map(f);
  const [sx, sy] = geometry.start.map(f);
  const [ex, ey] = geometry.end.map(f);
  return `M ${cx} ${cy} L ${sx} ${sy} ` +
    `A ${f(r)} ${f(r)} 0 0 ${geometry.sweep} ${ex} ${ey} Z`;
}

function buildGoldenSpiral() {
  const container = document.querySelector('#spiral-segments');
  const status = document.querySelector('#spiral-status');
  if (!container || !status) return;
		
		// One reusable tooltip for all spiral segments.
		const tooltip = document.createElement('div');
		tooltip.className = 'spiral-tooltip';
		tooltip.id = 'spiral-tooltip';
		tooltip.setAttribute('role', 'tooltip');
		tooltip.hidden = true;

		document.body.appendChild(tooltip);

		function positionTooltip(hit, event) {
				const bounds = hit.getBoundingClientRect();

				const x = event?.clientX ?? bounds.left + bounds.width / 2;
				const y = event?.clientY ?? bounds.top + bounds.height / 2;

				const halfWidth = tooltip.offsetWidth / 2;

				tooltip.style.left = `${Math.max(
						halfWidth + 12,
						Math.min(window.innerWidth - halfWidth - 12, x)
				)}px`;

				tooltip.style.top = `${Math.max(45, y - 12)}px`;
		}

		function showTooltip(hit, segmentNumber, event) {
				tooltip.textContent = SPIRAL_TOOLTIPS[segmentNumber];
				tooltip.hidden = false;
				positionTooltip(hit, event);
		}

		function hideTooltip() {
				tooltip.hidden = true;
		}		

  const scale = (SPIRAL_VIEWBOX.height - 2 * SPIRAL_PADDING_Y) / SPIRAL_GRID.height;
  const originX = (SPIRAL_VIEWBOX.width - SPIRAL_GRID.width * scale) / 2;
  const originY = (SPIRAL_VIEWBOX.height - SPIRAL_GRID.height * scale) / 2;

  const selectSegment = segmentNumber => {
    const target = SPIRAL_DESTINATIONS[segmentNumber];
    if (typeof target === 'string' && target.trim()) {
      window.location.assign(target);
      return;
    }
    status.textContent = `Exploration ${String(segmentNumber).padStart(2, '0')} · coming soon`;
  };

  container.replaceChildren();
  FIBONACCI_TILES.forEach((tile, index) => {
    const segmentNumber = index + 1;
    const group = svgElement('g', {
      class: 'spiral-sector',
      'data-segment': segmentNumber,
    });

    const wedge = svgElement('path', {
      d: quarterDiscPath(tile, scale, originX, originY),
      fill: SPIRAL_COLORS[index],
      class: 'spiral-sector-shape',
      'aria-hidden': 'true',
    });
    group.appendChild(wedge);

    // The entire non-overlapping Fibonacci tile is a pointer target, making
    // the tiny inner wedges easier to click without enlarging their artwork.
    const hit = svgElement('rect', {
      x: originX + tile.x * scale,
      y: originY + tile.y * scale,
      width: tile.size * scale,
      height: tile.size * scale,
      class: 'spiral-sector-hit',
      fill: 'transparent',
      'pointer-events': 'all',
      role: 'button',
      tabindex: 0,
      'aria-label': `Explore application ${segmentNumber}${SPIRAL_DESTINATIONS[segmentNumber] ? '' : ' (coming soon)'}`,
    });
    hit.addEventListener('click', () => selectSegment(segmentNumber));
    hit.addEventListener('keydown', event => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        selectSegment(segmentNumber);
      }
    });
				
				hit.setAttribute(
						'aria-label',
						SPIRAL_TOOLTIPS[segmentNumber]
				);

				hit.addEventListener('pointerenter', event => {
						showTooltip(hit, segmentNumber, event);
				});

				hit.addEventListener('pointermove', event => {
						if (!tooltip.hidden) {
								positionTooltip(hit, event);
						}
				});

				hit.addEventListener('pointerleave', hideTooltip);

				hit.addEventListener('focus', () => {
						showTooltip(hit, segmentNumber);
				});

				hit.addEventListener('blur', hideTooltip);				
				
    group.appendChild(hit);
    container.appendChild(group);
  });
}

function configureDiagramFallback() {
  const image = document.querySelector('#ibm-cloud-diagram');
  const fallback = document.querySelector('#ibm-diagram-fallback');
  if (!image || !fallback) return;
  const handleMissing = () => { image.hidden = true; fallback.hidden = false; };
  image.addEventListener('error', handleMissing);
  if (image.complete && image.naturalWidth === 0) handleMissing();
}

buildGoldenSpiral();
configureDiagramFallback();
