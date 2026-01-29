"""
Dependency Injection Container for mi_patrimonio.

Provides centralized service management with lazy initialization
and support for both singleton and factory patterns.

Example:
    # Get services
    data_provider = container.data_provider
    risk_analyzer = container.risk_analyzer

    # Override for testing
    container.set_data_provider(mock_provider)
"""
import logging
from typing import Optional, TypeVar, Generic, Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Lazy(Generic[T]):
    """
    Lazy initialization wrapper.

    Creates the instance only when first accessed.
    """

    def __init__(self, factory: Callable[[], T]):
        self._factory = factory
        self._instance: Optional[T] = None

    @property
    def instance(self) -> T:
        if self._instance is None:
            self._instance = self._factory()
        return self._instance

    def reset(self) -> None:
        """Reset to allow re-initialization."""
        self._instance = None

    def set(self, instance: T) -> None:
        """Set instance directly (useful for testing)."""
        self._instance = instance


class ServiceContainer:
    """
    Service container for mi_patrimonio.

    Manages service lifecycle and dependencies with support for:
    - Lazy initialization
    - Singleton pattern
    - Service overrides for testing
    """

    def __init__(self):
        self._data_provider: Optional[Lazy] = None
        self._risk_analyzer: Optional[Lazy] = None
        self._ai_advisor: Optional[Lazy] = None
        self._finrobot_advisor: Optional[Lazy] = None
        self._initialize_defaults()

    def _initialize_defaults(self) -> None:
        """Set up default service factories."""
        self._data_provider = Lazy(self._create_data_provider)
        self._risk_analyzer = Lazy(self._create_risk_analyzer)
        self._ai_advisor = Lazy(self._create_ai_advisor)
        self._finrobot_advisor = Lazy(self._create_finrobot_advisor)

    def _create_data_provider(self):
        """Factory for DataProvider."""
        from data_provider import DataProvider
        logger.info("Creating DataProvider instance")
        return DataProvider()

    def _create_risk_analyzer(self):
        """Factory for RiskAnalyzer."""
        from risk_analyzer import RiskAnalyzer
        logger.info("Creating RiskAnalyzer instance")
        return RiskAnalyzer(data_provider=self.data_provider)

    def _create_ai_advisor(self):
        """Factory for AIAdvisor."""
        from ai_advisor import AIAdvisor
        logger.info("Creating AIAdvisor instance")
        return AIAdvisor()

    def _create_finrobot_advisor(self):
        """Factory for FinRobotAdvisor."""
        from finrobot_agents import FinRobotAdvisor
        logger.info("Creating FinRobotAdvisor instance")
        return FinRobotAdvisor()

    # Service accessors

    @property
    def data_provider(self):
        """Get the data provider service."""
        return self._data_provider.instance

    @property
    def risk_analyzer(self):
        """Get the risk analyzer service."""
        return self._risk_analyzer.instance

    @property
    def ai_advisor(self):
        """Get the AI advisor service."""
        return self._ai_advisor.instance

    @property
    def finrobot_advisor(self):
        """Get the FinRobot advisor service."""
        return self._finrobot_advisor.instance

    # Service setters (for testing/overrides)

    def set_data_provider(self, provider) -> None:
        """Override data provider (useful for testing)."""
        self._data_provider.set(provider)
        logger.info("DataProvider overridden")

    def set_risk_analyzer(self, analyzer) -> None:
        """Override risk analyzer (useful for testing)."""
        self._risk_analyzer.set(analyzer)
        logger.info("RiskAnalyzer overridden")

    def set_ai_advisor(self, advisor) -> None:
        """Override AI advisor (useful for testing)."""
        self._ai_advisor.set(advisor)
        logger.info("AIAdvisor overridden")

    def set_finrobot_advisor(self, advisor) -> None:
        """Override FinRobot advisor (useful for testing)."""
        self._finrobot_advisor.set(advisor)
        logger.info("FinRobotAdvisor overridden")

    # Lifecycle management

    def reset(self) -> None:
        """Reset all services to re-initialize on next access."""
        self._data_provider.reset()
        self._risk_analyzer.reset()
        self._ai_advisor.reset()
        self._finrobot_advisor.reset()
        logger.info("All services reset")

    def reset_service(self, service_name: str) -> None:
        """Reset a specific service."""
        service_map = {
            "data_provider": self._data_provider,
            "risk_analyzer": self._risk_analyzer,
            "ai_advisor": self._ai_advisor,
            "finrobot_advisor": self._finrobot_advisor,
        }
        if service_name in service_map:
            service_map[service_name].reset()
            logger.info("Service %s reset", service_name)
        else:
            raise ValueError(f"Unknown service: {service_name}")


# Global container instance
_container: Optional[ServiceContainer] = None


def get_container() -> ServiceContainer:
    """
    Get the global service container.

    Creates container on first access.

    Returns:
        ServiceContainer instance
    """
    global _container
    if _container is None:
        _container = ServiceContainer()
    return _container


def reset_container() -> None:
    """Reset the global container."""
    global _container
    if _container is not None:
        _container.reset()
    _container = None
    logger.info("Global container reset")


# Convenience accessors for backward compatibility

def get_data_provider():
    """Get data provider from container."""
    return get_container().data_provider


def get_risk_analyzer():
    """Get risk analyzer from container."""
    return get_container().risk_analyzer


def get_ai_advisor():
    """Get AI advisor from container."""
    return get_container().ai_advisor


def get_finrobot_advisor():
    """Get FinRobot advisor from container."""
    return get_container().finrobot_advisor
