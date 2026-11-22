# Valheim world viewer

An isometric 3D website of a Valheim server's world: your bases rendered with the game's own
models on the real terrain, a round world map of what's been explored, portals you can click
through, a timelapse of how the world grew, weather that fits each biome, night mode, boss
progress, ships, and who's been playing.

It reads the world save directly (the chunked save format, Valheim 0.220+), regenerates the
terrain from the seed, and pulls models and textures out of the game files already on your
machine. Nothing from the game is shipped with it.

## Running it next to your server

1. Download the program for your system from the [releases page](../../releases)
   (`valheimdisplay-windows-x64.exe`, `-linux-x64`, `-linux-arm64`, `-macos-arm64`, `-macos-x64`).
2. Put it on the machine that runs the Valheim server and start it:
   - Windows: double-click it (Windows may warn that it's from an unknown publisher: *More info → Run anyway*).
   - Linux / macOS: `chmod +x valheimdisplay-* && ./valheimdisplay-linux-x64`
     (macOS: the first time, right-click → Open, or `xattr -d com.apple.quarantine valheimdisplay-macos-*`).
3. Open http://localhost:8080 (or `http://<server's address>:8080` from another computer on your network).

The first build takes a few minutes: it reads the game files for models and textures. After that it
rebuilds by itself when the server saves (at most once an hour, and only if someone has played).

It finds the world, the game files and the server log by itself in the usual places: a running
`valheim_server` process (its install folder and `-world` / `-savedir` / `-logFile` options),
Steam libraries, and the default save folders. `valheimdisplay detect` shows what it found.
If it can't find something, set it in `valheimdisplay-data/valheimdisplay.toml` (created on first run):

```toml
world = "C:\\Users\\you\\AppData\\LocalLow\\IronGate\\Valheim\\worlds_local\\MyWorld"
game = "C:\\Program Files (x86)\\Steam\\steamapps\\common\\Valheim dedicated server\\valheim_server_Data"
server_log = "C:\\valheim\\server.log"     # or "journal:valheim.service", or "none"
port = 8080
```

Or on the command line: `valheimdisplay --world DIR --game DIR --log FILE --port 8080`.

**Player stats** (hours, deaths, who's online) come from the server's log. On Linux with a
systemd service that's found automatically. Otherwise start the server with
`-logFile <path>` (add it to `start_headless_server.bat` / `start_server.sh`) and the viewer picks it up.

**Places** are found automatically from what's been built (see `tools/places.py`). To name them
or change their size, add a `regions.json` to the data folder:

```json
[{"slug": "main", "title": "Main base", "x": 705, "z": -113, "radius": 150}]
```

**The timelapse** starts from Valheim's own backups of the world (`<World>_backup_*` next to the
save) and adds a snapshot each time it rebuilds.

**Sharing it outside your network:** put it behind a reverse proxy (Caddy, nginx) or forward the port.
Note that player names and play times are visible to anyone who can open the site.

### Docker

```sh
docker build -t valheimdisplay .
docker run -d -p 8080:8080 \
  -v /path/to/worlds_local/MyWorld:/world:ro \
  -v /path/to/valheim_server_Data:/game:ro \
  -v valheimdisplay-data:/data valheimdisplay
```

## How it works

| Step | Code |
| --- | --- |
| The program: find the server, rebuild when it saves, serve the site | `tools/valheimdisplay.py`, `tools/detect.py` |
| Read the save (`_main.N.chunks/.db2/.fwl2` + `*.chunk`) | `tools/vworld.py` |
| Choose which places to render | `tools/places.py` (rule documented there) |
| Terrain: port of the world generator + terrain edits | `tools/terrain.py`, `tools/rivers.py`, `tools/export_region.py` |
| Models and textures from the game's asset bundles | `tools/export_models.py`, `tools/export_terrain_textures.py`, `tools/export_icons.py` |
| World map with explored areas | `tools/export_worldmap.py` |
| Timelapse history (pieces, explored zones, bosses, in-game day) | `tools/history.py` |
| Players: hours, deaths, who's online (from the server log) | `tools/players.py` |
| One full build, in order | `tools/build.py` |
| Website (three.js, vendored in `web/vendor`) | `web/` |
| Weather per biome | `web/weather.js` |

Everything the program generates lives in its data folder: `data/` (world copy, history) and
`web/assets/` (terrain, models, textures). None of it is committed: it comes from Iron Gate's game files.

## Developing

```sh
uv sync
uv run python tools/valheimdisplay.py          # same as the executable; the repository is the data folder
uv run python tools/valheimdisplay.py build    # one build, no server
uv run pyinstaller valheimdisplay.spec         # the executable, in dist/
```

GitHub Actions builds the executables for every platform on each push to `main`
(`.github/workflows/release.yml`); pushing a `v*` tag publishes them as a release.
To fill in history from old save backups: `uv run python tools/history.py backfill <backup .tar.gz or folder> ...`.

## valheim.goku.host

The server runs `deploy/valheimdisplay.service` (a systemd user service running the program from
this checkout, on 127.0.0.1:8080) behind Caddy (`deploy/valheimdisplay.caddy`).
Logs: `journalctl --user -u valheimdisplay`.
