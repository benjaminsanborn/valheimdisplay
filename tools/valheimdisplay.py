"""valheimdisplay: a 3D website of your Valheim server's world, kept up to date as the server saves.

usage:
  valheimdisplay [options]              find the world, build the site, serve it, rebuild as the world changes
  valheimdisplay build [place ...]      build once and exit
  valheimdisplay detect                 show what was found (world, game files, server log) and exit

options (each can also go in valheimdisplay.toml in the data folder):
  --home DIR       data folder (default: valheimdisplay-data next to this program)
  --world DIR      the world's save folder, e.g. .../worlds_local/MyWorld
  --game DIR       the server's valheim_server_Data folder (or the game's valheim_Data)
  --log SOURCE     server log for player stats: a file path, journal:<systemd unit>, or none
  --port N         web server port (default 8080)
  --bind ADDR      web server address (default 0.0.0.0, everyone on the network)
"""
import email.utils
import html
import os
import runpy
import shutil
import subprocess
import sys
import threading
import time
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
import detect

VERSION = '0.2.0'
DEFAULTS = dict(world='', game='', server_log='', port=8080, bind='0.0.0.0', rebuild_minutes=60, players_minutes=3)
CONFIG_TEMPLATE = '''# valheimdisplay settings. Empty values are found automatically; run `valheimdisplay detect` to see what was found.

# The world's save folder (it holds _main.N.db2 / .chunks files), e.g.
#   Windows: C:\\\\Users\\\\you\\\\AppData\\\\LocalLow\\\\IronGate\\\\Valheim\\\\worlds_local\\\\MyWorld
#   Linux:   /home/you/.config/unity3d/IronGate/Valheim/worlds_local/MyWorld
world = ""

# The server's valheim_server_Data folder (the game's valheim_Data works too). Models and textures come from here.
game = ""

# Where player joins and deaths are read from: a log file (start the server with -logFile <path>),
# "journal:valheim.service" for a systemd service, or "none".
server_log = ""

# Web server
port = 8080
bind = "0.0.0.0"

# Rebuild at most this often when the world has been saved (a rebuild takes a few minutes of CPU)
rebuild_minutes = 60
# Refresh who's online / player stats this often
players_minutes = 3
'''


def bundled(*p):
    """A file shipped with the program (the website)."""
    base = getattr(sys, '_MEIPASS', None) or os.path.dirname(common.TOOLS)
    return os.path.join(base, *p)


# ---------------------------------------------------------------- settings
def parse_args(argv):
    opts, rest = {}, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith('--') and a[2:] in ('home', 'world', 'game', 'log', 'port', 'bind'):
            if i + 1 >= len(argv):
                sys.exit(f'{a} needs a value')
            opts[a[2:]] = argv[i + 1]
            i += 2
        elif a in ('-h', '--help'):
            print(__doc__)
            sys.exit(0)
        elif a == '--version':
            print(VERSION)
            sys.exit(0)
        else:
            rest.append(a)
            i += 1
    return opts, rest


def default_home():
    if common.FROZEN:
        return os.path.join(os.path.dirname(os.path.abspath(sys.executable)), 'valheimdisplay-data')
    return os.path.dirname(common.TOOLS)   # running from source: the repository


def settings(opts):
    home = os.path.abspath(opts.get('home') or os.environ.get('VALHEIM_DISPLAY_HOME') or default_home())
    os.makedirs(home, exist_ok=True)
    path = os.path.join(home, 'valheimdisplay.toml')
    if not os.path.exists(path):
        open(path, 'w', encoding='utf-8').write(CONFIG_TEMPLATE)
    try:
        cfg = {**DEFAULTS, **tomllib.load(open(path, 'rb'))}
    except tomllib.TOMLDecodeError as e:
        sys.exit(f'{path}: {e}')
    for k, ck in (('world', 'world'), ('game', 'game'), ('log', 'server_log'), ('port', 'port'), ('bind', 'bind')):
        if opts.get(k):
            cfg[ck] = opts[k]
    cfg['port'] = int(cfg['port'])
    for k in ('world', 'game'):
        if cfg[k]:
            cfg[k] = os.path.abspath(os.path.expanduser(cfg[k]))
    log = cfg['server_log']
    if log and not log.startswith('journal:') and log.lower() not in ('none', 'off'):
        cfg['server_log'] = os.path.abspath(os.path.expanduser(log))
    cfg['home'] = home
    notes = {}
    if not cfg['world']:
        cfg['world'], notes['world'] = detect.find_world()
    if not cfg['game']:
        cfg['game'], notes['game'] = detect.find_game()
    if not cfg['server_log']:
        cfg['server_log'], notes['server_log'] = detect.find_log()
    cfg['notes'] = notes
    return cfg


