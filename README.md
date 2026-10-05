# Pulse

System health, without the noise. **OBSERVE → UNDERSTAND → FIX**

Pulse is a macOS-first desktop application for understanding system resources,
exploring storage, reviewing personal files and removing explicitly selected old developer caches. The
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
- **Storage:** read-only cache discovery, logical/allocated sizes, coverage, cancellation and cleanup policies.
- **Processes:** search and rank apps/processes by processor or resident memory use.
- **Disk explorer:** choose a folder, inspect its largest files and immediate children,
  compare logical lengths with allocated blocks, filter results and drill into folders.
- **System details:** measured RAM, swap, CPU/load, network counters individual mounted volumes, physical drives and available SMART status.
- **Maintenance:** explicitly rebuild Finder thumbnail caches when previews are stale.
- **History:** local audit details and reviewed recovery of preserved files and supported trashed personal files.

The resource sample refreshes every 30 seconds while the window is active.
Storage is scanned only on request. One background operation runs at a time;
Pulse waits for it to finish before allowing the window to close. Collection
errors appear with details, and the interface stays responsive during scans.

**Review cleanup** shows the exact eligible files with every checkbox initially
empty. Select the files you want to remove, then confirm permanent removal in a
separate dialog (default No). Files are revalidated by the engine before deletion.
Only the five cache policies listed below authorize permanent cleanup. In Disk explorer, a selected visible regular
file in Downloads, Desktop, Documents, Movies, Music or Pictures can instead be reviewed and moved to macOS Trash. No folders or
application/library packages are moved. Trash is never emptied automatically.

Folder analysis is metadata-only, with a 30-second / 200,000-entry budget and a
Stop scan button. Stopping returns the inspected partial results. OS metadata calls
can temporarily block cancellation, especially on network/cloud storage. Symlinks,
other volumes, Trash, recovery staging and unreadable entries are explicitly excluded;
partial coverage is never presented as a complete disk inventory. Largest files are
limited to 100; the table shows up to 1,000 filtered immediate children.

Scan sizes are estimates, and APFS
space actually reclaimed is not claimed. History is loaded on request; reload it
after cleanup or recovery. Successfully deleted files cannot be restored.

## Build a standalone macOS app

```sh
python -m pip install -e '.[desktop,build]'
python packaging/build_macos.py
```

This creates `dist/Pulse.app` and `dist/Pulse-0.4.0-macos-arm64.zip` on an Apple
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
| `pulse analyze ~/Downloads` / `pulse analyze PATH --json` | Bounded, read-only folder analysis and largest files |
| `pulse drives` / `pulse drives --json` | Physical drives and OS-reported SMART; missing information stays unknown |
| `pulse trash PATH --dry-run` / `pulse trash PATH` | Preview or confirm a single personal file for native Trash (desktop dependency required to move) |
| `pulse clean-categories` | Explain supported cache policies and consequences |
| `pulse volumes` / `pulse volumes --json` | Individual mounted volumes and accessible capacity |
| `pulse maintain` | List supported symptom-specific maintenance actions |
| `pulse maintain quicklook-cache --dry-run` | Explain thumbnail rebuilding without changes |
| `pulse maintain quicklook-cache` | Confirm (default NO), run a fixed macOS tool with a timeout and audit |
| `pulse status` | OS version, architecture, cores, load, CPU, memory, disk, swap, battery and network totals |
| `pulse processes --sort cpu --limit 10` | Accessible processes ranked by sampled CPU |
| `pulse processes --sort memory` | Rank by resident memory |
| `pulse health` / `pulse health --json` | Explainable snapshot findings; no storage scan |
| `pulse doctor` | Resource observations and manual next steps |
| `pulse scan` / `pulse scan --details` | Read-only inventory of known locations and discovered application caches |
| `pulse scan --json` | Structured inventory with coverage, exclusions, allocated bytes and access problems |
| `pulse clean --dry-run` | Plan and validate eligible cache files (pip by default) without filesystem writes |
| `pulse clean --dry-run --json` | Structured plan and execution preview |
| `pulse clean --category CATEGORY` | Display plan, ask confirmation (default NO), execute and report |
| `pulse history` / `pulse history --json` | Read private cleanup audit journals and potential recovery paths |
| `pulse recover SOURCE --to ORIGINAL --dry-run` | Preview recovery of a supported preserved file / trashed personal file |
| `pulse recover SOURCE --to ORIGINAL` | Restore with confirmation, without overwriting existing data |
| `pulse optimize` | Manual maintenance recommendations; no automatic changes |

Use `--details` on `clean` to show every planned file and individual result.
The known-cache inventory does not scan the whole filesystem. `analyze` inspects
only the selected root and does not cross volumes; a budget always bounds traversal. `status` and `health` never traverse cache directories.

## What measurements mean

