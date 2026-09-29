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
