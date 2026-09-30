class GraphBackendUnavailable(RuntimeError):
    """The configured graph projection cannot serve the request."""


class GraphAuthorizationInvariantError(RuntimeError):
    """An adapter returned graph material outside the trusted access scope."""
