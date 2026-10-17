# Light workspace

A white desktop workspace centered on the real phone, with soft neutral sidebars and clear text hierarchy. The task drawer starts closed; tools stay in a narrow, integrated right column. The 40 px handoff bar and 23 px status row preserve the phone picture height.

Visual reference: the light desktop screenshot on the official [Codex product page](https://openai.com/codex/), inspected on 2026-10-17. We borrow the restraint of its sidebar, monochrome primary action, simple typography and fine dividers. No OpenAI brand assets, screenshots, fonts or component source are included. Phone Harness icons and CSS are original.

The previous 0.6.0 Graphite design was rejected in local review. This revision intentionally uses light mode, including the native macOS title bar and loading screen. It is not tied to the operating system's dark-mode preference.

Design brief: White control surfaces, a very light neutral phone stage, readable charcoal text and a quiet selected row. Reserve green and amber for meaningful state. Remove ornamental English headings and floating dark docks. Keep the full uncropped phone view, immediate human takeover, honest device readings, visible keyboard focus and reduced-motion support. Status details remain behind compact icons. Showcase only explicitly labeled synthetic data.

## Tune

- Palette and spacing: `src/phone_harness/web/style.css`, tokens at the top.
- Icons and semantic labels: `src/phone_harness/web/index.html`.
- Native appearance: `src/phone_harness/Desktop.swift`.
- Control logic: `src/phone_harness/web/app.js`.
- Ephemeral action cues: `src/phone_harness/web/actions.js`; existing 450/900 ms manual/assistant timings retained.
- Preview: `python3 tools/preview.py`; uses the real UI, a synthetic in-memory state and an original SVG phone screen. Does not open a phone connection.

Existing plain HTML/CSS, native system typography and original SVG icons provide the required controls without a new framework, font download, animation dependency or analytics request.
