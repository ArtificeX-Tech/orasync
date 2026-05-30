# orasync

`orasync` is a small OpenRaster (`.ora`) sync helper for editor extensions.
It keeps the sync engine editor-neutral so Krita, GIMP, and future ArtificeX
extensions can call the same code.

The project model is:

1. The editor owns a normal `.ora` file on disk.
2. `orasync` imports that `.ora` into an unpacked Git working tree.
3. Git tracks the unpacked OpenRaster payload (`mimetype`, `stack.xml`, layer
   images, thumbnails, and related files).
4. Remote changes are exported back into the `.ora` file.

`orasync` can configure Git remotes, but it does not store credentials. SSH
keys, access tokens, credential helpers, and keychains remain owned by Git and
the operating system. If `git pull` and `git push` work in a terminal for the
repo, `orasync` should be able to use the same setup.

## Install for local testing

From this repository:

```bash
python -m pip install -e .
```

Then verify:

```bash
orasync --help
```

## Basic CLI flow

Create or bind a project repo:

```bash
orasync init /path/to/project-repo \
  --ora /path/to/image.ora \
  --remote git@github.com:example/art-project.git \
  --branch main
```

Import an existing `.ora` into the repo:

```bash
orasync import /path/to/image.ora /path/to/project-repo --force
```

Commit and push the unpacked project:

```bash
orasync commit-push /path/to/project-repo --message "Krita save"
```

Pull remote changes and export a fresh `.ora`:

```bash
orasync pull-export /path/to/project-repo --output /path/to/image.ora
```

Run the prototype watcher:

```bash
orasync watch /path/to/project-repo --ora /path/to/image.ora --json
```

Watcher defaults:

- local file poll: 2 seconds
- remote fetch poll: 5 seconds
- remote: `origin`
- branch: `main`
- output: human text unless `--json` is set

## Prototype sync policy

This first version uses deterministic overwrite sync. It does not provide a
merge UI or conflict editor.

- If the local `.ora` changes, `orasync` imports it, commits it, and pushes it.
- If the remote branch changes, `orasync` resets the unpacked repo to the remote
  branch and exports the result to the `.ora`.
- If a push is rejected because the remote changed first, the remote copy wins
  for this prototype.

This is intentionally simple so the pipeline can be tested end-to-end. The
future ArtificeX extension should own richer project state, user confirmation,
and conflict presentation.

## Local metadata

`orasync` stores local runtime metadata in:

```text
PROJECT/.orasync/
```

`orasync init` also adds `.orasync/` to the project `.gitignore` so absolute
local file paths and watch state are not committed.

## Krita POC

The Krita proof-of-concept lives in:

```text
examples/krita-poc/
```

Krita 6 requires Qt6 Python bindings for Python plugins. On Arch/Parabola-style
systems, install:

```bash
sudo pacman -S python-pyqt6
```

Copy `orasync_poc.desktop` and the `orasync_poc/` package into Krita's Python
plugin directory, then enable "Orasync POC" in Krita's Python Plugin Manager.

The POC adds actions under the Scripts/Tools menu area:

- configure the project repo and `.ora` path;
- start live sync for the active document;
- stop live sync;
- export and sync the active document immediately.

Live sync checks the active Krita document every 2 seconds. When the document
becomes modified, the POC exports it to the configured `.ora`, runs
`orasync sync`, and clears Krita's modified flag. It also checks Git every 5
seconds and reloads the active Krita document when either the remote sync or
another local editor updates the configured `.ora`.

## GIMP POC

The GIMP proof-of-concept lives in:

```text
examples/gimp-poc/orasync-poc/
```

Install it as a GIMP 3 Python plug-in. The POC exposes small menu procedures
under `Filters -> Development -> Orasync`. Use "Start Orasync Live Sync" on the
image you want to sync.

On Linux, make the plug-in file executable after copying it into GIMP's plug-in
directory:

```bash
chmod +x orasync-poc.py
```

The GIMP live-sync window keeps a 2-second editor poll and a 5-second Git poll
alive while it is open. When the image becomes dirty, the POC exports it with
GIMP's OpenRaster exporter, runs `orasync sync`, and marks the image clean.
When another client updates the configured `.ora`, the POC loads the new ORA in
GIMP and closes the old clean image.

## Development

Run tests:

```bash
python -m pytest
```
