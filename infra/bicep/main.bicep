// Aegis — Azure Bicep (validated, never deployed)
//
// This is never `az deployment create`'d in this repository. CI runs
// `bicep build` and `bicep lint` only (see .github/workflows/ci.yml, job
// `iac-validate`) — there are no Azure credentials configured anywhere in
// CI. See docs/adr/0003-local-first-contract-testing.md and the root
// README's zero-cost constraint. Mirrors infra/terraform's AWS shape:
// managed identity ~ IAM role, Key Vault ~ Secrets Manager, private
// endpoint ~ VPC interface endpoint, AI Foundry account ~ Bedrock.

targetScope = 'resourceGroup'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Deployment environment tag (dev/staging/prod).')
param environment string = 'dev'

@description('Existing subnet resource ID the Key Vault private endpoint attaches to. This module assumes a VNet/subnet already exists — see README.md.')
param privateEndpointSubnetId string

@description('Existing VNet resource ID, used only to link the private DNS zone for Key Vault name resolution.')
param vnetId string

@description('Azure OpenAI / AI Foundry deployment model name, kept in sync by hand with policies/routing.yaml\'s providers.foundry.model.')
param foundryModelDeploymentName string = 'gpt-4o'

var commonTags = {
  project: 'aegis'
  environment: environment
  managedBy: 'bicep'
}

// ---------------------------------------------------------------------------
// Managed identity — what the Aegis API runs as (AWS equivalent: the ECS
// task role in infra/terraform/iam.tf).
// ---------------------------------------------------------------------------
resource aegisApiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aegis-api-${environment}'
  location: location
  tags: commonTags
}

// ---------------------------------------------------------------------------
// Key Vault for the JWT signing key (AWS equivalent: infra/terraform/secrets.tf).
// RBAC-authorized (not vault access policies — the modern, reviewable-in-IaC
// approach), public network access disabled, reached only via the private
// endpoint below.
// ---------------------------------------------------------------------------
resource jwtSigningKeyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: 'kv-aegis-${environment}-jwt'
  location: location
  tags: commonTags
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
    }
  }
}

// Key Vault Secrets User (built-in role) — least privilege: the API's
// identity can read secret values, nothing else (can't create/delete
// secrets or manage the vault itself). Same intent as the Bedrock IAM
// policy's per-model-ARN scoping in infra/terraform/iam.tf.
var keyVaultSecretsUserRoleId = '4633458b-17de-408a-b874-0445c86b69e6'

resource jwtSecretReaderRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(jwtSigningKeyVault.id, aegisApiIdentity.id, keyVaultSecretsUserRoleId)
  scope: jwtSigningKeyVault
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUserRoleId)
    principalId: aegisApiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// No secret *value* resource here, deliberately — same reasoning as
// infra/terraform/secrets.tf: a real secret value must never live in IaC
// source or state. An operator sets it out-of-band after this vault exists.

// ---------------------------------------------------------------------------
// Private endpoint + DNS — Key Vault traffic never leaves Azure's private
// network (AWS equivalent: infra/terraform/network.tf's Bedrock VPC endpoint).
// ---------------------------------------------------------------------------
resource jwtKeyVaultPrivateEndpoint 'Microsoft.Network/privateEndpoints@2023-09-01' = {
  name: 'pe-aegis-${environment}-jwt-kv'
  location: location
  tags: commonTags
  properties: {
    subnet: {
      id: privateEndpointSubnetId
    }
    privateLinkServiceConnections: [
      {
        name: 'aegis-jwt-kv-connection'
        properties: {
          privateLinkServiceId: jwtSigningKeyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
  }
}

resource keyVaultPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: commonTags
}

resource keyVaultPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: keyVaultPrivateDnsZone
  name: 'link-aegis-${environment}'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnetId
    }
  }
}

resource keyVaultPrivateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-09-01' = {
  parent: jwtKeyVaultPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'vaultcore'
        properties: {
          privateDnsZoneId: keyVaultPrivateDnsZone.id
        }
      }
    ]
  }
}

// ---------------------------------------------------------------------------
// Azure AI Foundry account (AWS equivalent: Bedrock, reached in
// src/aegis/providers/foundry_provider.py). Public network access is left
// enabled here — a documented, deliberate scope trade-off, not an oversight;
// see README.md's "Accepted trade-offs" section.
// ---------------------------------------------------------------------------
resource aiFoundryAccount 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: 'aif-aegis-${environment}'
  location: location
  tags: commonTags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    customSubDomainName: 'aif-aegis-${environment}'
    disableLocalAuth: true // no API-key auth — only Entra ID identities (e.g. aegisApiIdentity) may call this
  }
}

resource aiFoundryModelDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiFoundryAccount
  name: foundryModelDeploymentName
  sku: {
    name: 'Standard'
    capacity: 10
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: foundryModelDeploymentName
      version: '2024-08-06'
    }
  }
}

// Cognitive Services OpenAI User (built-in role) — least privilege: can call
// inference on this account, cannot manage it or read/rotate its keys
// (moot anyway, since disableLocalAuth removes key-based auth entirely).
var cognitiveServicesOpenAiUserRoleId = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource aiFoundryRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiFoundryAccount.id, aegisApiIdentity.id, cognitiveServicesOpenAiUserRoleId)
  scope: aiFoundryAccount
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveServicesOpenAiUserRoleId)
    principalId: aegisApiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

output aegisApiIdentityPrincipalId string = aegisApiIdentity.properties.principalId
output aegisApiIdentityClientId string = aegisApiIdentity.properties.clientId
output jwtSigningKeyVaultUri string = jwtSigningKeyVault.properties.vaultUri
output aiFoundryEndpoint string = aiFoundryAccount.properties.endpoint
