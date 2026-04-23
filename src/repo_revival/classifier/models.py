from typing import Literal

from pydantic import BaseModel


class ClassificationResult(BaseModel):
    verdict: Literal["revive", "fork", "let_rest"]
    confidence: float
    reasoning: str