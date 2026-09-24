from scorenow_api_observer.json_structure import extract_json_structure


def test_extract_json_structure_collects_nested_paths_and_types() -> None:
    data = {
        "id": "A",
        "score": None,
        "participants": [
            {"name": "home", "value": 1, "active": True},
            {"name": "away", "value": 2.5, "active": False},
        ],
    }

    result = extract_json_structure(data)

    assert result == {
        "$": {"object"},
        "$.id": {"string"},
        "$.score": {"null"},
        "$.participants": {"array"},
        "$.participants[]": {"object"},
        "$.participants[].name": {"string"},
        "$.participants[].value": {"integer", "number"},
        "$.participants[].active": {"boolean"},
    }


def test_extract_json_structure_merges_types_at_the_same_array_path() -> None:
    data = {"values": [None, True, 1, 1.5, "one"]}

    result = extract_json_structure(data)

    assert result == {
        "$": {"object"},
        "$.values": {"array"},
        "$.values[]": {"null", "boolean", "integer", "number", "string"},
    }


def test_extract_json_structure_does_not_create_element_path_for_empty_array() -> None:
    data = {"values": []}

    result = extract_json_structure(data)

    assert result == {
        "$": {"object"},
        "$.values": {"array"},
    }
