# Archived GPUI Experiment

The GPUI desktop operator console is archived here for provenance only.

- `mesh-gpui/` contains the former Rust desktop client.
- `Cargo.workspace.toml` and `Cargo.lock` are the former root Rust workspace files used only for the GPUI client.
- `gpui-operator-console.md` records the original architecture and hardening notes with archived status.

The active operator surface is the `meshapp/` Next static app, served by `run_server.py` from `meshapp/frontend/out` or launched through the zero-native shell. `web/` remains the Vite reference surface during migration.
