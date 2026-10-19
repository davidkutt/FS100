# Runbook: Incident response

Owner: SRE · Applies to: production incidents of every FS100 service · Last reviewed: 2026-10

## Severity levels

| Level | Definition | Response |
|---|---|---|
| SEV1 | Chat or login unavailable for all users, or data loss / leak suspected | Page on-call immediately, all hands, status update every 30 minutes |
| SEV2 | Degraded for many users (slow answers, failed uploads), workaround exists | Page on-call, status update every 60 minutes |
| SEV3 | Minor bug, single user affected, no data at risk | Ticket, next business day |

When in doubt, choose the higher severity; downgrading later is cheap.

## Roles

- **Incident commander (IC):** owns the incident, decides, delegates. The IC does not debug.
- **Operations lead:** investigates and applies mitigations.
- **Communications lead:** writes status updates for users and stakeholders.

For a one-person team the on-call engineer holds all roles but still writes the timeline.

## First 15 minutes

1. Acknowledge the page and open an incident channel named `inc-<date>-<short-name>`.
2. Declare the severity and the IC in the channel.
3. Mitigate before you diagnose: roll back the last release, scale up, or switch the LLM provider.
4. Start a timeline: every action with a timestamp.

## Communication

Status updates follow a fixed template: what is affected, what we know, what we are doing, when the next
update comes. Never speculate about the root cause in external updates.

## Closing an incident

An incident is resolved when the user impact has ended and monitoring is back to baseline for 30
minutes. The IC posts a closing note with duration and impact.

## Postmortem

Every SEV1 and SEV2 gets a written postmortem within **five business days**. Postmortems are blameless:
they describe how the system and the process allowed the failure, not who made a mistake. Each one ends
with action items that have an owner and a due date; they are reviewed in the weekly ops meeting until
done.
