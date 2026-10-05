# Engine boundaries

Pulse exposes synchronous, typed Python functions and immutable dataclasses.
The CLI and optional PySide6 desktop interface are replaceable presentation layers.

| Stage | Modules | Output / responsibility |
| --- | --- | --- |
| Collect | `core/system`, `core/processes`, `core/network`, `core/volumes` | Measured data, optional values and process coverage |
| Explore | `storage/analyzer` | Bounded metadata-only traversal, cancellation, logical/allocated sizes and coverage |
| Trash | `storage/trash`, `desktop/platform` | Exact Downloads file, journal, private staging, native adapter; no deletion fallback |
| Maintain | `optimization/actions` | Fixed non-privileged macOS tool, explicit confirmation, timeout and audit |
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
permanently removes pip HTTP caches only; selected regular Downloads files can be moved to
native Trash; recovery is explicit rather than automatic; there is no
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

## Explorer and maintenance boundaries

The explorer reads only directory metadata via descriptors and never opens file
contents. It shares a global inode set to attribute hard-linked content once.
Allocated blocks are a measurement, not a claim about APFS exclusive allocation
or reclaimed space. Traversal and retained largest-file results are bounded.
The GUI supplies a cooperative cancellation event and receives queued progress
signals; partial results remain usable. No scan triggers cleanup or maintenance.

The engine's Trash adapter is injected as a callable and has no Qt import.
`desktop/platform` implements it using Qt's native macOS Trash API. Selection
previews are fresh identities, not authorization derived from analyzer results.
Intent is synced before staging, identity is rechecked after atomic rename, and
errors preserve a recoverable file. The adapter must move the file; absence of
native support never triggers unlink. Successful native moves keep the original
filename and report zero reclaimed bytes. History records contain original and
Trash paths; recovery preparation revalidates supported paths independently.

Maintenance uses an immutable internal catalog of complete argument tuples,
without accepting user commands, a shell, sudo or arbitrary executables. Preview
and cancellation have no effects. The journal is persisted before the tool runs;
a timeout is an uncertain outcome, not reported success.
