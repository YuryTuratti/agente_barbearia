from app.tools.scheduling_definitions import get_scheduling_tool_definitions
from app.tools.scheduling_write_definitions import get_scheduling_write_tool_definitions


def test_read_mode_has_confirmed_barbershop_info_tool() -> None:
    assert [tool["name"] for tool in get_scheduling_tool_definitions()] == [
        "list_services",
        "get_barbershop_info",
        "list_available_slots",
        "list_my_appointments",
    ]


def test_write_mode_has_exactly_nine_strict_tools_without_identity_fields() -> None:
    tools = get_scheduling_write_tool_definitions()
    names = {tool["name"] for tool in tools}

    assert len(tools) == 9
    assert names == {
        "list_services",
        "get_barbershop_info",
        "list_available_slots",
        "list_my_appointments",
        "prepare_create_appointment",
        "prepare_cancel_appointment",
        "prepare_reschedule_appointment",
        "confirm_pending_action",
        "discard_pending_action",
    }
    assert "create_appointment" not in names
    assert "cancel_appointment" not in names
    assert "reschedule_appointment" not in names
    for tool in tools:
        schema_text = str(tool["parameters"])
        assert tool["strict"] is True
        assert tool["parameters"]["additionalProperties"] is False
        assert "phone" not in schema_text
        assert "instance" not in schema_text
        assert "resource_key" not in schema_text


def test_confirm_and_discard_accept_no_arguments() -> None:
    tools = {tool["name"]: tool for tool in get_scheduling_write_tool_definitions()}

    assert tools["confirm_pending_action"]["parameters"]["properties"] == {}
    assert tools["discard_pending_action"]["parameters"]["properties"] == {}
