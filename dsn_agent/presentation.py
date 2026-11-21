import json

from a2ui.core import Catalog
from a2ui.utils import validate_payload

from .config import ROOT
from .results import Result


class Presenter:
    def __init__(self):
        self.catalog = Catalog.from_json(
            json.loads((ROOT / "config" / "catalog.json").read_text(encoding="utf-8"))
        )

    def render(self, result: Result, preferred: str, point_limit: int) -> dict:
        card = result.presentation(preferred, point_limit)
        messages = [
            {
                "version": "1.0",
                "createSurface": {
                    "surfaceId": f"result-{result.id}",
                    "catalogId": self.catalog.catalog_id,
                    "components": [
                        {
                            "id": "root",
                            "component": "DSNResult",
                            "resultId": {"@path": "/resultId"},
                        }
                    ],
                    "dataModel": {"resultId": result.id},
                },
            }
        ]
        # Use the Python agent SDK's renderer-equivalent validation, not just JSON parsing.
        validate_payload([self.catalog], messages)
        return {"card": card, "messages": messages}
