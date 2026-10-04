# Pulse

System health, without the noise.

**OBSERVE → UNDERSTAND → FIX**

Pulse v0.1 is a macOS-first, read-only system diagnostics CLI for developers,
using Python 3.12+. It observes CPU usage, memory, root disk usage, and uptime.
Other platforms supported by psutil may also work.

## Development

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
pulse --help
pulse status
pytest
ruff check .
ruff format --check .
```

CPU usage is sampled over 0.5 seconds. Memory and disk sizes are shown in GiB.
Disk figures describe the root filesystem as reported by psutil; macOS APFS
shared volumes and reclaimable space can differ from Finder's storage display.

`src/pulse/core/system.py` collects metrics with psutil.
`src/pulse/cli.py` presents them with Typer and Rich.

This version only observes the system. Cleaner, AI, and GUI features are outside
v0.1 scope.
