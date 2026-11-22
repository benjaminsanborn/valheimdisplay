"""Find a Valheim server's world save, its game files and its log, on Windows, Linux or macOS.

Each finder returns a path (or None) and a short note on how it was found. Looked at, in order:
  - a running valheim_server process (its install folder, and its -world / -savedir / -logFile options)
  - Steam libraries (the dedicated server, then the game itself)
  - the default save folders for each OS
"""
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys

SYSTEM = platform.system()   # 'Windows', 'Linux', 'Darwin'
HOME = os.path.expanduser('~')


# ---------------------------------------------------------------- the running server
def _server_processes():
    """[(exe path or None, argv list)] for running Valheim servers (and the game, which can host)."""
    found = []
    if SYSTEM == 'Linux':
        for d in glob.glob('/proc/[0-9]*'):
            try:
                argv = open(f'{d}/cmdline', 'rb').read().split(b'\0')
                argv = [a.decode(errors='replace') for a in argv if a]
                if not argv or not re.search(r'valheim(_server)?\.x86_64$', argv[0], re.I):
                    continue
                try:
                    exe = os.readlink(f'{d}/exe')
                except OSError:
                    exe = argv[0]
                found.append((exe, argv))
            except OSError:
                continue
    elif SYSTEM == 'Windows':
        ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^valheim(_server)?\\.exe$' } | "
              "Select-Object ExecutablePath, CommandLine | ConvertTo-Json")
        try:
            out = subprocess.run(['powershell', '-NoProfile', '-Command', ps], capture_output=True, text=True, timeout=20).stdout
            rows = json.loads(out) if out.strip() else []
            for r in rows if isinstance(rows, list) else [rows]:
                found.append((r.get('ExecutablePath'), _split_cmdline(r.get('CommandLine') or '')))
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    else:
        try:
            out = subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True, timeout=10).stdout
            for line in out.splitlines():
                if re.search(r'valheim(_server)?(\.app/Contents/MacOS/\S+|\.x86_64)?\b', line, re.I) and 'valheimdisplay' not in line:
                    argv = _split_cmdline(line)
                    found.append((argv[0] if argv else None, argv))
        except (OSError, subprocess.SubprocessError):
            pass
    return found


def _split_cmdline(s):
    return [a.strip('"') for a in re.findall(r'"[^"]*"|\S+', s)]


def _arg(argv, name):
    lower = [a.lower() for a in argv]
    if name.lower() in lower:
        i = lower.index(name.lower())
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


# ---------------------------------------------------------------- Steam
def _steam_roots():
    if SYSTEM == 'Windows':
        roots = [os.path.join(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'), 'Steam'),
                 os.path.join(os.environ.get('ProgramFiles', r'C:\Program Files'), 'Steam')]
    elif SYSTEM == 'Darwin':
        roots = [f'{HOME}/Library/Application Support/Steam']
    else:
        roots = [f'{HOME}/.steam/steam', f'{HOME}/.local/share/Steam', f'{HOME}/.steam/root',
                 f'{HOME}/.var/app/com.valvesoftware.Steam/.local/share/Steam', f'{HOME}/Steam']
    return [r for r in roots if os.path.isdir(r)]


def _steam_libraries():
    libs = []
    for root in _steam_roots():
        libs.append(root)
        vdf = os.path.join(root, 'steamapps', 'libraryfolders.vdf')
        if os.path.exists(vdf):
            libs += [p.replace('\\\\', '\\') for p in re.findall(r'"path"\s+"([^"]+)"', open(vdf, errors='replace').read())]
    out = []
    for l in libs:
        if os.path.isdir(l) and os.path.realpath(l) not in map(os.path.realpath, out):
            out.append(l)
    return out


# ---------------------------------------------------------------- game files
def is_game_data(path):
    return bool(path) and os.path.isfile(os.path.join(path, 'globalgamemanagers'))


def _data_dirs_in(install):
    """The *_Data folder(s) inside a Valheim install folder."""
    cands = [os.path.join(install, n) for n in ('valheim_server_Data', 'valheim_Data')]
    cands += [os.path.join(install, 'Valheim.app', 'Contents', 'Resources', 'Data'),
              os.path.join(install, 'Contents', 'Resources', 'Data')]
    return [c for c in cands if is_game_data(c)]


def find_game():
    for exe, _ in _server_processes():
        if exe:
            d = os.path.dirname(exe)
            for c in _data_dirs_in(d) + _data_dirs_in(os.path.dirname(os.path.dirname(d))):
                return c, 'from the running server'
    here = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, 'frozen', False) else __file__))
    for d in (os.getcwd(), here, os.path.dirname(here)):
        for c in _data_dirs_in(d):
            return c, 'next to this program'
    for lib in _steam_libraries():
        for name in ('Valheim dedicated server', 'Valheim'):
            for c in _data_dirs_in(os.path.join(lib, 'steamapps', 'common', name)):
                return c, f'Steam library {lib}'
    for d in (f'{HOME}/valheim', f'{HOME}/valheim-server', f'{HOME}/valheimserver', '/opt/valheim', '/home/steam/valheim',
              f'{HOME}/.steam/steamcmd/valheim', r'C:\valheim', r'C:\steamcmd\steamapps\common\Valheim dedicated server'):
        for c in _data_dirs_in(d):
            return c, 'common install folder'
    return None, 'not found'


