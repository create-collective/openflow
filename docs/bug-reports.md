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

## Shipping it inside an installer

A build bakes the webhook in, so an installed copy files reports with **no setup by the person
running it**. That is the whole reason for choosing a webhook over an account token: the secret
in the URL can do exactly one thing, fire one rule that creates one issue in one project, and
regenerating the rule's webhook rotates it. An account token would hand every reader the whole
account, so one must never be built in.

The build takes the URL from `OPENFLOW_REPORT_WEBHOOK`, or from `backend/report-sink.json`
(`{"webhook": "https://..."}`), which is gitignored. Neither is in the repository, so the URL
never enters git history.

```
OPENFLOW_REPORT_WEBHOOK=https://... npm run build:win
```

The spec prints which host reports will go to, or says reports will be copy-and-save only when
no webhook is configured, so a build never quietly ships without one. Runtime precedence is
environment, then `jira.json` on the machine, then whatever the build shipped, so a tester can
redirect their own reports and a developer can override both.

## Setting the rule up: an automation incoming webhook

Atlassian generates and hosts the URL, so there is nothing to buy, host or deploy. The secret in
it can do exactly one thing: fire that one rule. It cannot read, edit, or reach another project,
and regenerating the webhook rotates it. The worst an extracted URL buys anyone is junk tickets
in the inbox queue.

In Jira: **Project settings → Automation → Create rule**.

1. Trigger: **Incoming webhook**. Copy the URL it shows. For "Execute this rule with", choose
   **No issues from the webhook** (the rule creates one; it is not acting on existing issues).
2. Action: **Create issue**
   - Project `SCRUM`, issue type `Task`
   - Parent: `SCRUM-79`
   - Summary: `{{webhookData.summary}}`
   - Description: `{{webhookData.description}}`
   - Labels: `user-reported`, `needs-triage`
   - Sprint: `Inbox: user reports`
3. Turn the rule on, then put the URL where OpenFlow will find it:

```
OPENFLOW_JIRA_WEBHOOK=https://automation.atlassian.com/pro/hooks/<the rest of it>
```

or in `jira.json` in the data directory: `{ "webhook": "https://automation.atlassian.com/..." }`

The body OpenFlow posts is `summary`, `description`, `contact`, `page` and `source`, so any of
those can be read in the rule as `{{webhookData.<name>}}`.

Two things to know. Automation answers before its rule has run, so OpenFlow cannot report the
issue key: the page says the report was sent, not that it was filed as SCRUM-123. And automation
rule executions are metered by Jira plan, so check the limit if reports ever come in volume.

### A gotcha when running the dev build

`jira.json` is read from the **data directory**, and a dev launch usually overrides that with
`OPENFLOW_DATA_DIR`. A file in `%APPDATA%\OpenFlow` is then invisible to it, even though the
packaged app would find it. For dev, either put a copy in whatever `OPENFLOW_DATA_DIR` points
at, or set `OPENFLOW_JIRA_WEBHOOK` in the environment you launch from. The override is
deliberate: the data directory is authoritative, so a scratch data directory (a test run, for
instance) never picks up the real credentials by accident.

## The full-access way: an account API token (a trusted machine only)

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

This path has full REST access, so it returns the issue key and can set the sprint on create.
It creates a Task under **SCRUM-79** in sprint **9** (*Inbox: user reports*) with the labels
`user-reported` and `needs-triage`, the queue described in SCRUM-80. Setting the sprint is best
effort: if the site refuses that field the issue is still filed, without the sprint, and the page
says so.

**A webhook wins when both are configured**, since it can only create. The account token path
then never runs.

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

A webhook shipped to a handful of testers who are asked not to redistribute is a reasonable
trade. For public downloads the URL would be in every copy, so decide between:

1. **Keep the webhook.** Its blast radius is spam in one queue, which may simply be acceptable.
   Add rate limiting in the app and be ready to regenerate the URL.
2. **A relay** holding the credential server side, which the app posts to. Nothing authenticating
   in the build at all, works for everyone, costs one small deployment.
3. **A prefilled GitHub issue.** No infrastructure and the reporter is the user, but issues on a
   **private** repository need repository access, so beta testers could not file there.
4. **A mail form** that hands the report to the user's own mail client. No infrastructure and no
   account needed; the report arrives as mail rather than as a structured ticket.

Only the sink changes in any of these. The form, the payload and the redaction stay as they are.
