#!/bin/sh
# Push main and update a server that runs valheimdisplay from a checkout of this repository
# (the systemd user service in this folder).
#
#   deploy/update.sh <ssh host> [--rebuild]
#
# --rebuild  also regenerate the site's data now (world map, places, ...), for changes to the tools.
#            Without it the server only rebuilds when the world is next saved and the version changed.
# DIR        the checkout on the server (default: valheimdisplay in the home folder)
set -eu
host=${1:?usage: deploy/update.sh <ssh host> [--rebuild]}
rebuild=${2:-}
dir=${DIR:-valheimdisplay}

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "uncommitted changes; commit them first" >&2
  exit 1
fi
git push origin main
want=$(git rev-parse HEAD)

ssh "$host" "set -e
  cd $dir
  git pull --ff-only --quiet
  test \"\$(git rev-parse HEAD)\" = $want || { echo 'the server is not on the commit just pushed' >&2; exit 1; }
  if [ '$rebuild' = --rebuild ]; then rm -f data/build-state.json; fi
  systemctl --user restart valheimdisplay
  sleep 3
  systemctl --user is-active --quiet valheimdisplay || { journalctl --user -u valheimdisplay -n 30 --no-pager; exit 1; }
  echo \"updated to \$(git log --oneline -1)\""
if [ "$rebuild" = --rebuild ]; then
  echo "rebuilding in the background; follow it with: ssh $host journalctl --user -fu valheimdisplay"
fi
