# Engine boundaries

Pulse exposes synchronous, typed Python functions and immutable dataclasses.
The CLI and optional PySide6 desktop interface are replaceable presentation layers.

| Stage | Modules | Output / responsibility |
| --- | --- | --- |
| Collect | `core/system`, `core/processes`, `core/network` | Measured data, optional values and process coverage |
| Analyze | `health/engine` | Deterministic issues with severity, evidence and recommendations |
| Scan | `cleanup/scanner` | Bounded, descriptor-based inventories; no writes |
| Classify / plan | `cleanup/planner`, `cleanup/models` | Narrow allowlist, file identities, age, scope and completeness |
| Execute | `cleanup/executor`, `cleanup/filesystem` | Explicit confirmation, revalidation, staging, unlink and per-file results |
| Audit / recover | `cleanup/journal`, `cleanup/recovery` | Local write-ahead records and explicit recovery without overwrite |
| Recommend | `optimization/engine` | Real maintenance recommendations, no system mutations |
| Coordinate | `services/monitor`, `services/engine` | Snapshots and explicit full scans reusable by a desktop UI |
| Present | `cli`, `desktop` | CLI output, Qt views, background tasks and explicit user confirmation |

Collectors do not import presentation. Scanning never authorizes deletion.
The planner does not trust inventory sizes as permission to clean. Execution
revalidates independently and never accepts arbitrary cache categories. Default
execution is a dry-run; GUI callers must show the exact plan and obtain explicit
user confirmation before passing `confirmed=True, dry_run=False`.

Each report can be serialized using `dataclasses.asdict`; JSON callers should
serialize `Path` as strings. These are in-process APIs, not a versioned remote
protocol. Do not deserialize an untrusted cleanup plan and execute it.

The optional `home` parameter supports deterministic tests and deliberate API
scope selection. Runtime CLI commands always use the current user's home. Tests
never use real user data for deletion. Do not supply arbitrary production trees
as a fake home to circumvent policy.

macOS cache paths and POSIX descriptor flags live in the cleanup policy and
filesystem modules. Standard psutil/platform collection remains independent.
Add explicit platform adapters only when a second implementation is required.
Optional platform data returns unknown rather than invented measurements;
fundamental metric collection failures are surfaced to the caller.

Known limits: snapshot thresholds do not establish sustained problems; battery
condition and macOS Memory Pressure are not measured; cleanup execution currently
supports pip HTTP caches (current and legacy) only; recovery is explicit rather than automatic; there is no
startup-item controller or claimed APFS reclaimed-space measurement.

Cleanup journals are append-only per run and synced before mutations. They are
local data, not trusted instructions. History parsing is bounded and preserves
recovery hints from valid records preceding a malformed tail. Plans are always
built and validated against the live filesystem rather than executed from logs.
A final audit-write error does not erase or misreport already-completed deletion
or recovery; the report includes the audit error and subsequent operations stop.

## Desktop boundary

`desktop/tasks` runs one synchronous engine call on a QThread. Signals deliver
results and errors to the GUI thread. The window disables operation controls
while busy and refuses to close during a job, so an active executor is not
terminated. Monitoring refreshes only when active; scanning and journal reading
are explicit actions. No Qt dependency is imported by the engine or CLI.

`desktop/cleanup_dialog` derives a selected plan with `dataclasses.replace`,
retaining category, root and file identities. Selection starts empty. A separate
default-No confirmation precedes `confirmed=True, dry_run=False`. The executor
remains the authority for scope, freshness and safety. History recovery hints
are treated as data and passed through live recovery preparation/validation.
