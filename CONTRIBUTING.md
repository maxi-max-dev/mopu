# Contributing

Phone Harness is an early local-first prototype. Small fixes with reproducible evidence are welcome. Start with an issue for transport, ownership or permission changes.

## Develop without a phone

```sh
python3 -m venv .venv
.venv/bin/pip install -e .
python3 tools/preview.py
# http://127.0.0.1:18797 — explicit synthetic UI fixture, no ADB or phone access
```

The preview uses the real HTML/CSS/frontend and a small in-memory fixture server. It is for presentation and UI checks, not proof of phone actions or queue semantics. Do not expose it publicly.

Run the software checks:

```sh
.venv/bin/python -m unittest discover -s tests -v
node --check src/phone_harness/web/app.js
node --check src/phone_harness/web/actions.js
node --test tests/actions.test.cjs
node --test integrations/openclaw/bridge.test.mjs
.venv/bin/pip wheel --no-deps . -w dist
```

CI uses fake devices and does not establish Android, acoustic or physical-display compatibility. Native builds require Xcode Command Line Tools; phone acceptance requires an owner-authorized test device.

## Review contract

- Keep takeover, lease invalidation, fresh-observation guards and no-input-replay behavior intact.
- Never replace an unknown/stale sensor reading with a reassuring default.
- Do not change the user’s model, send messages, or start new conversations from a queue item.
- Preserve original state before changing setup or recovery behavior.
- UI work must retain the full uncropped phone view, visible handoff, physical-screen indicator and accessible controls. Check at 1280 × 828 and 850 × 618, including landscape and open dialogs.
- Report software, simulation, installation and real-device evidence separately in the PR.
- Do not include private state, serials, tokens, task text or real phone screenshots. The public preview is original synthetic content.

Include what changed, why and how it was validated. Contributors retain copyright to their work and contribute under the repository's MIT license. Third-party code/assets require an identified compatible license and attribution.
