# Mopu 0.14 migration

Phone Harness is now **Mopu (莫普)**. The Python distribution and source package are `mopu`, the primary command is `mopu`, and the macOS app is `Mopu.app`. The repository is https://github.com/maxi-max-dev/mopu.

## Existing installations

When the console has no active task, stop its server gracefully and back up the existing environment and private state. Remove the old distribution metadata first (`python -m pip uninstall phone-harness`), then install the new package in that same environment (`python -m pip install .`) and run `mopu install-app`. Do not uninstall the old distribution after installing Mopu: the packages share the compatibility entry point. Both `mopu` and the retained `phone-harness` executable use the same implementation. Old `python -m phone_harness.cli` and imports remain supported by a compatibility namespace. Do not install the old distribution again over Mopu.

The default resolver reuses `~/.local/share/phone-harness` whenever that directory exists. Otherwise it uses `~/.local/share/mopu`. Explicit `--state PATH` always wins. If both directories exist, the legacy directory wins deliberately; use `--state` to select another installation. No configuration, credentials, receipts or task history are rewritten or merged. Keep the existing virtual environment path. Commands coordinate through the same endpoint and server lock; changing the name must not start a second phone controller.

Build the new app before archiving the old app. Both use the stable `local.phone-harness.console` bundle identifier and `PhoneHarnessWindow` preference key, preserving macOS identity and window settings. Existing installations may retain a `Phone Harness.app` symlink to `Mopu.app`.

## Stable integration contracts

Existing MCP configuration keys and launch paths remain valid. New configurations can use server name `mopu` and command `mopu`; do not enable both server entries simultaneously for the same assistant. Tool names `phone_*`, HTTP authentication header `X-Phone-Token`, `phone_harness_observation` / `phone_harness_step` receipt fields and device transport filenames stay unchanged. They are compatibility identifiers, not visible branding.

The OpenClaw adapter displays Mopu while retaining plugin ID `phone-harness` and its resume-service ID. Existing `plugins.entries.phone-harness` settings, allowlists, conversation identities and resume history therefore continue to work. New installations also use this stable ID. Its default directory selection matches the CLI. Updating adapter files does not reload a running gateway; the host must load them on its next normal restart.

Historical release notes and screenshots describe earlier versions; existing GitHub release tags are retained. The GitHub old repository URL redirects after repository rename.
