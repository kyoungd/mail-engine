"""Verb validation errors. A precondition failure carries a machine-readable code
plus a message the UI can render and Claude Code can read (service contract §4).
Verbs fail loudly and completely — no partial writes."""


class ValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
