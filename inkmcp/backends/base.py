"""Abstract base class for Inkscape communication backends."""
from abc import ABC, abstractmethod
from typing import Any, Dict


class InkscapeBackend(ABC):
    """Abstract interface for Inkscape command execution."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if this backend is capable of handling operations."""
        pass

    @abstractmethod
    def execute_operation(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute an operation dictionary and return the structured response."""
        pass

    @abstractmethod
    def get_backend_name(self) -> str:
        """Return human-readable identifier for this backend."""
        pass

    async def is_available_async(self) -> bool:
        """Async-compatible wrapper for is_available to prevent event loop starvation."""
        import asyncio
        return await asyncio.to_thread(self.is_available)

    async def execute_operation_async(self, operation_data: Dict[str, Any]) -> Dict[str, Any]:
        """Async-compatible wrapper for execute_operation to prevent event loop starvation."""
        import asyncio
        return await asyncio.to_thread(self.execute_operation, operation_data)
