# Work IQ Data Connectors - Developer Guide

## Overview

The Work IQ connector framework provides a unified interface for integrating data from multiple sources. Users can choose from built-in connectors or register custom API endpoints without modifying agent code.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Work IQ Agent                           │
├─────────────────────────────────────────────────────────────────┤
│                      Connector Manager                          │
│  (orchestrates multi-source queries, handles auth, caching)    │
├────────────┬──────────────┬─────────────┬──────────────────────┤
│ MS Graph   │ GCP          │ AWS         │ Custom API           │
│ Connector  │ Connector    │ Connector   │ Connector            │
├────────────┼──────────────┼─────────────┼──────────────────────┤
│ M365 APIs  │ Workspace    │ S3, DDB,    │ User-registered      │
│ (Messages, │ APIs         │ CloudWatch  │ REST endpoints       │
│ Meetings,  │ (Gmail,      │ (Logs,      │ (Salesforce, Jira,   │
│ Files)     │ Calendar,    │ Metrics,    │ Internal APIs, etc.) │
│            │ Drive)       │ Tables)     │                      │
└────────────┴──────────────┴─────────────┴──────────────────────┘
```

## Built-in Connectors

### 1. Microsoft Graph Connector
**ID:** `msgraph`  
**Auth Types:** OAuth 2.0  
**Resources:** emails, meetings, calendar_events, files, people, teams, chats

```python
from connectors import MSGraphConnector, ConnectorConfig, ConnectorType

config = ConnectorConfig(
    connector_id="msgraph_primary",
    connector_type=ConnectorType.MSGRAPH,
    auth_config={
        "type": "oauth2",
        "tenant_id": "your-tenant-id",
        "client_id": "your-client-id",
        "client_secret": "your-client-secret"
    }
)

connector = MSGraphConnector(config)
```

### 2. Google Cloud Connector
**ID:** `gcp`  
**Auth Types:** Service Account, OAuth 2.0  
**Resources:** gmail_messages, calendar_events, drive_files, meet_recordings, chat_messages

```python
config = ConnectorConfig(
    connector_id="gcp_workspace",
    connector_type=ConnectorType.GCP,
    auth_config={
        "type": "service_account",
        "service_account_json": "path/to/service-account-key.json"
    }
)

connector = GCPConnector(config)
```

### 3. AWS Connector
**ID:** `aws`  
**Auth Types:** IAM Access Keys, STS Assumed Role  
**Resources:** s3_objects, dynamodb_items, cloudwatch_logs, cloudwatch_metrics, sns_messages, sqs_messages

```python
config = ConnectorConfig(
    connector_id="aws_primary",
    connector_type=ConnectorType.AWS,
    auth_config={
        "type": "aws_iam",
        "access_key_id": "your-access-key",
        "secret_access_key": "your-secret-key"
    }
)

connector = AWSConnector(config)
```

### 4. Social Media Connector
**ID:** `social_media`  
**Platforms:** LinkedIn, Twitter/X, Facebook  
**Auth Types:** OAuth 2.0, Bearer Token

```python
config = ConnectorConfig(
    connector_id="linkedin_network",
    connector_type=ConnectorType.SOCIAL_MEDIA,
    auth_config={
        "type": "oauth2",
        "client_id": "your-client-id",
        "client_secret": "your-client-secret"
    },
    custom_config={"platform": "linkedin"}
)

connector = SocialMediaConnector(config)
```

## Custom API Connector

Register any REST API in seconds without writing code:

```python
from connectors import CustomAPIConnector, ConnectorConfig, ConnectorType

config = ConnectorConfig(
    connector_id="salesforce_crm",
    connector_type=ConnectorType.CUSTOM_API,
    auth_config={
        "type": "oauth2",
        "token_url": "https://login.salesforce.com/services/oauth2/token",
        "client_id": "...",
        "client_secret": "..."
    },
    custom_config={
        "base_url": "https://yourinstance.salesforce.com/services/data/v57.0",
        "resources": {
            "opportunities": {
                "endpoint": "/query?q=SELECT+Id,Name,Amount+FROM+Opportunity",
                "field_mapping": {
                    "id": "Id",
                    "title": "Name",
                    "amount": "Amount"
                }
            }
        }
    }
)

connector = CustomAPIConnector(config)
```

## Using the Connector Manager

### Initialization

```python
from connectors import get_connector_manager, ConnectorConfig, ConnectorType
from connectors import MSGraphConnector, CustomAPIConnector

