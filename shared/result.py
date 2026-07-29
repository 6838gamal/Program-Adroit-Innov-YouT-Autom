from typing import TypeVar, Generic, Optional, Callable

T = TypeVar("T")
E = TypeVar("E")


class Result(Generic[T, E]):
    """
    A monad for explicit error handling without exceptions.
    Use Result.ok(value) for success, Result.fail(error) for failure.
    """

    def __init__(self, value: Optional[T], error: Optional[E], is_ok: bool):
        self._value = value
        self._error = error
        self._is_ok = is_ok

    @classmethod
    def ok(cls, value: T) -> "Result[T, E]":
        return cls(value=value, error=None, is_ok=True)

    @classmethod
    def fail(cls, error: E) -> "Result[T, E]":
        return cls(value=None, error=error, is_ok=False)

    @property
    def is_ok(self) -> bool:
        return self._is_ok

    @property
    def is_error(self) -> bool:
        return not self._is_ok

    @property
    def value(self) -> T:
        if not self._is_ok:
            raise ValueError("Cannot access value of a failed Result")
        return self._value  # type: ignore

    @property
    def error(self) -> E:
        if self._is_ok:
            raise ValueError("Cannot access error of a successful Result")
        return self._error  # type: ignore

    def map(self, func: Callable[[T], T]) -> "Result[T, E]":
        if self._is_ok:
            return Result.ok(func(self._value))  # type: ignore
        return self  # type: ignore

    def __repr__(self) -> str:
        if self._is_ok:
            return f"Result.ok({self._value!r})"
        return f"Result.fail({self._error!r})"
