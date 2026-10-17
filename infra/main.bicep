targetScope = 'subscription'

@minLength(1)
@maxLength(40)
@description('azd environment name; used for tags and the resource group name.')
param environmentName string

@description('Region for every resource. gpt-4.1-mini GlobalStandard is offered in eastus2.')
param location string = 'eastus2'

@description('Resource group to create.')
param resourceGroupName string = 'rg-playmakers-demo'

@description('Model deployment capacity in thousands of tokens per minute (1-100). Keep it small; it is also a rate ceiling.')
param modelCapacity string = '50'

@description('Object id of the developer running azd (AZURE_PRINCIPAL_ID); empty skips developer roles.')
param principalId string = ''

@allowed(['User', 'ServicePrincipal'])
param principalType string = 'User'

@description('Public GHCR image for the API.')
param apiImage string = 'ghcr.io/kingemma7/playmakers-api:latest'

@description('Public GHCR image for the web app.')
param webImage string = 'ghcr.io/kingemma7/playmakers-web:latest'

@description('Most live-model matches that may run at once; further matches use the offline crew.')
@minValue(0)
param maxLiveMatches int = 2

@description('Live-model matches allowed per UTC day; further matches use the offline crew.')
@minValue(0)
param dailyLiveMatches int = 15

@description('Log Analytics daily ingestion cap in GB.')
param logDailyQuotaGb string = '0.2'

@description('"true" also grants the identity Speech access on the Foundry account and turns on the Azure voice.')
param enableSpeech string = 'false'

var tags = { 'azd-env-name': environmentName, app: 'playmakers' }

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module resources 'resources.bicep' = {
  name: 'playmakers-resources'
  scope: rg
  params: {
    location: location
    tags: tags
    modelCapacity: min(max(int(modelCapacity), 1), 100)
    principalId: principalId
    principalType: principalType
    apiImage: apiImage
    webImage: webImage
    maxLiveMatches: maxLiveMatches
    dailyLiveMatches: dailyLiveMatches
    logDailyQuotaGb: logDailyQuotaGb
    enableSpeech: toLower(enableSpeech) == 'true'
  }
}

output AZURE_RESOURCE_GROUP string = rg.name
output AZURE_AI_PROJECT_ENDPOINT string = resources.outputs.projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT string = resources.outputs.modelDeployment
output AZURE_CLIENT_ID string = resources.outputs.identityClientId
output API_URL string = resources.outputs.apiUrl
output WEB_URL string = resources.outputs.webUrl