manager = get_connector_manager()

# Register MS Graph
msgraph_config = ConnectorConfig(
    connector_id="msgraph_primary",
    connector_type=ConnectorType.MSGRAPH,
    auth_config={"tenant_id": "...", "client_id": "..."}
)
manager.register_connector(MSGraphConnector(msgraph_config))

# Register Salesforce
sf_config = ConnectorConfig(
    connector_id="salesforce",
    connector_type=ConnectorType.CUSTOM_API,
    auth_config={"type": "oauth2", ...},
    custom_config={"base_url": "https://...", "resources": {...}}
)
manager.register_connector(CustomAPIConnector(sf_config))
```

### Authenticate

```python
# Authenticate single connector
authenticated = await manager.authenticate_connector("msgraph_primary")

# Authenticate all enabled connectors
results = await manager.authenticate_all()
# Results: {"msgraph_primary": True, "salesforce": True, ...}
```

### Fetch from Single Source

```python
response = await manager.fetch_resource(
    connector_id="msgraph_primary",
    resource_type="emails",
    filters={"is_read": False},
    top=50
)

for item in response.items:
    print(item)
```

### Fetch from Multiple Sources (Parallel)

```python
# Query emails from MS Graph and Gmail simultaneously
responses = await manager.fetch_resource_from_all(
    resource_type="emails",
    connector_ids=["msgraph_primary", "gcp_workspace"],
    filters={"is_read": False},
    top=20
)

for response in responses:
    print(f"From {response.connector_name}:")
    for item in response.items:
        print(f"  - {item}")
```

### Search Across Sources

```python
results = await manager.search(
    query="Q4 planning",
    resource_types=["emails", "files"],
    connector_ids=["msgraph_primary", "gcp_workspace"]
)

for response in results:
    if response.items:
        print(f"{response.connector_name} ({response.resource_type}): {len(response.items)} results")
```

### List Available Connectors

```python
connectors = manager.list_connectors(include_disabled=True)
for connector in connectors:
    print(f"{connector['connector_name']} - Authenticated: {connector['authenticated']}")
```

## Creating Custom Connectors

### Step 1: Inherit from DataConnector

```python
from connectors import DataConnector, ConnectorConfig, ConnectorType, ConnectorResponse

class MyCustomConnector(DataConnector):
    
    @property
    def connector_id(self) -> str:
        return self.config.connector_id
    
    @property
    def connector_name(self) -> str:
        return "My Custom Data Source"
    
    @property
    def connector_type(self) -> ConnectorType:
        return ConnectorType.CUSTOM_API
    
    @property
    def supported_resources(self) -> List[str]:
        return ["items", "records", "entries"]
```

### Step 2: Implement Required Methods

```python
    async def authenticate(self, credentials=None) -> bool:
        """Verify credentials and connect to your service."""
        auth_config = credentials or self.config.auth_config
        try:
            # Validate API credentials
            # Connect to your service
            self._authenticated = True
            return True
        except Exception as e:
            self._authenticated = False
            return False
    
    async def fetch_resource(self, resource_type, filters=None, skip=0, top=100) -> ConnectorResponse:
        """Retrieve data from your service."""
        try:
            # Query your API
            items = await self._query_api(resource_type, filters, skip, top)
            
            return ConnectorResponse(
                connector_id=self.connector_id,
                connector_name=self.connector_name,
                resource_type=resource_type,
                items=items,
                total_count=len(items)
            )
        except Exception as e:
            return ConnectorResponse(
                connector_id=self.connector_id,
                connector_name=self.connector_name,
                resource_type=resource_type,
                items=[],
                errors=[str(e)]
            )
    
    async def search(self, query, resource_types=None, skip=0, top=50) -> ConnectorResponse:
        """Search your data source."""
        try:
            items = await self._search_api(query, resource_types, skip, top)
            
            return ConnectorResponse(
                connector_id=self.connector_id,
                connector_name=self.connector_name,
                resource_type="search_results",
                items=items,
                total_count=len(items)
            )
        except Exception as e:
            return ConnectorResponse(
                connector_id=self.connector_id,
                connector_name=self.connector_name,
                resource_type="search_results",
                items=[],
                errors=[str(e)]
            )
```

### Step 3: Register Your Connector

```python
from connectors import get_connector_manager

manager = get_connector_manager()

