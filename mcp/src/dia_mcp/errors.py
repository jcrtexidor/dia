"""Stable machine-readable errors shared by the API and MCP adapter."""


class DiaError(Exception):
    def __init__(self, code: str, message: str, *, outcome=None, details=None):
        super().__init__(message)
        self.code, self.outcome, self.details = code, outcome, details

    def record(self):
        result = {"code": self.code, "message": str(self)}
        if self.outcome is not None:
            result["outcome"] = self.outcome
        if self.details is not None:
            result["details"] = self.details
        return result

    def as_dict(self) -> dict:
        return {"api_version": "1", **self.record()}
