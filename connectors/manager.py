"""
Connector registry and management.

Handles connector discovery, configuration, lifecycle, and multi-source orchestration.
"""

import json
from typing import Any, Dict, List, Optional
from pathlib import Path
import asyncio
import logging

from .base import DataConnector, ConnectorConfig, ConnectorType, ConnectorResponse


logger = logging.getLogger(__name__)


class ConnectorManager:
    """
    Manages connector lifecycle, configuration, and discovery.
    
    Supports registering, loading, initializing, and querying multiple connectors.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize connector manager.
        
        Args:
            config_path: Path to connectors.json config file.
        """
        self._connectors: Dict[str, DataConnector] = {}
        self._configs: Dict[str, ConnectorConfig] = {}
        self.config_path = config_path
        self._initialized = False
    
    def register_connector(self, connector: DataConnector) -> None:
        """Register a connector instance."""
        connector_id = connector.connector_id
        self._connectors[connector_id] = connector
        logger.info(f"Registered connector: {connector_id} ({connector.connector_name})")
    
    def unregister_connector(self, connector_id: str) -> bool:
        """Unregister a connector by ID."""
        if connector_id in self._connectors:
            del self._connectors[connector_id]
            logger.info(f"Unregistered connector: {connector_id}")
            return True
        return False
    
    def get_connector(self, connector_id: str) -> Optional[DataConnector]:
        """Retrieve a connector by ID."""
        return self._connectors.get(connector_id)
    
    def list_connectors(self, include_disabled: bool = False) -> List[Dict[str, Any]]:
        """List all available connectors with their status."""
        connectors = []
        for cid, connector in self._connectors.items():
            config = self._configs.get(cid)
            if config and not config.enabled and not include_disabled:
                continue
            
            connectors.append({
                "connector_id": connector.connector_id,
                "connector_name": connector.connector_name,
                "connector_type": connector.connector_type.value,
                "enabled": config.enabled if config else True,
                "supported_resources": connector.supported_resources,
                "authenticated": connector.is_authenticated(),
                "auth_type": config.auth_config.auth_type.value if config and config.auth_config else "api_key",
            })
        return connectors
    
    async def authenticate_connector(
        self,
        connector_id: str,
        credentials: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Authenticate a connector.
        
        Args:
            connector_id: ID of connector to authenticate
            credentials: Optional override credentials
            
        Returns:
            True if authentication successful.
        """
        connector = self.get_connector(connector_id)
        if not connector:
            logger.error(f"Connector not found: {connector_id}")
            return False
        
        try:
            result = await connector.authenticate(credentials)
            if result:
                logger.info(f"Authenticated connector: {connector_id}")
            else:
                logger.error(f"Failed to authenticate connector: {connector_id}")
            return result
        except Exception as e:
            logger.error(f"Error authenticating connector {connector_id}: {e}")
            return False
    
    async def authenticate_all(self) -> Dict[str, bool]:
        """Authenticate all enabled connectors."""
        results = {}
        for cid, connector in self._connectors.items():
            config = self._configs.get(cid)
            if config and not config.enabled:
                continue
            results[cid] = await self.authenticate_connector(cid)
        return results
    
    async def fetch_resource(
        self,
        connector_id: str,
        resource_type: str,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ConnectorResponse:
        """
        Fetch a resource from a single connector.
        
        Args:
            connector_id: ID of source connector
            resource_type: Type of resource to fetch
            filters: Optional filter criteria
            **kwargs: Additional parameters (skip, top, etc.)
            
        Returns:
            ConnectorResponse with results.
        """
        connector = self.get_connector(connector_id)
        if not connector:
            return ConnectorResponse(
                connector_id=connector_id,
                connector_name="Unknown",
                resource_type=resource_type,
                items=[],
                errors=[f"Connector not found: {connector_id}"],
            )
        
        if not connector.is_authenticated():
            return ConnectorResponse(
                connector_id=connector_id,
                connector_name=connector.connector_name,
                resource_type=resource_type,
                items=[],
                errors=[f"Connector not authenticated: {connector_id}"],
            )
        
        try:
            return await connector.fetch_resource(resource_type, filters, **kwargs)
        except Exception as e:
            logger.error(f"Error fetching {resource_type} from {connector_id}: {e}")
            return ConnectorResponse(
                connector_id=connector_id,
                connector_name=connector.connector_name,
                resource_type=resource_type,
                items=[],
                errors=[str(e)],
            )
    
    async def fetch_resource_from_all(
        self,
        resource_type: str,
        connector_ids: Optional[List[str]] = None,
        filters: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> List[ConnectorResponse]:
        """
        Fetch a resource from multiple connectors in parallel.
        
        Args:
            resource_type: Type of resource to fetch
            connector_ids: Optional list of specific connectors. If None, use all enabled.
            filters: Optional filter criteria
            **kwargs: Additional parameters
            
        Returns:
            List of ConnectorResponse objects, one per connector.
        """
        if connector_ids is None:
            connector_ids = [
                cid for cid, connector in self._connectors.items()
                if self._configs.get(cid, ConnectorConfig("", ConnectorType.MSGRAPH)).enabled
            ]
        
        # Fetch from all connectors in parallel
        tasks = [
            self.fetch_resource(cid, resource_type, filters, **kwargs)
            for cid in connector_ids
        ]
        
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    async def search(
        self,
        query: str,
        resource_types: Optional[List[str]] = None,
        connector_ids: Optional[List[str]] = None,
        **kwargs,
    ) -> List[ConnectorResponse]:
        """
        Search across one or more connectors.
        
        Args:
            query: Search query string
            resource_types: Optional resource types to search
            connector_ids: Optional specific connectors. If None, use all enabled.
            **kwargs: Additional parameters (skip, top, etc.)
            
        Returns:
            List of ConnectorResponse objects with search results.
        """
        if connector_ids is None:
            connector_ids = [
                cid for cid, connector in self._connectors.items()
                if self._configs.get(cid, ConnectorConfig("", ConnectorType.MSGRAPH)).enabled
            ]
        
        # Search all connectors in parallel
        tasks = []
        for cid in connector_ids:
            connector = self.get_connector(cid)
            if connector and connector.is_authenticated():
                tasks.append(connector.search(query, resource_types, **kwargs))
        
        return await asyncio.gather(*tasks, return_exceptions=False)
    
    def load_config(self, config_path: Path) -> Dict[str, Any]:
        """
        Load connector configuration from JSON file.
        
        Args:
            config_path: Path to connectors.json
            
        Returns:
            Loaded configuration dictionary.
        """
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded connector config from {config_path}")
            return config
        except Exception as e:
            logger.error(f"Error loading connector config: {e}")
            return {"connectors": []}
    
    def save_config(self, config_path: Path, config: Dict[str, Any]) -> bool:
        """
        Save connector configuration to JSON file.
        
        Args:
            config_path: Path to save connectors.json
            config: Configuration dictionary
            
        Returns:
            True if successful.
        """
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(config_path, 'w') as f:
                json.dump(config, f, indent=2)
            logger.info(f"Saved connector config to {config_path}")
            return True
        except Exception as e:
            logger.error(f"Error saving connector config: {e}")
            return False
    
    def health_check(self) -> Dict[str, Any]:
        """Get health status of all connectors."""
        return {
            "initialized": self._initialized,
            "connector_count": len(self._connectors),
            "connectors": [
                self.get_connector(cid).health_check()
                for cid in self._connectors.keys()
            ],
        }


# Global connector manager instance
_connector_manager: Optional[ConnectorManager] = None


def get_connector_manager() -> ConnectorManager:
    """Get or create the global connector manager."""
    global _connector_manager
    if _connector_manager is None:
        _connector_manager = ConnectorManager()
    return _connector_manager


def set_connector_manager(manager: ConnectorManager) -> None:
    """Set the global connector manager."""
    global _connector_manager
    _connector_manager = manager