def show(cfg):
    for k in ('world', 'game', 'server_log'):
        note = cfg['notes'].get(k, 'from settings')
        print(f'  {k:11s} {cfg[k] or "-"}  ({note})')
    print(f'  {"data":11s} {cfg["home"]}')


def check(cfg):
    problems = []
    if not detect.is_world(cfg['world']):
        problems.append('No world save found. Set `world` in valheimdisplay.toml to the folder holding _main.N.db2 '
                        '(…/IronGate/Valheim/worlds_local/<World>). Older single-file saves (World.db) are not supported.')
    if not detect.is_game_data(cfg['game']):
        problems.append('No Valheim game files found. Set `game` to the server\'s valheim_server_Data folder '
                        '(or the game\'s valheim_Data). They are read for models and textures; nothing is copied out of this machine.')
    return problems


def child_env(cfg):
    env = dict(os.environ, VALHEIM_DISPLAY_HOME=cfg['home'], VALHEIM_GAME_DATA=cfg['game'] or '',
               VALHEIM_SERVER_LOG=cfg['server_log'] or 'none', PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    return env


def install_site(home):
    """Copy the website (html/js) into the data folder; generated files go in web/assets beside it."""
    src, dst = bundled('web'), os.path.join(home, 'web')
    if os.path.realpath(src) == os.path.realpath(dst):
        return
    os.makedirs(dst, exist_ok=True)
    for dp, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != 'assets']
        for f in files:
            s = os.path.join(dp, f)
            d = os.path.join(dst, os.path.relpath(s, src))
            os.makedirs(os.path.dirname(d), exist_ok=True)
            shutil.copy2(s, d)


# ---------------------------------------------------------------- keeping it up to date
def save_signature(world):
    oks = [os.path.join(world, f) for f in os.listdir(world) if f.startswith('_main.') and f.endswith('.ok')]
    return max(((os.path.getmtime(f), f) for f in oks), default=None)


def mirror(src, dst):
    """Copy the save to our own folder so the server can keep saving while we read.
    The .ok markers go last: a save only counts once its marker is there."""
    os.makedirs(dst, exist_ok=True)
    names = [f for f in os.listdir(src) if os.path.isfile(os.path.join(src, f))]
    for f in sorted(names, key=lambda f: f.endswith('.ok')):
        s, d = os.path.join(src, f), os.path.join(dst, f)
        st = os.stat(s)
        if not os.path.exists(d) or os.path.getsize(d) != st.st_size or int(os.path.getmtime(d)) != int(st.st_mtime):
            shutil.copy2(s, d)
    for f in os.listdir(dst):
        if f not in names and os.path.isfile(os.path.join(dst, f)):
            os.remove(os.path.join(dst, f))


