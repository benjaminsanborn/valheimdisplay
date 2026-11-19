#!/bin/sh
# Copy the latest world save and rebuild the viewer data.
#
#   ./update.sh            rebuild every place
#   ./update.sh main farm  rebuild just those places
#
# Settings (environment variables):
#   VALHEIM_SSH        ssh host to copy the save from; empty = the save is on this machine (default: ubuntu)
#   VALHEIM_WORLD_DIR  the world's save folder         (default: ~/.config/unity3d/IronGate/Valheim/worlds_local/Dedicated)
#   VALHEIM_GAME_DATA  the server's valheim_server_Data folder, for models/textures (default: data/game/gamedata)
#   VALHEIM_PUBLISH    folder the web server serves; the finished site is copied there (default: none)
set -e
cd "$(dirname "$0")"
SSH_HOST=${VALHEIM_SSH-ubuntu}
WORLD_DIR=${VALHEIM_WORLD_DIR:-"$HOME/.config/unity3d/IronGate/Valheim/worlds_local/Dedicated"}
mkdir -p data/world
# Work from a copy: the server keeps saving while we read. --delete drops old chunk versions;
# the parser only reads the newest save that has its _main.N.ok marker.
if [ -n "$SSH_HOST" ]; then
  rsync -a --delete "$SSH_HOST:${VALHEIM_WORLD_DIR:-.config/unity3d/IronGate/Valheim/worlds_local/Dedicated}/" data/world/
else
  rsync -a --delete "$WORLD_DIR/" data/world/
fi
UV=$(command -v uv || echo "$HOME/.local/bin/uv")
"$UV" run --frozen python tools/build.py "$@"
if [ -n "$VALHEIM_PUBLISH" ]; then
  rsync -a --delete web/ "$VALHEIM_PUBLISH/"
fi
