# Scheduling ResearchPilot

ResearchPilot deliberately has no in-process scheduler. Use the operating
system to invoke one bounded `run` command at the desired interval.

## Before scheduling

1. Install ResearchPilot in a dedicated virtual environment.
2. Create a user-specific profile outside version control.
3. Initialize or upgrade the database with `researchpilot db init`.
4. Run the complete command manually and resolve any configuration, Ollama,
   GitHub, digest, or Obsidian errors.
5. Use absolute paths for the executable, profile, database, working directory,
   and log files in scheduler definitions.

The scheduled command is:

```bash
/absolute/path/to/Research_Agent/.venv/bin/researchpilot run \
  --config /absolute/path/to/profile.yaml \
  --database /absolute/path/to/researchpilot.db
```

The command exits `0` after a successful pipeline, `1` when a recorded pipeline
step fails, and `2` for configuration, database, or overlapping-run errors.
Only one process may run for a database at a time. A hard interruption leaves
the current run resumable; the next invocation skips its completed steps and
retries the interrupted step.

## cron

This example runs every day at 07:00 and appends stdout and stderr to one log:

```cron
SHELL=/bin/zsh
PATH=/usr/local/bin:/usr/bin:/bin

0 7 * * * cd /absolute/path/to/Research_Agent && /absolute/path/to/Research_Agent/.venv/bin/researchpilot run --config /absolute/path/to/profile.yaml --database /absolute/path/to/researchpilot.db >> /absolute/path/to/logs/researchpilot.log 2>&1
```

Install it with `crontab -e`. Cron has a small environment: do not assume an
interactive shell, relative paths, or shell startup files. Supply
`GITHUB_TOKEN` and endpoint overrides through a protected environment-loading
mechanism rather than writing secrets into this repository or command line.
Ensure Ollama is already running when analysis work is expected.

## launchd on macOS

Save a property list such as
`~/Library/LaunchAgents/com.example.researchpilot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.example.researchpilot</string>

  <key>ProgramArguments</key>
  <array>
    <string>/absolute/path/to/Research_Agent/.venv/bin/researchpilot</string>
    <string>run</string>
    <string>--config</string>
    <string>/absolute/path/to/profile.yaml</string>
    <string>--database</string>
    <string>/absolute/path/to/researchpilot.db</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/absolute/path/to/Research_Agent</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>7</integer>
    <key>Minute</key>
    <integer>0</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>/absolute/path/to/logs/researchpilot.out.log</string>
  <key>StandardErrorPath</key>
  <string>/absolute/path/to/logs/researchpilot.err.log</string>
</dict>
</plist>
```

Load and test the agent for the current signed-in user:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.example.researchpilot.plist
launchctl kickstart -k gui/$(id -u)/com.example.researchpilot
```

Unload it with:

```bash
launchctl bootout gui/$(id -u)/com.example.researchpilot
```

Do not place API tokens in a checked-in property list. Use a protected local
secret-loading mechanism. The launch agent must have filesystem permission for
the database, digest directory, logs, and configured Obsidian vault.

## Operational checks

- Inspect command logs and the final `Pipeline status` line.
- Use `researchpilot db status` to confirm schema readiness and run-step counts.
- A failed run remains recorded; the next invocation starts a new idempotent
  run and safely reuses deduplicated discoveries and completed analyses.
- A process killed before recording failure remains `running`; the next
  invocation with the same config and database paths resumes that run.
- Keep the same absolute config and database paths across invocations so the
  pipeline identity remains stable.
