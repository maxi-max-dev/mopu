# Graphite workspace

A quiet operator's desktop, centered on a real phone. Phone picture first; task chrome second.

Visual direction: graphite surfaces, original thin-line SVG icons, softly raised controls, a single blue handoff action, and restrained mint/amber state colors. The task drawer starts closed. The 40 px handoff bar and 23 px status row retain the previous picture height. Glass-like edges belong to the controls; no refraction or decorative layer obscures phone content.

Inspired by the Apple category in [优设美地](https://allan.xin/?library=components), especially [Apple Navbar V002](https://skiper-ui.com/preview/skiper75) and [GlassSurface](https://reactbits.dev/components/glass-surface). These were visual references only, not imported code. The Navbar component's source has separate access/license terms. Apple [Materials](https://developer.apple.com/design/human-interface-guidelines/materials) guidance reinforced the separation of controls and underlying content.

Original design brief: Build a calm macOS-style phone workspace. Preserve the full uncropped live view, immediate human takeover and truthful status. Put tasks in a collapsible drawer. Use neutral graphite layers, soft edge highlights and one blue action; reserve other colors for meaning. Keep icons readable, labels available, keyboard focus visible and reduced-motion preferences honored. Preserve input and ownership semantics. Showcase only explicitly labeled synthetic data.

## Tune

- Palette and spacing: `src/phone_harness/web/style.css`, tokens at the top.
- Icons and semantic labels: `src/phone_harness/web/index.html`.
- Control logic: `src/phone_harness/web/app.js`.
- Ephemeral action cues: `src/phone_harness/web/actions.js`; existing 450/900 ms manual/assistant timings retained.
- Preview: `python3 tools/preview.py`; uses the real UI, a synthetic in-memory state and an original SVG phone screen. Does not open a phone connection.

There is no new frontend framework, font download, animation dependency or analytics request.
