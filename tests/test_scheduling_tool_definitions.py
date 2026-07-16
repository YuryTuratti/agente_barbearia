from app.tools.scheduling_definitions import get_scheduling_tool_definitions


def test_scheduling_tool_definitions_are_strict_read_only_tools() -> None:
    tools = get_scheduling_tool_definitions()
    names = {tool["name"] for tool in tools}

    assert len(tools) == 4
    assert names == {
        "list_services",
        "get_barbershop_info",
        "list_available_slots",
        "list_my_appointments",
    }
    assert "create_appointment" not in names
    assert "cancel_appointment" not in names
    assert "reschedule_appointment" not in names

    for tool in tools:
        parameters = tool["parameters"]
        assert tool["type"] == "function"
        assert tool["strict"] is True
        assert parameters["additionalProperties"] is False
        schema_text = str(parameters)
        assert "phone" not in schema_text
        assert "instance" not in schema_text
        assert "resource_key" not in schema_text
