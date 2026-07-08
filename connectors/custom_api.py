"""
Custom API connector for Work IQ.

Allows users to register and query arbitrary REST APIs and data sources
through a unified interface. Supports multiple authentication methods.
"""

from typing import Any, Dict, List, Optional
import aiohttp
import base64
import json


from .base import DataConnector, ConnectorConfig, ConnectorType, ConnectorResponse, AuthType


class CustomAPIConnector(DataConnector):
    """
    Generic REST API connector.
    
    Allows integration with any REST API by specifying:
    - Base URL
    - Authentication (API Key, OAuth 2.0, Bearer Token, Basic Auth)
    - Resource mappings and field mappings
    
    Example config:
    {
        "id": "salesforce_api",
        "type": "custom_api",
        "config": {
            "base_url": "https://api.salesforce.com/services/data/v57.0",
            "auth": {
                "type": "oauth2",
                "token_url": "https://login.salesforce.com/services/oauth2/token",
                "client_id": "...",
                "client_secret": "..."
            },
            "resources": {
                "opportunities": {
                    "endpoint": "/query?q=SELECT+Id,Name+FROM+Opportunity",
                    "field_mapping": {
                        "id": "Id",
                        "title": "Name"
                    }
                }
            }
        }
    }
    """
    
    def __init__(self, config: ConnectorConfig):
        """Initialize custom API connector."""
        super().__init__(config)
        self.connector_id_value = config.connector_id
        self._session: Optional[aiohttp.ClientSession] = None
        self._bearer_token: Optional[str] = None
    
    @property
    def connector_id(self) -> str:
        """Unique identifier."""
        return self.connector_id_value
    
    @property
    def connector_name(self) -> str:
        """Human-readable name."""
        base_url = self.config.custom_config.get("base_url", "") if self.config.custom_config else ""
        return f"Custom API: {base_url.split('/')[2] if '/' in base_url else base_url}"
    
    @property
    def connector_type(self) -> ConnectorType:
        """Connector type."""
        return ConnectorType.CUSTOM_API
    
    @property
    def supported_resources(self) -> List[str]:
        """Get list of configured resources."""
        if not self.config.custom_config or "resources" not in self.config.custom_config:
            return []
        return list(self.config.custom_config["resources"].keys())
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def _build_headers(self) -> Dict[str, str]:
        """Build request headers with authentication."""
        headers = {"Content-Type": "application/json"}
        
        if not self.config.auth_config:
            return headers
        
        auth_type = self.config.auth_config.get("type", "")
        
        if auth_type == "api_key":
            key_header = self.config.auth_config.get("header_name", "X-API-Key")
            headers[key_header] = self.config.auth_config.get("api_key", "")
        
        elif auth_type == "bearer_token":
            if self._bearer_token:
                headers["Authorization"] = f"Bearer {self._bearer_token}"
        
        elif auth_type == "basic_auth":
            username = self.config.auth_config.get("username", "")
            password = self.config.auth_config.get("password", "")
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        
        return headers
    
    async def authenticate(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """
        Authenticate with the custom API.
        
        Supports multiple auth methods:
        - API Key: included in headers
        - Bearer Token: OAuth 2.0 or direct token
        - Basic Auth: username/password
        """
        try:
            auth_config = credentials or self.config.auth_config or {}
            auth_type = auth_config.get("type", "")
            
            if not auth_type:
                # If no auth configured, assume public API
                self._authenticated = True
                return True
            
            if auth_type == "api_key":
                # Validate API key is present
                if "api_key" not in auth_config:
                    return False
                self._authenticated = True
                return True
            
            elif auth_type == "bearer_token":
                # Try to get token via OAuth 2.0 or use provided token
                token = auth_config.get("token")
                if token:
                    self._bearer_token = token
                    self._authenticated = True
                    return True
                
                # Try OAuth 2.0 flow
                if "token_url" in auth_config:
                    return await self._oauth2_flow(auth_config)
                
                return False
            
            elif auth_type == "basic_auth":
                # Validate username/password present
                if "username" not in auth_config or "password" not in auth_config:
                    return False
                self._authenticated = True
                return True
            
            else:
                return False
        except Exception as e:
            return False
    
    async def _oauth2_flow(self, auth_config: Dict[str, Any]) -> bool:
        """Execute OAuth 2.0 flow to obtain token."""
        try:
            session = await self._get_session()
            
            payload = {
                "client_id": auth_config.get("client_id"),
                "client_secret": auth_config.get("client_secret"),
                "grant_type": "client_credentials",
            }
            
            async with session.post(auth_config["token_url"], data=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    self._bearer_token = data.get("access_token")
                    self._authenticated = True
                    return True
            
            return False
        except Exception as e:
            return False
    
    async def fetch_resource(
        self,
        resource_type: str,
        filters: Optional[Dict[str, Any]] = None,
        skip: int = 0,
        top: int = 100,
    ) -> ConnectorResponse:
        """
        Fetch resources from the custom API.
        
        Args:
            resource_type: Name of configured resource
            filters: Optional query filters
            skip: Pagination offset
            top: Result limit
            
        Returns:
            ConnectorResponse with normalized results.
        """
        try:
            if not self.config.custom_config:
                return ConnectorResponse(
                    connector_id=self.connector_id,
                    connector_name=self.connector_name,
                    resource_type=resource_type,
                    items=[],
                    errors=["No configuration provided"],
                )
            
            resources = self.config.custom_config.get("resources", {})
            if resource_type not in resources:
                return ConnectorResponse(
                    connector_id=self.connector_id,
                    connector_name=self.connector_name,
                    resource_type=resource_type,
                    items=[],
                    errors=[f"Resource not configured: {resource_type}"],
                )
            
            base_url = self.config.custom_config.get("base_url", "")
            resource_config = resources[resource_type]
            endpoint = resource_config.get("endpoint", "")
            
            # Build full URL
            url = f"{base_url}{endpoint}"
            
            # Add pagination if supported
            if "?" in endpoint:
                url += f"&skip={skip}&top={top}"
            else:
                url += f"?skip={skip}&top={top}"
            
            # Fetch data
            session = await self._get_session()
            headers = await self._build_headers()
            
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return ConnectorResponse(
                        connector_id=self.connector_id,
                        connector_name=self.connector_name,
                        resource_type=resource_type,
                        items=[],
                        errors=[f"API returned {resp.status}"],
                    )
                
                data = await resp.json()
                
                # Extract items based on configuration
                items = data if isinstance(data, list) else data.get("items", [data])
                
                # Apply field mapping if configured
                field_mapping = resource_config.get("field_mapping", {})
                if field_mapping:
                    items = self._map_fields(items, field_mapping)
                
                return ConnectorResponse(
                    connector_id=self.connector_id,
                    connector_name=self.connector_name,
                    resource_type=resource_type,
                    items=items,
                    total_count=len(items),
                )
        
        except Exception as e:
            return ConnectorResponse(
                connector_id=self.connector_id,
                connector_name=self.connector_name,
                resource_type=resource_type,
                items=[],
                errors=[str(e)],
            )
    
    async def search(
        self,
        query: str,
        resource_types: Optional[List[str]] = None,
        skip: int = 0,
        top: int = 50,
    ) -> ConnectorResponse:
        """
        Search resources by implementing full-text search via API.
        
        Note: Implementation depends on API capabilities.
        """
        # Custom APIs may not support search; return unsupported
        return ConnectorResponse(
            connector_id=self.connector_id,
            connector_name=self.connector_name,
            resource_type="search_results",
            items=[],
            errors=["Search not supported for this custom API"],
        )
    
    def _map_fields(self, items: List[Dict], mapping: Dict[str, str]) -> List[Dict]:
        """
        Map API fields to standard Work IQ field names.
        
        Args:
            items: List of API items
            mapping: Mapping of standard_name -> api_name
            
        Returns:
            Items with remapped fields.
        """
        mapped = []
        for item in items:
            mapped_item = {}
            for standard_name, api_name in mapping.items():
                if api_name in item:
                    mapped_item[standard_name] = item[api_name]
            # Include unmapped fields
            for key, value in item.items():
                if key not in [v for v in mapping.values()]:
                    mapped_item[key] = value
            mapped.append(mapped_item)
        return mapped
    
    async def __del__(self):
        """Clean up HTTP session."""
        if self._session:
            await self._session.close()
