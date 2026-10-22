from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCENARIOS = [
    {"id": "unreachable", "label": "Unreachable booking button", "description": "A mouse can activate the booking control, but keyboard focus skips it."},
    {"id": "working", "label": "Repaired booking form", "description": "The same task with a keyboard-operable booking control."},
    {"id": "trap", "label": "Modal focus trap", "description": "A notice captures focus and its close control cannot be reached by keyboard."},
    {"id": "variant", "label": "Different form layout", "description": "A working form with a different field order to test adaptability."},
]


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Literal["working", "unreachable", "trap", "variant"] = "unreachable"
    goal: str = Field(min_length=10, max_length=1600)
    expected_text: str = Field(default="Alex Rivera · alex@example.com · Calculus", min_length=3, max_length=500)
    mode: Literal["live", "offline"] = "live"
    parent_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")

    @field_validator("goal", "expected_text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Enter nonempty text.")
        return value