config = ConnectorConfig(
    connector_id="my_connector",
    connector_type=ConnectorType.CUSTOM_API,
    auth_config={"api_key": "..."}
)

connector = MyCustomConnector(config)
manager.register_connector(connector)

await manager.authenticate_connector("my_connector")
```

## Authentication Methods

### API Key
```python
"auth": {
    "type": "api_key",
    "header_name": "X-API-Key",
    "api_key": "your-api-key"
}
```

### Bearer Token
```python
"auth": {
    "type": "bearer_token",
    "token": "your-bearer-token"
}
```

### OAuth 2.0
```python
"auth": {
    "type": "oauth2",
    "token_url": "https://auth.example.com/oauth/token",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret"
}
```

### Basic Auth
```python
"auth": {
    "type": "basic_auth",
    "username": "your-username",
    "password": "your-password"
}
```

## Configuration File

Store connector configurations in `connectors/config.json`:

```json
{
  "connectors": [
    {
      "id": "msgraph_primary",
      "type": "msgraph",
      "enabled": true,
      "auth": {
        "type": "oauth2",
        "tenant_id": "${AZURE_TENANT_ID}",
        "client_id": "${AZURE_CLIENT_ID}",
        "client_secret": "${AZURE_CLIENT_SECRET}"
      }
    }
  ]
}
```

Support environment variable substitution using `${VAR_NAME}` syntax.

## Response Format

All connectors return standardized `ConnectorResponse` objects:

```python
@dataclass
class ConnectorResponse:
    connector_id: str           # Unique connector ID
    connector_name: str         # Human-readable name
    resource_type: str          # Type of resource fetched
    items: List[Dict]           # Actual data items
    total_count: int            # Total items (for pagination)
    next_token: Optional[str]   # Pagination token
    errors: List[str]           # Error messages if any
```

## Examples

### Query Multiple Data Sources

```python
async def get_all_documents():
    """Fetch documents from MS Graph, Google Drive, and S3."""
    manager = get_connector_manager()
    
    responses = await manager.fetch_resource_from_all(
        resource_type="files",
        connector_ids=["msgraph_primary", "gcp_drive", "aws_s3"]
    )
    
    all_documents = []
    for response in responses:
        if response.errors:
            print(f"Error from {response.connector_name}: {response.errors}")
        else:
            all_documents.extend(response.items)
    
    return all_documents
```

### Add Custom API in Minutes

```python
# Register Jira without writing code
config = ConnectorConfig(
    connector_id="jira",
    connector_type=ConnectorType.CUSTOM_API,
    auth_config={
        "type": "basic_auth",
        "username": "user@example.com",
        "password": os.getenv("JIRA_API_TOKEN")
    },
    custom_config={
        "base_url": "https://company.atlassian.net/rest/api/2",
        "resources": {
            "issues": {
                "endpoint": "/search?jql=assignee=currentUser()",
                "field_mapping": {"id": "key", "title": "fields.summary"}
            }
        }
    }
)

manager.register_connector(CustomAPIConnector(config))
```

## Troubleshooting

### Authentication Fails
- Check credentials are valid
- Verify environment variables are set
- Test API access manually first

### Empty Results
- Verify resource_type is supported by connector
- Check filters are compatible with source
- Review connector logs for API errors

### Performance Issues
- Use specific resource_types (reduces API load)
- Enable caching at manager level
- Limit top/skip parameters appropriately
- Consider serial vs parallel queries

## Best Practices

1. **Always authenticate before querying**
   ```python
   if await manager.authenticate_connector("salesforce"):
       response = await manager.fetch_resource("salesforce", "opportunities")
   ```

2. **Handle errors gracefully**
   ```python
   response = await manager.fetch_resource(...)
   if response.errors:
       logger.error(f"Query failed: {response.errors}")
   ```

3. **Use resource type filtering**
   ```python
   # Bad: Query everything
   responses = await manager.search("report")
   
   # Good: Specify resource types
   responses = await manager.search(
       "report", 
       resource_types=["files", "emails"]
   )
   ```

4. **Test custom API credentials separately**
   ```python
   # Validate before registering
   test_response = await connector.fetch_resource("items", top=1)
   if not test_response.errors:
       manager.register_connector(connector)
   ```

## Contributing

To add a new built-in connector:

1. Create new file: `connectors/myservice.py`
2. Implement `DataConnector` interface
3. Add to `connectors/__init__.py` exports
4. Update `config.example.json`
5. Add unit tests to `tests/test_connectors.py`
