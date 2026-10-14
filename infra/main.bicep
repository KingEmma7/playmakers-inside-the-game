@description('Azure region for resources.')
param location string = resourceGroup().location

@description('Resource name prefix.')
param namePrefix string = 'gallery'

// Phase 1 stub: intentionally minimal and safe-by-default.
// These resources are placeholders for Phase 2+ and are not deployed in CI.

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
  }
}

resource caEnv 'Microsoft.App/managedEnvironments@2023-11-02-preview' = {
  name: '${namePrefix}-cae'
  location: location
  properties: {
    // Log forwarding intentionally omitted in Phase 1 scaffolding.
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: '${namePrefix}-cosmos'
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
  }
}

resource eventHubsNs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: '${namePrefix}-eh'
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
    capacity: 1
  }
  properties: {
    isAutoInflateEnabled: false
  }
}

output containerAppsEnvironmentName string = caEnv.name
output cosmosAccountName string = cosmos.name
output eventHubsNamespaceName string = eventHubsNs.name

