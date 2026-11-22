# Running it as a service behind a web server

An example of a permanent setup on a Linux server: the viewer runs as a systemd user service next to
the game server, and [Caddy](https://caddyserver.com) serves it on a domain with HTTPS.

1. Put the program (or a checkout of this repository) on the server.
2. `valheimdisplay.service` → `~/.config/systemd/user/valheimdisplay.service`. Edit `WorkingDirectory`
   and `ExecStart` if you use the downloaded program instead of a checkout:
   ```ini
   ExecStart=%h/valheimdisplay-linux-x64 --home %h/valheimdisplay-data --bind 127.0.0.1
   ```
   Then:
   ```sh
   systemctl --user daemon-reload
   systemctl --user enable --now valheimdisplay
   loginctl enable-linger $USER         # keep it running when you're logged out
   journalctl --user -u valheimdisplay  # its output
   ```
   For player stats from the game server's journal, the user needs to be able to read it
   (for example, by being in the `systemd-journal` or `adm` group).
3. `valheimdisplay.caddy`: replace the domain, then add it to Caddy's config and `systemctl reload caddy`.

The viewer sends its own cache headers and pre-compressed files, so the proxy only needs to pass
requests through.
