# Follow-up Automation With Error Alerts

Sends the follow-up step that is due today, remembers what already went out, retries a failed send —
and if it still cannot deliver, raises an alert instead of failing silently.

That last part is the whole point: a follow-up that quietly never left the building costs you the
customer, and you usually find out weeks later.

## What it handles

- **Sequence logic** — step 1 on day 0, step 2 on day 3, step 3 on day 7 (edit `SEQUENCE` to change it)
- **Never sends the same step twice** — every send is recorded in `state/state.json`
- **Suppression** — skips opted-out contacts and existing customers
- **Retry with backoff**, then a structured alert in `output/alerts.log` and a non-zero exit code
  (a non-zero exit code is what makes a scheduler email you when something breaks)
- **Safety first**: runs as a dry run by default and just writes the messages to `outbox/`; real
  sending is opt-in via `--smtp`, and credentials come from environment variables

## Run it

```bash
python make_sample_contacts.py                # sample list, dated relative to today
python follow_up.py                           # dry run
python follow_up.py --retries 2 --simulate-failure priya@orchard.example
```

`--simulate-failure` injects a delivery failure so the retry-and-alert path can be seen end to end.

## Output

| Path | Contents |
|---|---|
| `outbox/` | the rendered messages (dry run) |
| `state/state.json` | which step each contact has received, plus any permanent failures |
| `output/run.log` | full run log |
| `output/alerts.log` | one JSON line per permanently failed send |

Verified runs (2026-10-15):

- normal run — `sent=6 alerts=0`, opted-out contact and existing customer both correctly skipped
- fault-injected run — retried twice, then `ALERT send failed permanently for Priya Nair`, alert
  written to `output/alerts.log`, **exit code 2**, and the remaining contacts still processed

No third-party packages required — Python standard library only.

## Replaying the demo

Delete `state/` and `outbox/` first — the state file is what stops a contact from being emailed twice.
