"""Shared bits: where the working folder is, and how one tool runs another.

Every tool works relative to the home folder (data/, web/assets/, regions.json live there).
From a source checkout that is the repository; the packaged app sets VALHEIM_DISPLAY_HOME.
"""
import os
import subprocess
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
FROZEN = getattr(sys, 'frozen', False)   # running from the PyInstaller executable


def home():
    return os.environ.get('VALHEIM_DISPLAY_HOME') or os.path.dirname(TOOLS)


def enter_home():
    os.chdir(home())


def tool_cmd(name, *args):
    """Command line that runs tools/<name>.py, from source or inside the executable."""
    if FROZEN:
        return [sys.executable, '__tool', name, *map(str, args)]
    return [sys.executable, os.path.join(TOOLS, name + '.py'), *map(str, args)]


def run_tool(name, *args, **kw):
    """Run a tool in its own process (the asset exporters use a lot of memory; this hands it back)."""
    return subprocess.run(tool_cmd(name, *args), check=True, **kw)
