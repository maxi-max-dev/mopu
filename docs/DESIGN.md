# Centered phone workspace

A light desktop workspace whose phone stays on the horizontal centerline of the entire window. The full-width stage is independent of the left task drawer. Tools attach to the phone’s right edge with a 16 px gap. A 44 px header holds ownership and takeover; the compact 26 px status row holds device details. The redundant current-task footer is removed, giving the picture more height.

Visual reference: the light desktop screenshot on the official [Codex product page](https://openai.com/codex/), inspected on 2026-10-17. We borrow the restraint of its sidebar, monochrome primary action, simple typography and fine dividers. No OpenAI brand assets, screenshots, fonts or component source are included. Phone Harness icons and CSS are original.

The previous 0.6.0 Graphite design was rejected in local review. Version 0.6.1 changed the palette; 0.7.0 changes the composition. Light mode includes the native macOS title bar and loading screen and is independent of the operating system theme.

Design brief: White control surfaces, a very light neutral phone stage, readable charcoal text and a quiet selected row. Reserve green and amber for meaningful state. Remove ornamental English headings and floating dark docks. Opening tasks never reflows or shifts the phone. If the drawer cannot fit beside it, use a temporary scrim and make covered video/tools inert; close via the drawer arrow, background or Escape. Focus view hides the task drawer and status row while keeping takeover available. Task rows carry order, progress and results without duplicating them under the phone. Keep the full uncropped phone view, immediate human takeover, honest device readings, visible keyboard focus and reduced-motion support. Status details remain behind compact icons. Showcase only explicitly labeled synthetic data.

## Tune

- Palette and spacing: `src/phone_harness/web/style.css`, tokens at the top.
- Icons and semantic labels: `src/phone_harness/web/index.html`.
- Native appearance: `src/phone_harness/Desktop.swift`.
- Control logic: `src/phone_harness/web/app.js`.
- Ephemeral action cues: `src/phone_harness/web/actions.js`; existing 450/900 ms manual/assistant timings retained.
- Preview: `python3 tools/preview.py`; uses the real UI, a synthetic in-memory state and an original SVG phone screen. Does not open a phone connection.

Existing plain HTML/CSS, native system typography and original SVG icons provide the required controls without a new framework, font download, animation dependency or analytics request.
