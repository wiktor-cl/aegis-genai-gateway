# Aegis — Azure Bicep (validated, never deployed)

**This is never `az deployment create`'d in this repository.** CI runs `bicep build` and
`bicep lint` only (see `.github/workflows/ci.yml`, job `iac-validate`) — no Azure credentials
are configured anywhere in CI. See
[ADR-0003](../../docs/adr/0003-local-first-contract-testing.md) and the root README's zero-cost
constraint.

## What this provisions (if it were applied)

Mirrors `infra/terraform`'s AWS shape, resource-for-resource:

| This module (Azure) | `infra/terraform` (AWS) | Purpose |
|---|---|---|
| `aegisApiIdentity` (user-assigned managed identity) | `aws_iam_role.aegis_api_task_role` | What the Aegis API authenticates as |
| `jwtSigningKeyVault` (Key Vault, RBAC-authorized, `publicNetworkAccess: Disabled`) | `aws_secretsmanager_secret.jwt_signing_key` | Holds the JWT signing key — no secret *value* in either module, same reasoning |
| `jwtKeyVaultPrivateEndpoint` + private DNS zone | `aws_vpc_endpoint.bedrock_runtime` | Keeps traffic off the public internet |
| `aiFoundryAccount` + `aiFoundryModelDeployment` | Bedrock (referenced via IAM only — Bedrock itself isn't a Terraform resource here, it's an AWS-managed service) | Backs `FoundryProvider` (`src/aegis/providers/foundry_provider.py`) |
| Role assignments (`Key Vault Secrets User`, `Cognitive Services OpenAI User`) | `aws_iam_role_policy` (Bedrock invoke, secret read) | Least privilege: identity can call inference / read the one secret, nothing else |

`disableLocalAuth: true` on the AI Foundry account means API-key auth is turned off entirely —
only Entra ID identities (like `aegisApiIdentity`) can call it, which is a stronger guarantee
than Bedrock's IAM-only model (Azure Cognitive Services accounts support key-based auth by
default; this explicitly closes that off).

## What this does NOT provision

No VNet/subnet, AKS/App Service/Container Apps environment, Postgres/Redis-equivalent, or
Application Gateway — this module assumes the network already exists
(`privateEndpointSubnetId`, `vnetId` parameters), same scope decision as `infra/terraform`.

## Accepted trade-off

The AI Foundry account (`aiFoundryAccount`) does not get a private endpoint — only the Key
Vault does. Network-isolating both would double the module's size to demonstrate the same
private-endpoint pattern twice; Key Vault (the secret) is the higher-value target to isolate,
and this is a portfolio reference architecture, not a from-scratch produced deployment. Noted
here explicitly rather than left implicit — the same "documented gaps, not hidden" approach as
`docs/threat-model.md`.

## Running the validation locally

```bash
cd infra/bicep
bicep build main.bicep --stdout > /dev/null   # fails loudly on any error
bicep lint main.bicep
```
