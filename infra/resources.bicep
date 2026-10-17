param location string
param tags object
param modelCapacity int
param principalId string
param principalType string
param apiImage string
param webImage string
param maxLiveMatches int
param dailyLiveMatches int
param logDailyQuotaGb string
param enableSpeech bool

var suffix = take(uniqueString(subscription().id, resourceGroup().id), 6)
var accountName = 'ais-playmakers-${suffix}'
var projectName = 'proj-playmakers'
var deploymentName = 'gpt-41-mini'
var apiName = 'ca-playmakers-api'
var webName = 'ca-playmakers-web'

// Built-in role definition ids.
var azureAiUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var openAiUser = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
var speechUser = 'f2dc8367-1007-4938-bd23-fe263f013447'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-playmakers'
  location: location
  tags: tags
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-playmakers'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json(logDailyQuotaGb) }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: 'appi-playmakers'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logs.id
  }
}

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: accountName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: accountName
    allowProjectManagement: true
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Playmakers'
    description: 'Playmakers agent crew'
  }
}

resource model 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: deploymentName
  dependsOn: [project]
  sku: {
    name: 'GlobalStandard'
    capacity: modelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4.1-mini'
      version: '2025-04-14'
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

// Lets the Foundry portal Tracing view read the App Insights traces.
resource tracing 'Microsoft.CognitiveServices/accounts/connections@2025-06-01' = {
  parent: account
  name: 'appi-playmakers'
  dependsOn: [model]
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: appInsights.properties.ConnectionString }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

var identityRoles = enableSpeech ? [azureAiUser, openAiUser, speechUser] : [azureAiUser, openAiUser]

resource identityAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in identityRoles: {
    scope: account
    name: guid(account.id, identity.id, role)
    properties: {
      principalId: identity.properties.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

resource developerAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for role in (empty(principalId) ? [] : [azureAiUser, openAiUser]): {
    scope: account
    name: guid(account.id, principalId, role)
    properties: {
      principalId: principalId
      principalType: principalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role)
    }
  }
]

// Consumption only: no workload profiles, VNet or planned maintenance (those add a management fee).
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: 'cae-playmakers'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

var apiUrl = 'https://${apiName}.${environment.properties.defaultDomain}'
var webUrl = 'https://${webName}.${environment.properties.defaultDomain}'
var projectEndpoint = 'https://${accountName}.services.ai.azure.com/api/projects/${projectName}'
var speechEnv = enableSpeech
  ? [
      { name: 'AZURE_SPEECH_REGION', value: location }
      { name: 'AZURE_SPEECH_RESOURCE_ID', value: account.id }
      { name: 'AZURE_SPEECH_ENDPOINT', value: 'https://${accountName}.cognitiveservices.azure.com' }
    ]
  : []

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  tags: union(tags, { 'azd-service-name': 'api' })
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${identity.id}': {} }
  }
  dependsOn: [identityAccess, model]
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: apiImage
          resources: { cpu: json('1.0'), memory: '2Gi' }
          env: concat(
            [
              { name: 'AZURE_AI_PROJECT_ENDPOINT', value: projectEndpoint }
              { name: 'AZURE_AI_MODEL_DEPLOYMENT', value: deploymentName }
              { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId }
              { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
              { name: 'CORS_ORIGINS', value: webUrl }
              { name: 'STATS_MCP_URL', value: 'http://127.0.0.1:8000/stats-mcp/' }
              { name: 'WHATIF_WORKERS', value: '1' }
              { name: 'PLAYMAKERS_MAX_LIVE_MATCHES', value: string(maxLiveMatches) }
              { name: 'PLAYMAKERS_DAILY_LIVE_MATCHES', value: string(dailyLiveMatches) }
            ],
            speechEnv
          )
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 10
            }
          ]
        }
      ]
      // In-memory match sessions and checkpoints need exactly one replica when awake.
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: webName
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  properties: {
    environmentId: environment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 80
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            { name: 'API_BASE', value: apiUrl }
            { name: 'API_UPSTREAM', value: '' }
          ]
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 }
    }
  }
}

output projectEndpoint string = projectEndpoint
output modelDeployment string = model.name
output identityClientId string = identity.properties.clientId
output apiUrl string = apiUrl
output webUrl string = webUrl
