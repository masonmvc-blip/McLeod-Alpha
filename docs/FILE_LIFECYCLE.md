# File Lifecycle Policy

Use this policy to keep root clean and avoid stale-runtime confusion.

## Naming States

- Active: normal descriptive names only; no backup/fix prefixes in root.
- Temporary: use tmp_<topic>_<yyyy-mm-dd> and remove within 7 days.
- Historical: move to archive/<date>_<topic>/ and keep a manifest.

## Root Directory Rules

- Root is for active runtime entrypoints and high-signal docs only.
- Do not create root files named *backup*, *.bak, or fix_*.py.
- One-off migration/repair scripts belong in scripts/maintenance/ or archive.
- Conflicted copies must be resolved and moved to archive immediately.

## Documentation Rules

- Keep one canonical status doc and one quick reference per subsystem.
- Move superseded summaries/fix reports to docs/archive/<date>_<topic>/.
- Add a one-line pointer from canonical docs when archives are created.

## Weekly Hygiene

Run:

```bash
scripts/maintenance/check_repo_hygiene.sh
```

Failing checks should be resolved before operational changes or live sessions.
