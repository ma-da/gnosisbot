/** Playback policy only. Color, spacing and viewport limits live in global.css. */
export const CONFIG = Object.freeze({
  /* Decorative pre-reveal motion; not hardware activity or entropy evidence. */
  ambientIntervalMs: 950,
  ambientMorphMs: 810,

  /* Unhurried bottom-to-top reveal of the authoritative measured coin lines. */
  revealStartDelay: 260,
  coinPulseMs: 55,
  lineRevealMs: 180,

  /* Three times the original 880 ms Now → Becoming transition. */
  morphMs: 2640,

  /* Deterministic grouping of historical demo readings. */
  clusterCount: 11
});
