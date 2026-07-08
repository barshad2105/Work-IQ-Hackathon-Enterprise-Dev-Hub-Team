"""
Work IQ Data Connectors - Extensible data source integration.

Provides a pluggable connector architecture for integrating data from:
- Microsoft Graph (primary)
- Google Cloud Platform (Workspace, Drive, Storage)
- Amazon Web Services (S3, DynamoDB, CloudWatch)
- Social Media (LinkedIn, Twitter, Facebook)
- Custom REST APIs

Usage:
    from connectors import get_connector_manager
    from connectors.msgraph import MSGraphConnector
    from connectors.custom_api import CustomAPIConnector
    
    manager = get_connector_manager()
    
    # Register MS Graph connector
    msgraph_config = ConnectorConfig(
        connector_id="msgraph_primary",
        connector_type=ConnectorType.MSGRAPH,
        auth_config={"tenant_id": "...", "client_id": "..."}
    )
    msgraph = MSGraphConnector(msgraph_config)
    manager.register_connector(msgraph)
    
    # Authenticate
    await manager.authenticate_connector("msgraph_primary")
    
    # Fetch data
    response = await manager.fetch_resource(
        "msgraph_primary",
        "emails",
        filters={"is_read": False}
    )
    
    # Query multiple sources in parallel
    responses = await manager.fetch_resource_from_all(
        "files",
        connector_ids=["msgraph_primary", "gcp_drive"],
    )
"""

from .base import (
    DataConnector,
    ConnectorConfig,
    ConnectorResponse,
    ConnectorType,
    AuthType,
)
from .manager import (
    ConnectorManager,
    get_connector_manager,
    set_connector_manager,
)
from .msgraph import MSGraphConnector
from .custom_api import CustomAPIConnector
from .gcp import GCPConnector
from .aws import AWSConnector
from .social_media import SocialMediaConnector


__all__ = [
    # Base classes
    "DataConnector",
    "ConnectorConfig",
    "ConnectorResponse",
    "ConnectorType",
    "AuthType",
    # Manager
    "ConnectorManager",
    "get_connector_manager",
    "set_connector_manager",
    # Connectors
    "MSGraphConnector",
    "CustomAPIConnector",
    "GCPConnector",
    "AWSConnector",
    "SocialMediaConnector",
]

__version__ = "1.0.0"
__author__ = "Work IQ Team"
