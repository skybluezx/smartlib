from typing import Protocol

from .models import AdapterSearchResult, SearchAccessContext, SearchCommand


class SearchPort(Protocol):
    def search(self, command: SearchCommand, access: SearchAccessContext) -> AdapterSearchResult: ...
