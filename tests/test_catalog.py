from pathlib import Path

import pytest

from interface_ai.catalog import CapabilityCatalog, CatalogError


def test_catalog_exposes_typed_agent_tool_contract() -> None:
    catalog = CapabilityCatalog(Path("evidence/artifacts"))
    tools = catalog.list_tools()

    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == "lookup_patient_recent_claims"
    assert tool["approved"] is True
    assert tool["input_schema"]["required"] == ["member_id"]
    assert tool["input_schema"]["additionalProperties"] is False
    assert {item["name"] for item in tool["outputs"]} >= {
        "patient_status",
        "latest_claim",
    }


def test_catalog_rejects_unknown_capability() -> None:
    with pytest.raises(CatalogError, match="unknown capability"):
        CapabilityCatalog(Path("evidence/artifacts")).get("does_not_exist")
