from __future__ import annotations


class ApiError(Exception):
    """Error rendered as {"error": {"code", "message", "details"}, "request_id"}."""

    def __init__(self, code: str, message: str, status: int = 400, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.details = details or {}


def not_found(entity: str, entity_id: str | None = None) -> ApiError:
    # Same answer for "does not exist" and "belongs to another organisation" (no existence oracle).
    return ApiError("not_found", f"{entity} not found", 404, {"entity": entity, "id": entity_id})


def forbidden(message: str = "Недостаточно прав для этого действия", details: dict | None = None) -> ApiError:
    return ApiError("forbidden", message, 403, details)
