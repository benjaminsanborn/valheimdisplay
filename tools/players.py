"""Who plays on the server: sessions, hours, deaths and who is online, from the game server's log.

  players.py [--publish DIR]

Reads the valheim.service journal (over ssh when VALHEIM_SSH is set, like update.sh), keeps the lines
that matter in data/history/serverlog.txt (so history survives journal rotation), and writes
web/assets/players.json (and DIR/assets/players.json with --publish).

How the log is read:
  - "Got handshake from client X" then "Got character ZDOID from NAME : uid:1" = NAME joined
  - "Got character ZDOID from NAME : 0:0" = NAME's character is gone: a death if NAME spawns again,
    a logout if a disconnect follows instead
  - "Closing socket X" (Steam) / "Player connection lost ... now N player(s)" (crossplay) = left
  - the service stopping or starting ends every session
Only character names are published, never Steam/PlayFab ids.
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict

LOG = 'data/history/serverlog.txt'
OUT = 'web/assets/players.json'
KEEP = re.compile(r'Got handshake from client|Got character ZDOID from|Closing socket|Player connection lost|'
                  r'Player joined server|systemd\[1\]: (Started|Stopping) valheim')
MAX_SESSION = dt.timedelta(hours=16)   # a session with a missing disconnect (log gap) shouldn't count forever


def fetch():
    """New relevant journal lines, as 'ISO-time<TAB>message'."""
    known = set(open(LOG).read().splitlines()) if os.path.exists(LOG) else set()
    since = max((l.split('\t')[0] for l in known), default=None)
    cmd = ['journalctl', '-u', 'valheim.service', '-o', 'short-iso', '--no-pager']
    if since:
        cmd += ['--since', since[:19].replace('T', ' ')]
    host = os.environ.get('VALHEIM_SSH', 'ubuntu')
    if host:
        cmd = ['ssh', host, ' '.join(f"'{c}'" for c in cmd)]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    new = []
    for line in out.splitlines():
        if not KEEP.search(line):
            continue
        t, _, rest = line.partition(' ')
        msg = re.sub(r'^\S+ [^:]+: (\d\d/\d\d/\d{4} [\d:]+: )?', '', rest)
        if 'systemd[1]' in rest:
            msg = 'SERVICE ' + ('start' if 'Started' in rest else 'stop')
        row = f'{t}\t{msg}'
        if row not in known:
            known.add(row)
            new.append(row)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, 'a') as f:
        for row in new:
            f.write(row + '\n')
    return sorted(known)


def parse(rows):
    """Sessions and deaths. Crossplay disconnects don't say who left, so each one is held as an
    unassigned loss and given to a player later: the one whose character had just vanished, the one
    whose client reconnects next, a player who logs in again (they must have left in between), or,
    when a join reports fewer players than we think are online, whoever has been quiet longest."""
    online = {}           # name -> dict(start, last activity, uid)
    sock = {}             # client id -> name (PlayFab ids are stable per player)
    pending = []          # handshakes still waiting for their character
    gone = {}             # name -> time its character vanished (0:0)
    losses = []           # disconnects not yet tied to a player
    sessions, deaths = [], []

    def end(name, t):
        s = online.pop(name, None)
        gone.pop(name, None)
        if s:
            sessions.append((name, s['start'], min(t, s['start'] + MAX_SESSION)))

    def end_at_loss(name, before):
        """End name's session at the first open disconnect after its last activity."""
        last = online[name]['last']
        for i, lt in enumerate(losses):
            if last <= lt <= before:
                del losses[i]
                return end(name, lt)
        end(name, last)

    def trim(keep, t):
        # quietest first
        for n in sorted((n for n in online if n not in keep), key=lambda n: online[n]['last']):
            if len(online) <= len(keep) + trim.allowed:
                break
            end_at_loss(n, t)

    for row in rows:
        ts, msg = row.split('\t', 1)
        t = dt.datetime.fromisoformat(ts)
        if msg.startswith('SERVICE'):
            for n in list(online):
                end_at_loss(n, t) if losses else end(n, t)
            losses.clear(); pending.clear()
        elif m := re.match(r'Got handshake from client (\S+)', msg):
            name = sock.get(m[1])
            if name in online:     # this player's client is reconnecting: it had left
                end_at_loss(name, t)
            elif name and losses and (t - losses[-1]).total_seconds() < 30:
                losses.pop()       # the disconnect just before was this (offline) player's own client
            if m[1] in pending:
                pending.remove(m[1])
            pending.append(m[1])
        elif m := re.match(r'Got character ZDOID from (.+) : (-?\d+):(\d+)', msg):
            name, uid = m[1].strip(), int(m[2])
            if uid == 0:
                if name in online:
                    gone[name] = t
                    online[name]['last'] = t
                continue
            if name in online and online[name]['uid'] != uid:   # a fresh login: the old session ended
                end_at_loss(name, t)
            if name in gone:
                deaths.append((name, gone.pop(name)))
            if name not in online:
                online[name] = dict(start=t, last=t, uid=uid)
                if pending:
                    sock[pending.pop(0)] = name
            online[name]['last'] = t
        elif m := re.match(r'Closing socket (\S+)', msg):
            name = sock.get(m[1])
            if name in online:
                end(name, t)
        elif m := re.match(r'Player connection lost.* now (\d+) player', msg):
            recent = [n for n in online if n in gone and (t - gone[n]).total_seconds() < 60]
            if recent:
                end(max(recent, key=lambda n: gone[n]), t)
            else:
                losses.append(t)
            if int(m[1]) == 0:
                for n in list(online):
                    end_at_loss(n, t)
                losses.clear()
        elif m := re.match(r'Player joined server.* now (\d+) player', msg):
            # N players including the one joining: anyone beyond that has left
            trim.allowed = max(0, int(m[1]) - 1)
            trim(set(), t)
    # disconnects nobody claimed: the quietest players left first
    for lt in list(losses):
        cands = [n for n in online if online[n]['last'] <= lt]
        if cands:
            end(min(cands, key=lambda n: online[n]['last']), lt)
    return {n: s['start'] for n, s in online.items()}, sessions, deaths