class Updater:
    def __init__(self, cfg):
        self.cfg = cfg
        self.env = child_env(cfg)
        self.status = []          # recent output, for the "building" page
        self.state = 'starting'
        self.lock = threading.Lock()

    def log(self, line):
        line = line.rstrip()
        if not line:
            return
        print(line, flush=True)
        self.status = (self.status + [line])[-12:]

    def run(self, name, *args):
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = subprocess.BELOW_NORMAL_PRIORITY_CLASS
        else:
            kw['preexec_fn'] = lambda: os.nice(10)
        p = subprocess.Popen(common.tool_cmd(name, *args), env=self.env, cwd=self.cfg['home'], stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, **kw)
        for raw in p.stdout:
            self.log(raw.decode('utf-8', 'replace'))
        if p.wait():
            raise RuntimeError(f'{name} failed (exit {p.returncode})')

    def build(self, places=()):
        with self.lock:
            home, world = self.cfg['home'], os.path.join(self.cfg['home'], 'data', 'world')
            self.state = 'building'
            t0 = time.time()
            self.log(f'[{time.strftime("%H:%M")}] copying the world save')
            mirror(self.cfg['world'], world)
            if not os.path.exists(os.path.join(home, 'data', 'history', 'built.json')):
                old = detect.backups(self.cfg['world'])
                if old:
                    names = os.path.join(home, 'data', 'prefab_names.json')
                    if not os.path.exists(names):
                        self.log('indexing prefab names...')
                        self.run('prefab_names', self.cfg['game'], names)
                    self.log(f'filling in the timelapse from {len(old)} backups')
                    self.run('history', 'backfill', *old)
            self.run('build', *places)
            self.state = 'ready'
            self.log(f'[{time.strftime("%H:%M")}] built in {time.time() - t0:.0f}s')

    def players(self):
        with self.lock:
            try:
                self.run('players')
            except RuntimeError as e:
                self.log(f'players: {e}')

    def played_since(self, t):
        """Has anyone been on the server since t? (Without player stats, assume so.) An empty server still
        saves every half hour; rebuilding then would only burn CPU next to the game."""
        path = os.path.join(self.cfg['home'], 'web', 'assets', 'players.json')
        if self.cfg['server_log'] in ('', 'none', None) or not os.path.exists(path):
            return True
        try:
            import datetime as dt
            import json
            data = json.load(open(path, encoding='utf-8'))
            return bool(data.get('online')) or any(dt.datetime.fromisoformat(p['last']).timestamp() > t for p in data.get('players', []))
        except (OSError, ValueError, KeyError):
            return True

    def loop(self):
        state_path = os.path.join(self.cfg['home'], 'data', 'build-state.json')
        last_sig, last_build, last_players = None, 0, time.time()
        try:   # restarting the program doesn't rebuild an up-to-date site
            import json
            st = json.load(open(state_path))
            if os.path.exists(index_path(self.cfg['home'])) and st.get('version') == VERSION:
                last_sig, last_build = tuple(st['sig']), st['time']
                self.state = 'ready'
        except (OSError, ValueError, KeyError, TypeError):
            pass
        while True:
            try:
                sig = save_signature(self.cfg['world'])
                due = time.time() - last_build >= self.cfg['rebuild_minutes'] * 60
                if sig != last_sig and (last_sig is None or (due and self.played_since(last_build))):
                    self.build()
                    last_sig, last_build, last_players = sig, time.time(), time.time()
                    import json
                    json.dump(dict(sig=list(sig), time=last_build, version=VERSION), open(state_path, 'w'))
                elif time.time() - last_players >= self.cfg['players_minutes'] * 60:
                    self.players()
                    last_players = time.time()
            except Exception as e:   # keep serving the last good build
                self.state = 'ready' if os.path.exists(index_path(self.cfg['home'])) else 'failed'
                self.log(f'update failed: {e} (trying again in 5 minutes)')
                time.sleep(270)
            time.sleep(30)


def index_path(home):
    return os.path.join(home, 'web', 'assets', 'regions', 'index.json')


# ---------------------------------------------------------------- web server
TYPES = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.json': 'application/json',
         '.css': 'text/css', '.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp', '.svg': 'image/svg+xml',
         '.glb': 'model/gltf-binary', '.bin': 'application/octet-stream', '.ico': 'image/x-icon', '.txt': 'text/plain'}


_gz_cache = {}


def compressed(path):
    """gzip of a small text file, kept until the file changes."""
    key = (path, os.path.getmtime(path))
    if key not in _gz_cache:
        import gzip
        _gz_cache[key] = gzip.compress(open(path, 'rb').read(), 6)
    return _gz_cache[key]


