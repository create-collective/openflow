# Report a problem: what it sends, and how to switch the tracker on

The **More → Bug Report** page collects a report and hands it to whatever sink the machine has
configured. There is one sink today, Jira, and **it is off unless credentials are present on
that machine**. A build with none still assembles the report and offers it to be copied or
saved, which is the path every beta tester gets.

## Why no token ships with the app

A Jira API token is scoped to an **account**, not to a project. A token inside a distributed
binary, or in this repository's history, hands every reader the owner's whole Jira. So the site,
project, epic and sprint have defaults in `backend/openflow_backend/report.py` (none of them are
secrets, they are written down in this repo already) and the two secrets are read at runtime
from outside the tree.

## Turning it on for one machine

Either set two environment variables before starting OpenFlow:

```
OPENFLOW_JIRA_EMAIL=you@example.com
OPENFLOW_JIRA_TOKEN=<an Atlassian API token>
```

or drop a `jira.json` in the OpenFlow **data directory** (`%APPDATA%\OpenFlow` on Windows, or
wherever `OPENFLOW_DATA_DIR` points), which is outside the repository and outside the installer:

```json
{ "email": "you@example.com", "token": "<an Atlassian API token>" }
```

Tokens are made at <https://id.atlassian.com/manage-profile/security/api-tokens>. Overrides for
`url`, `project`, `parent` and `sprint` can go in the same file or as `OPENFLOW_JIRA_*`
variables.

With credentials present the page says "Goes straight to the OpenFlow tracker" and a report
creates a Task under **SCRUM-79** in sprint **9** (*Inbox: user reports*) with the labels
`user-reported` and `needs-triage`, which is the queue described in SCRUM-80. Setting the sprint
on create is best effort: if the site refuses that field the issue is still filed, without the
sprint, and the page says so.

Running list: `parent = SCRUM-79 OR labels = user-reported ORDER BY created DESC`

## What a report carries

Assembled by the backend, because it can see things the page cannot:

- the words the user typed, and the page they were on when they hit the problem;
- OpenFlow's version, whether it is a packaged or dev build, the operating system, the
  architecture and the Python version;
- the USB devices OpenFlow can see, and the halves and modules from the **last** status,
  never a fresh device read (a report is often filed because the device is misbehaving, and
  blocking on it then is the last thing to do);
- the most recent 40 device I/O log entries.

## Identifiers

Hardware IDs, Bluetooth addresses, USB serial numbers and UUIDs name a particular unit, so they
are **removed by default**. The switch on the page puts them back for a problem that looks
specific to one keyboard. Either way the page shows the exact payload under *Show the exact
data* before anything is sent. The redaction walks the whole structure by field name, so a new
field called something like `leftBleAddress` is covered without another edit
(`backend/tests/test_report.py` pins this).

## Before the app is public

The token-on-the-machine arrangement is right for a handful of beta testers who each have their
own copy. It does not scale to public downloads, because those users have no token and land on
copy-or-save. The options, in the order they were discussed:

1. **A relay** holding the token server side, which the app posts to. Keeps the token out of the
   build, works for everyone, costs one small deployment and needs abuse protection.
2. **A prefilled GitHub issue.** No infrastructure and the reporter is the user, but issues on a
   **private** repository need repository access, so beta testers could not file there.
3. **A mail form** that hands the report to the user's own mail client. No infrastructure and no
   account needed; the report arrives as mail rather than as a structured ticket.

Only the sink changes in any of these. The form, the payload and the redaction stay as they are.
