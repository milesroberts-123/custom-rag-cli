# Session transcripts

Compressed OpenCode session exports, one per session. Generate the current
session before each push:

```bash
scripts/export-session.sh <session-name>
```

The default export includes tool calls and outputs. Add `--sanitize` to redact
transcript and file data before compressing, at the cost of losing the tool
activity.

Commit the generated `.json.xz` with the push it accompanies.
