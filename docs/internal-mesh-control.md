# Internal Operator UI

`MeshControl` was the Purna Labs OS companion UI from the source repository. That app is not present in `orbital-mesh`, so active Compose files no longer build a `mesh-ui` sidecar or reference `purnaOS-main`.

The supported operator surface is the browser UI served by the Mesh process:

```text
http://127.0.0.1:8787
```

For local development:

```bash
python3 run_server.py
```

For Compose:

```bash
docker compose up --build -d
```

Keep this boundary explicit. Do not reintroduce `mesh-ui` docs or Compose services unless the UI source is restored in this repository.
