# Valheim world viewer

An isometric 3D website of a Valheim dedicated server's world: your bases rendered with the
game's own models on the real terrain, a round world map of what's been explored, and portals
you can click through.

It reads the server's save directly (the chunked save format, world version 40+), regenerates the
terrain from the seed, and pulls models/textures out of the server's game files.

## How it works

| Step | Code |
| --- | --- |
| Read the save (`_main.N.chunks/.db2/.fwl2` + `*.chunk`) | `tools/vworld.py` |
| Choose which places to render | `tools/places.py` (rule documented there) |
| Terrain: port of the world generator + terrain edits | `tools/terrain.py`, `tools/export_region.py` |
| Models and textures from the game's asset bundles | `tools/export_models.py`, `tools/export_terrain_textures.py` |
| World map with explored areas | `tools/export_worldmap.py` |
| Everything, in order | `tools/build.py` |
| Website (three.js) | `web/` |

Nothing extracted from the game is committed: `data/` and `web/assets/` are generated locally
(see `.gitignore`).

## Running it

```sh
./update.sh                     # copy the save and rebuild everything
cd web && python3 -m http.server 8765
```

`update.sh` settings are at the top of the file (where the save and game files live).
Name places or change their size in `regions.json`.

## Server deployment

On the game server (`deploy/`):

- `valheimdisplay.caddy` → `/etc/caddy/sites/` serves https://valheim.goku.host
  from `/var/www/valheimdisplay`.
- `valheimdisplay-update.{service,timer}` → `~/.config/systemd/user/` rebuilds every night at 04:30
  (`systemctl --user list-timers`, logs: `journalctl --user -u valheimdisplay-update`).