# ---------------------------------------------------------------- world save
def save_roots():
    if SYSTEM == 'Windows':
        base = os.path.join(os.environ.get('USERPROFILE', HOME), 'AppData', 'LocalLow', 'IronGate', 'Valheim')
    elif SYSTEM == 'Darwin':
        base = f'{HOME}/Library/Application Support/IronGate/Valheim'
    else:
        base = f'{HOME}/.config/unity3d/IronGate/Valheim'
    return [base]


def is_world(path):
    return bool(path) and bool(glob.glob(os.path.join(glob.escape(path), '_main.*.ok')))


def _worlds_in(worlds_local):
    out = []
    for d in glob.glob(os.path.join(glob.escape(worlds_local), '*')):
        if os.path.isdir(d) and '_backup_' not in os.path.basename(d) and is_world(d):
            out.append(d)
    return sorted(out, key=lambda d: max(os.path.getmtime(f) for f in glob.glob(os.path.join(glob.escape(d), '_main.*.ok'))), reverse=True)


def find_world(name=None):
    """The world's save folder (…/worlds_local/<World>). With several worlds, the one the running server
    uses, else the most recently saved."""
    for _, argv in _server_processes():
        world = name or _arg(argv, '-world')
        savedir = _arg(argv, '-savedir')
        roots = [savedir] if savedir else save_roots()
        for r in roots:
            if world and is_world(os.path.join(r, 'worlds_local', world)):
                return os.path.join(r, 'worlds_local', world), 'from the running server'
    for r in save_roots():
        worlds = _worlds_in(os.path.join(r, 'worlds_local'))
        if name:
            worlds = [w for w in worlds if os.path.basename(w) == name]
        if worlds:
            return worlds[0], 'most recently saved world' if len(worlds) > 1 else 'default save folder'
    return None, 'not found'


def backups(world):
    """Older copies of the world kept by Valheim (…/<World>_backup_*), for filling in the timelapse."""
    parent, name = os.path.split(os.path.normpath(world))
    return sorted(d for d in glob.glob(os.path.join(glob.escape(parent), glob.escape(name) + '_backup_*')) if os.path.isdir(d))


# ---------------------------------------------------------------- server log
def find_log():
    """Where to read joins/deaths: a -logFile, else a systemd unit running the server."""
    for exe, argv in _server_processes():
        lf = _arg(argv, '-logFile') or _arg(argv, '-logfile')
        if lf:
            if not os.path.isabs(lf) and exe:
                lf = os.path.join(os.path.dirname(exe), lf)
            return lf, 'the running server\'s -logFile'
    if SYSTEM == 'Linux' and shutil.which('systemctl'):
        try:
            out = subprocess.run(['systemctl', 'list-units', '--all', '--type=service', '--no-legend', '--plain'],
                                 capture_output=True, text=True, timeout=10).stdout
            units = [l.split()[0] for l in out.splitlines() if l.strip() and re.search(r'valheim', l.split()[0], re.I)
                     and 'valheimdisplay' not in l]
            if units:
                return f'journal:{units[0]}', 'systemd service'
        except (OSError, subprocess.SubprocessError):
            pass
    return None, 'not found (player stats need the server\'s log: set server_log)'


if __name__ == '__main__':
    w = find_world()
    print('world:', *w)
    print('game: ', *find_game())
    print('log:  ', *find_log())
    if w[0]:
        print('backups:', len(backups(w[0])))
