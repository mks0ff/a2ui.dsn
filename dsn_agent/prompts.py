import json
from pathlib import Path
from string import Formatter
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Visualization = Literal["auto", "line", "bar", "table", "kpi"]


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    default: str


class SuggestedPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    label: str
    template: str
    parameters: list[Parameter]
    category: str
    visualization: Visualization = "auto"
    order: int
    enabled: bool = True

    @model_validator(mode="after")
    def check_parameters(self):
        names = [p.id for p in self.parameters]
        fields = []
        for _, name, spec, conversion in Formatter().parse(self.template):
            if name is not None:
                if spec or conversion:
                    raise ValueError("Prompt placeholders cannot use format specifications.")
                fields.append(name)
        if len(names) != len(set(names)) or set(names) != set(fields):
            raise ValueError("Prompt placeholders must match unique parameter IDs.")
        return self


def load_prompts(path: Path) -> list[SuggestedPrompt]:
    entries = [
        SuggestedPrompt.model_validate(item)
        for item in json.loads(path.read_text(encoding="utf-8"))
    ]
    if len({item.id for item in entries}) != len(entries):
        raise ValueError("Suggested prompt IDs must be unique.")
    return sorted((entry for entry in entries if entry.enabled), key=lambda entry: entry.order)
