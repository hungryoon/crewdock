class CrewError(Exception):
    """Base class for all crew domain errors."""


class InvalidNameError(CrewError):
    """Instance name violates the naming rules."""


class InstanceExistsError(CrewError):
    """An instance with this name already exists."""


class InstanceNotFoundError(CrewError):
    """No instance with this name."""


class ManifestError(CrewError):
    """Agent-type manifest is missing or invalid."""


class NoFreePortError(CrewError):
    """No free port available in the configured range."""


class LayerNotFoundError(CrewError):
    """A requested data layer does not exist in the layer pool."""


class ExposeError(CrewError):
    """Exposing an instance's dashboard (Tailscale / oauth2-proxy) failed."""


class CredentialNotFoundError(CrewError):
    """A requested --credential bundle is not in the credentials/ pool."""


class NotInitializedError(CrewError):
    pass
