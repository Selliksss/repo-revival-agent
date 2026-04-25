from typing import Literal

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    verdict: Literal["revive", "fork", "let_rest", "uncertain"]
    confidence: float
    reasoning: str
    search_calls: list[dict] = []