Displayed sizes use decimal B/KB/MB/GB (1 MB = 1,000,000 bytes); JSON retains exact byte counts. Physical drive data comes from bounded, read-only macOS `diskutil` queries. SMART is an OS-reported status, not a full drive test. Unsupported values remain unknown; raw device attributes in JSON are not interpreted as temperature, wear or a health score.


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
- Memory ≥85% and swap ≥2,147,483,648 bytes (about 2.15 GB): informational observations, not pressure claims.
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
roots are reported. Standard storage scans share a 30-second budget and inspect up to 50,000 entries per location. Desktop Deep scan uses 120 seconds / 250,000 entries; CLI budgets can be set with `--seconds` and `--max-entries`. Additional application cache discovery is bounded to 500 directory entries. Cancellation returns partial results. OS metadata calls can delay cancellation. A failed resource sample does not prevent storage scanning.

Symlinks, mount changes, special files and recovery staging are excluded. Reports distinguish exclusions, access errors and unscanned locations. File lengths and allocated blocks are shown separately; hardlinks count once per location. Categories must not be summed as guaranteed reclaimable space. No file contents are read.

### Executable cache policies

| Category | Root below home | Minimum recorded access and modification age |
| --- | --- | --- |
| `pip-http` | `Library/Caches/pip/http-v2` | 7 days |
| `pip-http-legacy` | `Library/Caches/pip/http` | 7 days |
| `npm-content` | `.npm/_cacache/content-v2/sha512` | 30 days |
| `go-build` | `Library/Caches/go-build` | 30 days |
| `cargo-downloads` | `.cargo/registry/cache` | 30 days |

Each policy recognizes a narrow filename/layout pattern. Cargo supports only the recognized public registry directories; custom registries stay protected. Unknown files, browser profiles, Trash, diagnostics, Xcode build data and other application caches remain review-only. Age is based on filesystem timestamps, not proof that a file is unused. Close related installers/builds first. Removed downloads must be fetched again, offline builds may fail and subsequent builds can be slower.

A cache candidate must be a regular single-link file owned by the current user. Plans expire after 15 minutes, are bound to the category and root identity, and must be complete. Unknown, changed, incomplete or expired plans are refused. Permanent cleanup never extends to personal folders, projects, credentials or system files.

The separate personal-file workflow moves only an explicitly reviewed file to native Trash, rechecking ownership, single-link identity, private parent permissions and preview age. Hidden paths and contents of application, photo, mail, document and virtual-machine packages are protected. A journal is mandatory before staging and movement. No permanent-deletion fallback exists. Files preserved after failure have recovery paths. Synced-file movement may propagate to other devices; close the file's application first.

Trash still occupies space. History records original and Trash paths where available and supports confirmed recovery from home Trash without overwrite. Other Trash locations require manual recovery. Because files are staged for race checking, Finder Put Back can point to staging; use Pulse History or manually restore the original path.

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
Recovery is explicit and restricted to matching supported cache/personal-file staging paths or
regular files in the current home Trash restored into supported personal folders. The
source is revalidated and an exclusive hardlink prevents destination overwrite.
Changed files, symlinks, different owners and conflicting destinations are refused.
A successfully deleted cache file cannot be recovered. Personal files in Trash remain
recoverable until Trash is emptied outside Pulse. There is no automatic purge or history pruning. Descriptor
checks reduce races; they do not promise protection against a hostile process
running as the same user or an active writer with an already-open file handle.

Maintenance currently supports only the system thumbnail-cache reset
(`/usr/bin/qlmanage -r cache`), when Finder previews are stale. It requires an
explicit default-No confirmation and durable journal, uses no shell or administrator
privileges, and stops waiting after 30 seconds. A timeout is reported as uncertain;
check Finder before retrying. Caches regenerate, so previews may initially be slower.
No blanket speedup, RAM boost, automatic process killing, login-item mutation or
security-setting change is claimed. Close unneeded apps normally after reviewing
measured processes. Cleanup/recovery tests use disposable fixtures only. The native
Trash smoke check uses a uniquely named disposable file and restores/removes it.
Actual user-data validation uses read-only commands and dry-run.

## Python APIs and architecture

See [architecture](docs/architecture.md) for the stage boundaries.

- `pulse.storage.analyzer.analyze_directory()` → bounded metadata inventory, coverage and largest files
- `pulse.storage.trash.prepare_trash()` / `execute_trash()` → exact reviewed personal file, injected native adapter
- `pulse.core.volumes.get_volumes()` → individual accessible mounted volumes
- `pulse.optimization.actions.run_maintenance()` → confirmed narrow action and audit result
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

Policy layout references: [Go build cache](https://go.dev/src/cmd/go/internal/cache/cache.go), [npm content paths](https://github.com/npm/cacache/blob/main/lib/content/path.js), and [Cargo home](https://doc.rust-lang.org/cargo/guide/cargo-home.html). Pulse implements its own bounded scanning and reviewed execution.
