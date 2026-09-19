"""Stable machine-readable errors shared by the API and MCP adapter."""


class DiaError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def as_dict(self) -> dict:
        return {"api_version": "1", "code": self.code, "message": str(self)}
