"""Unit tests for connection degree parsing from HTML metadata."""

from app.parsing.connection_degree import parse_connection_degree_from_html


def test_parse_network_distance_second_degree():
    html = 'some blob with networkDistance\\":2 and more data'
    assert parse_connection_degree_from_html(html) == "2nd"


def test_parse_distance_enum():
    html = '{"distance":"DISTANCE_3"}'
    assert parse_connection_degree_from_html(html) == "3rd"


def test_ignores_invalid_network_distance():
    html = 'networkDistance\\":-1'
    assert parse_connection_degree_from_html(html) is None
