"""
Base connector class and interfaces for Work IQ data sources.

All connectors (MS Graph, GCP, AWS, Social Media, Custom API) inherit from
DataConnector and implement the standard interface for seamless integration.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum


class ConnectorType(str, Enum):
    """Supported connector types."""
    MSGRAPH = "msgraph"
    GCP = "gcp"
    AWS = "aws"
    SOCIAL_MEDIA = "social_media"
    CUSTOM_API = "custom_api"


class AuthType(str, Enum):
    """Authentication methods supported by connectors."""
    OAUTH2 = "oauth2"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    SERVICE_ACCOUNT = "service_account"
    AWS_IAM = "aws_iam"


@dataclass
class ConnectorConfig:
    """Configuration for a connector instance."""
    connector_id: str
    connector_type: ConnectorType
    enabled: bool = True
    auth_config: Optional[Dict[str, Any]] = None
    custom_config: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResponse:
    """Normalized response from a connector."""
    connector_id: str
    connector_name: str
    resource_type: str
    items: List[Dict[str, Any]]
    total_count: int = 0
    next_token: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "resource_type": self.resource_type,
            "items": self.items,
            "total_count": self.total_count,
            "next_token": self.next_token,
            "errors": self.errors,
        }


class DataConnector(ABC):
    """
    Abstract base class for all Work IQ data sources.
    
    Concrete implementations must provide authentication, retrieval,
    search, and CRUD operations for Work IQ data types.
    """
    
    def __init__(self, config: ConnectorConfig):
        """Initialize connector with configuration."""
        self.config = config
        self._authenticated = False
    
    @property
    @abstractmethod
    def connector_id(self) -> str:
        """Unique identifier for this connector instance."""
        pass
    
    @property
    @abstractmethod
    def connector_name(self) -> str:
        """Human-readable name of the connector."""
        pass
    
    @property
    @abstractmethod
    def connector_type(self) -> ConnectorType:
        """Type of connector (msgraph, gcp, aws, etc.)."""
        pass
    
    @property
    @abstractmethod
    def supported_resources(self) -> List[str]:
        """
        List of supported resource types.
        
        Standard resources: emails, meetings, files, people, teams, 
        calendar_events, chats, notes, etc.
        """
        pass
    
    @abstractmethod
    async def authenticate(self, credentials: Optional[Dict[str, Any]] = None) -> bool:
        """
        Authenticate with the data source.
        
        Args:
            credentials: Optional credentials override. If None, use config.
            
        Returns:
            True if authentication successful, False otherwise.
        """
        pass
    
    @abstractmethod
    async def fetch_resource(
        self,
        resource_type: str,
        filters: Optional[Dict[str, Any]] = None,
        skip: int = 0,
        top: int = 100,
    ) -> ConnectorResponse:
        """
        Retrieve resources from the data source.
        
        Args:
            resource_type: Type of resource to fetch (emails, meetings, etc.)
            filters: Optional filter criteria
            skip: Number of items to skip (pagination)
            top: Maximum number of items to return
            
        Returns:
            ConnectorResponse with normalized data.
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query: str,
        resource_types: Optional[List[str]] = None,
        skip: int = 0,
        top: int = 50,
    ) -> ConnectorResponse:
        """
        Search for resources matching a query.
        
        Args:
            query: Search query string
            resource_types: Optional list of resource types to search
            skip: Number of items to skip
            top: Maximum number of results
            
        Returns:
            ConnectorResponse with search results.
        """
        pass
    
    async def create_entity(
        self,
        resource_type: str,
        entity_data: Dict[str, Any],
    ) -> ConnectorResponse:
        """
        Create a new entity in the data source.
        
        Args:
            resource_type: Type of resource to create
            entity_data: Data for the new entity
            
        Returns:
            ConnectorResponse with created entity.
            
        Note:
            Default implementation returns error. Override in connectors that support CRUD.
        """
        return ConnectorResponse(
            connector_id=self.connector_id,
            connector_name=self.connector_name,
            resource_type=resource_type,
            items=[],
            errors=["Create operation not supported by this connector"],
        )
    
    async def update_entity(
        self,
        resource_type: str,
        entity_id: str,
        entity_data: Dict[str, Any],
    ) -> ConnectorResponse:
        """
        Update an existing entity in the data source.
        
        Args:
            resource_type: Type of resource to update
            entity_id: ID of the entity
            entity_data: New data for the entity
            
        Returns:
            ConnectorResponse with updated entity.
            
        Note:
            Default implementation returns error. Override in connectors that support CRUD.
        """
        return ConnectorResponse(
            connector_id=self.connector_id,
            connector_name=self.connector_name,
            resource_type=resource_type,
            items=[],
            errors=["Update operation not supported by this connector"],
        )
    
    async def delete_entity(
        self,
        resource_type: str,
        entity_id: str,
    ) -> ConnectorResponse:
        """
        Delete an entity from the data source.
        
        Args:
            resource_type: Type of resource to delete
            entity_id: ID of the entity
            
        Returns:
            ConnectorResponse indicating success/failure.
            
        Note:
            Default implementation returns error. Override in connectors that support CRUD.
        """
        return ConnectorResponse(
            connector_id=self.connector_id,
            connector_name=self.connector_name,
            resource_type=resource_type,
            items=[],
            errors=["Delete operation not supported by this connector"],
        )
    
    def is_authenticated(self) -> bool:
        """Check if connector is authenticated."""
        return self._authenticated
    
    def health_check(self) -> Dict[str, Any]:
        """Return connector health status."""
        return {
            "connector_id": self.connector_id,
            "connector_name": self.connector_name,
            "connector_type": self.connector_type.value,
            "authenticated": self._authenticated,
            "supported_resources": self.supported_resources,
        }