def summarise(online, sessions, deaths, now):
    stats = defaultdict(lambda: dict(seconds=0, sessions=0, deaths=0, first=None, last=None))
    days = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # date -> name -> [minutes, deaths]
    for name, a, b in sessions + [(n, s, now) for n, s in online.items()]:
        s = stats[name]
        s['seconds'] += (b - a).total_seconds()
        s['sessions'] += 1
        s['first'] = min(filter(None, [s['first'], a]))
        s['last'] = max(filter(None, [s['last'], b]))
        t = a
        while t < b:   # split across local midnights for the per-day activity
            nxt = min(b, dt.datetime.combine(t.date() + dt.timedelta(days=1), dt.time(), t.tzinfo))
            days[t.date().isoformat()][name][0] += round((nxt - t).total_seconds() / 60)
            t = nxt
    for name, t in deaths:
        stats[name]['deaths'] += 1
        days[t.date().isoformat()][name][1] += 1
    players = [dict(name=n, hours=round(s['seconds'] / 3600, 1), sessions=s['sessions'], deaths=s['deaths'],
                    first=s['first'].isoformat(timespec='minutes'), last=s['last'].isoformat(timespec='minutes'),
                    online=n in online)
               for n, s in stats.items()]
    players.sort(key=lambda p: -p['hours'])
    return dict(updated=now.isoformat(timespec='seconds'),
                online=[dict(name=n, since=s.isoformat(timespec='minutes')) for n, s in online.items()],
                players=players,
                days={d: {n: v for n, v in sorted(by.items())} for d, by in sorted(days.items())})


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rows = fetch()
    online, sessions, deaths = parse(rows)
    data = summarise(online, sessions, deaths, dt.datetime.now().astimezone())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + '.tmp'
    json.dump(data, open(tmp, 'w'), separators=(',', ':'))
    os.replace(tmp, OUT)
    if '--publish' in sys.argv:
        dest = os.path.join(sys.argv[sys.argv.index('--publish') + 1], 'assets', 'players.json')
        shutil.copy(OUT, dest + '.tmp')
        os.replace(dest + '.tmp', dest)
    print(f"{len(data['players'])} players, online: {[o['name'] for o in data['online']]}", file=sys.stderr)


if __name__ == '__main__':
    main()
