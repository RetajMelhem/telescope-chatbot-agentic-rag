"""Safe public errors with no upstream exception or input details."""

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    request_id: str
    error: ErrorDetail


class ApplicationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.safe_message = message


def error_payload(request_id: str, code: str, message: str) -> dict:
    return ErrorResponse(
        request_id=request_id, error=ErrorDetail(code=code, message=message)
    ).model_dump()
