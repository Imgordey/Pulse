# Pulse

System health, without the noise. **OBSERVE → UNDERSTAND → FIX**

Pulse is a macOS-first desktop application for understanding system resources,
reviewing storage and safely removing eligible old pip download caches. The
Python engine powers both a Qt desktop interface and a CLI. Everything stays
local: no telemetry, account, cloud service or AI. Windows and Linux are not
supported targets for this version.

## Open the desktop application

The locally built application is `dist/Pulse.app`; double-click it in Finder.
It includes Python and Qt, so a separate Python installation is not required.
This build targets Apple Silicon and macOS 13+. It is signed locally, without an
Apple Developer ID or notarization; it is not a signed public release installer.

From a development environment:

```sh
python -m pip install -e '.[dev,desktop]'
pulse-desktop
```

- **Overview:** real resource samples, explainable findings and available storage.
- **Storage:** an explicit read-only scan of known locations, coverage and policy.
- **Processes:** search and rank apps/processes by processor or resident memory use.
- **History:** local audit details and explicit recovery of files preserved after errors.

The resource sample refreshes every 30 seconds while the window is active.
Storage is scanned only on request. One background operation runs at a time;
Pulse waits for it to finish before allowing the window to close. Collection
errors appear with details, and the interface stays responsive during scans.

**Review cleanup** shows the exact eligible files with every checkbox initially
empty. Select the files you want to remove, then confirm permanent removal in a
separate dialog (default No). Files are revalidated by the engine before deletion.
Other storage categories remain review-only. Scan sizes are estimates, and APFS
space actually reclaimed is not claimed. History is loaded on request; reload it
after cleanup or recovery. Successfully deleted files cannot be restored.

## Build a standalone macOS app

```sh
python -m pip install -e '.[desktop,build]'
python packaging/build_macos.py
```

This creates `dist/Pulse.app` and `dist/Pulse-0.2.0-macos-arm64.zip` on an Apple
Silicon Mac. Build on the target architecture; this is not a universal binary.
The script generates the icon, bundles dependencies, adds runtime notices,
checks the final local signature, and archives the app. It does not install into
Applications or change macOS security settings. Rebuild after changing the source.
Before a public binary release, finish third-party notices/source review and
Apple Developer ID signing/notarization. Source development needs no Apple account.

## Install and develop

Python 3.12+ on macOS is required. Development is tested on Apple Silicon.

```sh
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev,desktop]'
pytest
ruff check .
ruff format --check .
```

## Commands

| Command | Behavior |
| --- | --- |
| `pulse status` | OS version, architecture, cores, load, CPU, memory, disk, swap, battery and network totals |
| `pulse processes --sort cpu --limit 10` | Accessible processes ranked by sampled CPU |
| `pulse processes --sort memory` | Rank by resident memory |
| `pulse health` / `pulse health --json` | Explainable snapshot findings; no storage scan |
| `pulse doctor` | Resource observations and manual next steps |
| `pulse scan` / `pulse scan --details` | Read-only inventory of known cache/report locations |
| `pulse scan --json` | Structured inventory with inaccessible-root problems |
| `pulse clean --dry-run` | Plan and validate eligible pip cache files without filesystem writes |
| `pulse clean --dry-run --json` | Structured plan and execution preview |
| `pulse clean --category pip-http` (or `pip-http-legacy`) | Display plan, ask confirmation (default NO), execute and report |
| `pulse history` / `pulse history --json` | Read private cleanup audit journals and potential recovery paths |
| `pulse recover SOURCE --to ORIGINAL --dry-run` | Preview recovery of a preserved cache file |
| `pulse recover SOURCE --to ORIGINAL` | Restore with confirmation, without overwriting existing data |
| `pulse optimize` | Manual maintenance recommendations; no automatic changes |

Use `--details` on `clean` to show every planned file and individual result.
No command scans the whole filesystem. Storage scanning is explicit, with progress
shown by the CLI. `status` and `health` never traverse cache directories.

## What measurements mean

CPU is sampled for 0.5 seconds. Process CPU is sampled twice with a shared wait;
100% represents one logical core and multithreaded apps can exceed 100%. RSS is
resident memory, not unique allocation, and should not be summed across apps.
Process owners can be unavailable; exited/inaccessible processes are skipped.
Command lines, environment variables and packet contents are never inspected.

On macOS, psutil memory `used`, available memory and percentage have different
definitions; the displayed percentage need not equal used/total. None is a
measurement of macOS Memory Pressure. Root filesystem usage can also differ
from Finder due to APFS shared volumes and reserved space. Health uses the
available/total space ratio when available. Battery charge is not battery
condition. Network totals are cumulative; rate APIs need two monotonic samples
and return unknown after counter resets. Optional unavailable metrics are not
silently treated as healthy.

## Health rules

Rules are deterministic and return evidence and manual recommendations:

- CPU ≥85%: snapshot warning, not proof of sustained overload.
- Memory ≥85% and swap ≥2 GiB: informational observations, not pressure claims.
- Available disk space ≤10%: warning; ≤5%: critical.
- Battery charge ≤10% while unplugged: warning.
- Process CPU ≥100% or RSS ≥25% of installed RAM: informational review.

Overall status reflects warning/critical severity. “No alerts in this sample” is
not a clean bill of health. No numerical health score or speed improvement is
promised. Large complete cache inventories can produce review recommendations
through the optimization API; their size is not guaranteed reclaimable space.