def make_handler(web, updater):
    web = os.path.realpath(web)

    class Handler(BaseHTTPRequestHandler):
        server_version = f'valheimdisplay/{VERSION}'

        def log_message(self, *a):
            pass

        def do_HEAD(self):
            self.do_GET(body=False)

        def do_GET(self, body=True):
            path = unquote(urlsplit(self.path).path)
            if path.endswith('/'):
                path += 'index.html'
            if path == '/index.html' and not os.path.exists(index_path(os.path.dirname(web))):
                return self.building(body)
            full = os.path.realpath(os.path.join(web, path.lstrip('/')))
            if not full.startswith(web + os.sep) or not os.path.isfile(full):
                return self.send_error(404)
            send, enc, data = full, None, None
            gz = full + '.gz'
            ext = os.path.splitext(full)[1].lower()
            if 'gzip' in self.headers.get('Accept-Encoding', ''):
                if os.path.exists(gz) and os.path.getmtime(gz) >= os.path.getmtime(full):
                    send, enc = gz, 'gzip'
                elif ext in ('.html', '.js', '.json', '.css', '.txt', '.svg'):
                    data, enc = compressed(full), 'gzip'
            mtime = int(os.path.getmtime(send))
            since = self.headers.get('If-Modified-Since')
            if since:
                try:
                    if int(email.utils.parsedate_to_datetime(since).timestamp()) >= mtime:
                        self.send_response(304)
                        self.end_headers()
                        return
                except (TypeError, ValueError):
                    pass
            size = len(data) if data is not None else os.path.getsize(send)
            self.send_response(200)
            self.send_header('Content-Type', TYPES.get(os.path.splitext(full)[1].lower(), 'application/octet-stream'))
            self.send_header('Content-Length', str(size))
            self.send_header('Last-Modified', email.utils.formatdate(mtime, usegmt=True))
            self.send_header('Cache-Control', 'no-cache')   # always revalidate; unchanged files come back as 304
            if enc:
                self.send_header('Content-Encoding', enc)
                self.send_header('Vary', 'Accept-Encoding')
            self.end_headers()
            if body and data is not None:
                self.wfile.write(data)
            elif body:
                with open(send, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)

        def building(self, body):
            failed = updater.state == 'failed'
            lines = '\n'.join(html.escape(l) for l in updater.status) or 'starting…'
            page = f'''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Valheim world</title>{'' if failed else '<meta http-equiv="refresh" content="5">'}
<style>body{{background:#1b1915;color:#e8dcc0;font:16px system-ui,sans-serif;margin:0;padding:40px 16px;display:flex;justify-content:center}}
main{{max-width:720px;width:100%}}pre{{background:#000a;padding:12px;border-radius:8px;white-space:pre-wrap;font-size:13px;color:#bfb49a}}</style></head>
<body><main><h1>{'The build failed' if failed else 'Building the world…'}</h1>
<p>{'See the messages below and the program\'s console.' if failed else 'The first build reads the game files for models and textures and takes a few minutes. This page refreshes by itself.'}</p>
<pre>{lines}</pre></main></body></html>'''.encode()
            self.send_response(503 if failed else 200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(page)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            if body:
                self.wfile.write(page)

    return Handler


# ---------------------------------------------------------------- main
def main():
    if len(sys.argv) > 2 and sys.argv[1] == '__tool':   # the executable running one of its tools
        name = sys.argv[2]
        sys.argv = [name, *sys.argv[3:]]
        runpy.run_module(name, run_name='__main__', alter_sys=True)
        return
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError):
            pass
    opts, rest = parse_args(sys.argv[1:])
    cmd = rest[0] if rest else 'serve'
    if cmd == 'selftest':   # the packaged program has everything it needs
        import numpy, scipy.ndimage, scipy.spatial, PIL.Image, UnityPy, texture2ddecoder, etcpak  # noqa: F401
        import export_models, export_region, history, places, players, terrain  # noqa: F401
        assert os.path.isfile(bundled('web', 'index.html')) and os.path.isfile(bundled('web', 'vendor', 'three', 'build', 'three.module.min.js'))
        print(f'ok: numpy {numpy.__version__}, UnityPy {UnityPy.__version__}')
        return
    print(f'valheimdisplay {VERSION}')
    cfg = settings(opts)
    show(cfg)
    if cmd == 'detect':
        return
    problems = check(cfg)
    if problems:
        print()
        for p in problems:
            print('!', p)
        print(f'\nSettings file: {os.path.join(cfg["home"], "valheimdisplay.toml")}')
        if common.FROZEN and os.name == 'nt':
            input('Press Enter to close.')
        sys.exit(1)
    install_site(cfg['home'])
    updater = Updater(cfg)
    if cmd == 'build':
        updater.build(rest[1:])
        return
    if cmd != 'serve':
        sys.exit(__doc__)
    server = ThreadingHTTPServer((cfg['bind'], cfg['port']), make_handler(os.path.join(cfg['home'], 'web'), updater))
    host = 'localhost' if cfg['bind'] in ('0.0.0.0', '::', '') else cfg['bind']
    print(f'\nServing http://{host}:{cfg["port"]}/  (Ctrl+C to stop)\n', flush=True)
    threading.Thread(target=updater.loop, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
