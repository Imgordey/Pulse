# Pulse

System health, without the noise.

**OBSERVE → UNDERSTAND → FIX**

Pulse is a macOS-first system health application for everyday computer users.
The current v0.1 foundation uses Python 3.12+ and a temporary, read-only CLI
for development and testing. It observes CPU usage, memory, root disk usage,
and uptime. The intended primary interface is a desktop application; GUI and
cleanup implementation are deferred. Windows and Linux are not currently
supported targets.

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

## Understand resource usage

```sh
pulse processes --sort cpu --limit 10
pulse processes --sort memory
pulse doctor
```

Process CPU is sampled twice with a shared 0.5 second wait. 100% represents one
logical core, so a multithreaded process can exceed 100%. RSS is resident memory,
not unique memory; shared pages mean process RSS values should not be summed.
Inaccessible or exited processes are skipped and counted. Names are displayed as
plain text, without inspecting command lines or environment variables.

`doctor` reports observations at CPU ≥85%, memory ≥85%, or root disk ≥90%.
These are simple heuristics, not proof of a problem. In particular, macOS memory
pressure requires additional context. Recommendations are manual; Pulse does
not delete files, stop processes, or alter settings.

## Extended metrics and cleanup preview

`pulse status` also reports available memory, free disk space, swap, and battery
charge/power source when accessible. Charge is not a battery condition assessment.
The psutil memory percentage and its `used` field have different definitions on
macOS; the percentage need not equal the displayed used/total ratio. Available
memory is a separate estimate and is not a macOS Memory Pressure measurement.

`pulse scan` inventories only pip's macOS cache and Xcode DerivedData, in the
separate developer category. It never deletes files or scans personal documents.
Symlinked roots and children are skipped. Each location is limited to 50,000
entries; permission failures or skipped entries make coverage partial. File
lengths are estimates, not allocated/reclaimable disk space, and hardlinks are
counted once per location. Missing/inaccessible roots are omitted, so this is
not a full disk scan. Filesystem changes during scanning can affect results.

Cleanup execution and desktop UI are not implemented yet.

## Health and maintenance APIs

`pulse health` (or `pulse health --json`) performs a quick, deterministic analysis
without scanning storage. `pulse optimize` additionally samples processes and
returns manual recommendations; it never stops apps or changes settings.

Rules: CPU ≥85% is a snapshot warning; memory ≥85% and swap ≥2 GiB are informational
observations, not proof of pressure. Available system-disk space ≤10% warns and
≤5% is critical. Battery charge ≤10% warns only while unplugged. Process CPU ≥100%
or RSS ≥25% of installed RAM prompts review, not automatic termination. Overall
status is the maximum warning/critical severity, not a numerical score. “No alerts”
only describes the measured sample. Network rates can be calculated from two
monotonic-time counter samples and are unknown when counters reset.

Import `pulse.services.monitor.collect_snapshot`, `pulse.health.engine.analyze_health`,
and `pulse.optimization.engine.recommend_maintenance` for structured Python APIs.
