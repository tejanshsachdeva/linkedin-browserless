"""Pass A unit tests for Tier A html_parser (inline HTML snippets)."""

from app.parsing.html_parser import parse_top_card


MINIMAL_PROFILE_HTML = """
<html>
<head>
  <title>Jane Doe | LinkedIn</title>
  <link rel="preload" imagesrcset="
    https://media.licdn.com/dms/image/v2/photo100/100_100/0/abc 100w,
    https://media.licdn.com/dms/image/v2/photo800/800_800/0/abc 800w
  ">
  <meta name="como-t" content='{"serviceVersion":"0.2.6975"}'>
  <script id="cdn-monitor" data-csrf="ajax:3969811343178654321"></script>
</head>
<body>
  <h1>Jane Doe</h1>
  <p>Senior Engineer at Acme Corp</p>
  <p>He/Him</p>
  <p>San Francisco, California, United States</p>
  <p>·</p>
  <p><a href="#">Contact info</a></p>
  <p>500+</p>
  <p>connections</p>
  <p>· 2nd</p>
  <a href="/company/acme-corp/">Acme Corp</a>
  <a href="/school/stanford-university/">Stanford University</a>
  urn:li:member:123456789
  ACoAAFAKE0000000001
  ACoAAFAKE0000000001
</body>
</html>
"""


def test_parse_name_from_h1():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.name == "Jane Doe"


def test_parse_headline():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.headline == "Senior Engineer at Acme Corp"


def test_parse_pronouns():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.pronouns == "He/Him"


def test_parse_location():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.location == "San Francisco, California, United States"


def test_parse_connection_degree():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.connection_degree == "2nd"


def test_parse_connections_count():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.connections_count == "500+"


def test_parse_entity_rows():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.current_company == "Acme Corp"
    assert data.current_school == "Stanford University"


def test_parse_profile_picture_renditions():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.profile_picture is not None
    assert "100" in data.profile_picture.renditions
    assert "800" in data.profile_picture.renditions
    assert "800" in data.profile_picture.renditions
    assert data.profile_picture.primary == data.profile_picture.renditions["800"]


def test_parse_profile_id_most_frequent():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.profile_id == "ACoAAFAKE0000000001"


def test_parse_member_urn():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.member_urn == "urn:li:member:123456789"


def test_parse_client_version():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.client_version == "0.2.6975"


def test_parse_csrf_token():
    data = parse_top_card(MINIMAL_PROFILE_HTML)
    assert data.csrf_token == "ajax:3969811343178654321"


def test_name_fallback_from_title():
    html = "<html><head><title>Fallback Name | LinkedIn</title></head><body></body></html>"
    data = parse_top_card(html)
    assert data.name == "Fallback Name"


def test_parse_connections_count_inline_format():
    html = """
    <html><body>
      <p>Jane Doe</p>
      <p>500+ connections</p>
    </body></html>
    """
    data = parse_top_card(html)
    assert data.connections_count == "500+"


def test_parse_company_from_headline_at_symbol():
    html = """
    <html><head><title>Jane | LinkedIn</title></head><body>
      <p>Engineer @ Acme Corp | Building things</p>
    </body></html>
    """
    data = parse_top_card(html)
    assert data.current_company == "Acme Corp"


def test_profile_picture_skips_background_preload():
    html = """
    <html><head>
      <link rel="preload" imagesrcset="
        https://media.licdn.com/dms/image/profile-displaybackgroundimage-shrink_200_800/bg 800w
      ">
      <link rel="preload" imagesrcset="
        https://media.licdn.com/dms/image/v2/profile-displayphoto-shrink_100_100/0/abc 100w,
        https://media.licdn.com/dms/image/v2/profile-displayphoto-shrink_800_800/0/abc 800w
      ">
    </head><body><h1>Jane Doe</h1></body></html>
    """
    data = parse_top_card(html)
    assert data.profile_picture is not None
    assert "profile-displayphoto" in data.profile_picture.primary
    assert "backgroundimage" not in data.profile_picture.primary


def test_open_to_work_ignored_when_only_in_script():
    html = """
    <html><body>
      <nav><span>Home</span></nav>
      <script>{"preferences":{"openToWork":true}}</script>
    </body></html>
    """
    data = parse_top_card(html)
    assert data.open_to_work is None


def test_open_to_work_extracts_visible_banner():
    html = """
    <html><body>
      <div>
        <strong>Open to work</strong>
        <p>Software Engineer roles · Remote</p>
      </div>
    </body></html>
    """
    data = parse_top_card(html)
    assert data.open_to_work is not None
    assert data.open_to_work.headline == "Open to work"
    assert "Software Engineer" in (data.open_to_work.detail or "")
