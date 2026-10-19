# Runbook: Azure cost guard

Owner: platform team · Applies to: the FS100 Azure subscription (Phase 5) · Last reviewed: 2026-10

## Budget and alerts

- The subscription has a monthly **budget of 30 USD**.
- Alerts fire at 50 %, 80 % and 100 % of actual cost and at 100 % of forecast cost, by e-mail to the
  owner.
- The budget is the only resource that survives a teardown.

## Tagging

Every resource carries the tags `project=kb-agent`, `env=dev|demo` and `owner=<alias>`. Cost analysis is
grouped by `project` and `env`; untagged resources are a bug. An Azure Policy denies resource groups
without the `project` tag.

## Ephemeral by default

The AKS cluster is created for a demo or a test session and destroyed afterwards — it is never left
running overnight. Container Apps scale to zero when idle. The container registry (ACR Basic) and the
Key Vault stay, because they cost only cents per day.

## Teardown

```bash
./infra/azure/teardown.sh            # deletes every resource group tagged project=kb-agent
az group list --tag project=kb-agent --query "[].name" -o tsv   # must print nothing
```

Run the teardown at the end of every working session that created cluster resources.

## When an alert fires

1. Open *Cost Management → Cost analysis*, group by resource.
2. Look for forgotten clusters, public IPs and premium disks — they are the usual cause.
3. Run the teardown if nothing must keep running.
4. If the forecast still exceeds the budget, lower the node count or VM size before the next session.

## Quota

New subscriptions have a low vCPU quota for B-series VMs. Check it before the first cluster
(`az vm list-usage --location westeurope -o table`) and request an increase early — approval can take
several days.