## Storage and cleanup safety

Known locations include pip, npm, pnpm, Yarn, Xcode DerivedData, Homebrew, Gradle,
Cargo downloads, Go builds, macOS help, Safari/Chrome caches, diagnostic reports
and Trash. Categories stay separate. Missing locations are normal; inaccessible
roots are reported. Each location has a 50,000-entry budget. Symlinks, mount
changes and special files are skipped; incomplete coverage is explicit. Logical
file lengths are estimates, not actual disk allocation; hardlinks are counted
once per location. No file contents are read. Recovery staging folders are
excluded from subsequent inventories.

**Only recognized files in `~/Library/Caches/pip/http-v2` and the legacy
`~/Library/Caches/pip/http` are executable cleanup candidates.** Browser caches/profiles, Trash, diagnostics, Xcode build data and
other categories remain review-only or protected. Pulse never deletes Documents,
Desktop, Downloads, media, projects, credentials, unknown app data or system files.
A large directory never becomes SAFE just because of its size.

A pip cache file qualifies only if its hash-based cache layout is recognized,
it is a regular single-link file owned by the current user, and both access and
modification times are at least seven days old. This is an allowlisted cache
policy, not content recognition. Close pip/installers first; removed downloads
will need to be fetched again. Unexpected/incomplete/expired plans are refused.
Plans expire after 15 minutes and are bound to a home, root device and inode.

The workflow is scan → classify → plan → display → confirm → execute → report.
The API defaults to dry-run; actual CLI cleanup requires an explicit category
and interactive confirmation defaulting to NO. There is no `--yes` bypass.
Execution validates the allowlisted path, owner, directory permissions and file
identity again. Every directory component is opened without following symlinks.
The file is atomically staged in a private directory before a second identity
check and single-file unlink. No recursive deletion or shell removal is used.
If a replacement or failure is detected after staging, the file is preserved and
the report includes its recovery path. There is no automatic purge of recovery
files. Successful cache deletion is permanent, not a Trash operation.

Reports distinguish deleted/skipped/failed/would-delete, logical bytes removed,
blocked-plan reasons and recovery paths. Actual reclaimed space remains unknown
on APFS because shared extents, snapshots and other activity prevent attribution.
Actual cleanup now writes a private journal in
`~/Library/Application Support/Pulse/cleanup-history` (files mode 600). Intent
records are flushed and synced before staging; staged records precede unlink.
If the journal is unavailable, cleanup is refused. If auditing fails during a
run, remaining operations stop and actual completed results are retained.
Dry-run creates no journals or directories. History is local and never uploaded.
Interrupted/malformed journals report errors while retaining prior recovery hints.
Use `history` to review these hints; records are data, never executable plans.
Recovery is explicit and restricted to matching pip cache staging paths. The
source is revalidated and an exclusive hardlink prevents destination overwrite.
Changed files, symlinks, different owners and conflicting destinations are refused.
A successfully deleted file cannot be recovered; recovery only handles files
preserved after errors. There is no automatic purge or history pruning. Descriptor
checks reduce races; they do not promise protection against a hostile process
running as the same user or an active writer with an already-open file handle.

No sudo, automatic process killing, login-item changes, security-setting changes,
RAM boosters or preference mutations are performed. Cleanup tests use temporary
fixtures only. Real-data validation uses read-only commands and dry-run.

## Python APIs and architecture

See [architecture](docs/architecture.md) for the stage boundaries.

- `pulse.core.system.get_system_stats()` → immutable system metrics
- `pulse.core.processes.get_process_stats()` → processes and coverage
- `pulse.core.network.network_activity(before, after)` → network rates
- `pulse.health.engine.analyze_health(stats, processes=None)` → issues and status
- `pulse.cleanup.scanner.scan_storage()` → candidates and access problems
- `pulse.cleanup.planner.create_cleanup_plan()` → eligible file plan
- `pulse.cleanup.executor.execute_cleanup(plan, dry_run=True)` → explicit results and audit location
- `pulse.cleanup.journal.read_history()` → bounded audit summaries and recovery hints
- `pulse.cleanup.recovery.prepare_recovery()` / `recover_file()` → reviewed, explicit recovery
- `pulse.optimization.engine.recommend_maintenance(report, candidates=())` → recommendations
- `pulse.services.monitor.collect_snapshot()` → quick monitor snapshot
- `pulse.services.engine.scan_computer()` → explicit full scan and recommendations

Core/health/cleanup/optimization/services have no Rich or Typer dependencies.
Filesystem scope is macOS-specific and intentionally narrow. Future OS adapters
should implement their own policies rather than reusing macOS cache paths.

## Automated checks

GitHub Actions runs the deterministic test suite, Ruff and dependency checks on
macOS with Python 3.12 and 3.13, including offscreen desktop tests. Cleanup/recovery operations use disposable pytest
fixtures. Actions are pinned to verified upstream commits and the workflow token
has read-only repository contents permissions.

`clean --category pip-http-legacy --dry-run` previews the old pip HTTP cache.
Category selection is bound into the plan and revalidated at execution; selecting
one category cannot clean another root. The allowlist is immutable and unsupported
categories fail closed. Age, identity, ownership, journaling and recovery policies
are identical for both HTTP cache formats. Other cache categories remain review-only.
