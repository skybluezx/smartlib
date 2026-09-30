class SearchError(Exception):
    """Base error for stable search capability failures."""


class InvalidSearchCursor(SearchError):
    pass


class SearchModeUnavailable(SearchError):
    pass


class SearchBackendUnavailable(SearchError):
    pass


class SearchAuthorizationInvariantError(SearchError):
    pass
