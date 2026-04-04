"""Tests for YAMLDiffEngine diff parsing and application."""

import pytest

from mcp_yamlfilesystem.diff_engine import YAMLDiffEngine
from mcp_yamlfilesystem.exceptions import YAMLConfigError, YAMLSyntaxError


class TestDiffParsing:
    """Test diff format parsing."""

    def test_parse_single_diff_block(self):
        """Parse single SEARCH/REPLACE block."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
old_value: 1
=======
new_value: 2
>>>>>>> REPLACE"""

        pairs = engine.parse_diff(diff)
        assert len(pairs) == 1
        assert pairs[0] == ("old_value: 1", "new_value: 2")

    def test_parse_multiple_diff_blocks(self):
        """Parse multiple SEARCH/REPLACE blocks."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
first: old
=======
first: new
>>>>>>> REPLACE

<<<<<<< SEARCH
second: old
=======
second: new
>>>>>>> REPLACE"""

        pairs = engine.parse_diff(diff)
        assert len(pairs) == 2
        assert pairs[0] == ("first: old", "first: new")
        assert pairs[1] == ("second: old", "second: new")

    def test_parse_multiline_blocks(self):
        """Parse diff blocks with multiple lines."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
key1: value1
key2: value2
key3: value3
=======
key1: updated1
key2: updated2
key3: updated3
>>>>>>> REPLACE"""

        pairs = engine.parse_diff(diff)
        assert len(pairs) == 1
        search, replace = pairs[0]
        assert "key1: value1" in search
        assert "key1: updated1" in replace

    def test_reject_invalid_diff_format_no_blocks(self):
        """Reject diff without valid SEARCH/REPLACE blocks."""
        engine = YAMLDiffEngine()

        with pytest.raises(YAMLConfigError, match="No valid diff blocks found"):
            engine.parse_diff("just some random text")

    def test_reject_incomplete_diff_block(self):
        """Reject incomplete diff blocks."""
        engine = YAMLDiffEngine()

        incomplete = """<<<<<<< SEARCH
old value
======="""

        with pytest.raises(YAMLConfigError, match="No valid diff blocks found"):
            engine.parse_diff(incomplete)

    def test_parse_empty_search_block(self):
        """Parse diff with empty search (insertion)."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH

=======
new_line: value
>>>>>>> REPLACE"""

        pairs = engine.parse_diff(diff)
        assert pairs[0][0] == ""
        assert pairs[0][1] == "new_line: value"

    def test_parse_empty_replace_block(self):
        """Parse diff with empty replace (deletion)."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
old_line: value
=======

>>>>>>> REPLACE"""

        pairs = engine.parse_diff(diff)
        assert pairs[0][0] == "old_line: value"
        assert pairs[0][1] == ""


class TestDiffApplication:
    """Test applying diffs to content."""

    def test_apply_single_replacement(self):
        """Apply single search/replace."""
        engine = YAMLDiffEngine()

        content = "name: old_name\nversion: 1\n"
        diff = """<<<<<<< SEARCH
name: old_name
=======
name: new_name
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "name: new_name" in result
        assert "name: old_name" not in result
        assert "version: 1" in result

    def test_apply_multiple_replacements(self):
        """Apply multiple search/replace blocks."""
        engine = YAMLDiffEngine()

        content = "name: old\nversion: 1\nenabled: false\n"
        diff = """<<<<<<< SEARCH
name: old
=======
name: new
>>>>>>> REPLACE

<<<<<<< SEARCH
enabled: false
=======
enabled: true
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "name: new" in result
        assert "enabled: true" in result
        assert "version: 1" in result

    def test_preserve_whitespace_and_indentation(self):
        """Preserve exact whitespace in replacements."""
        engine = YAMLDiffEngine()

        content = """config:
  nested:
    key: value
"""
        diff = """<<<<<<< SEARCH
  nested:
    key: value
=======
  nested:
    key: updated
    new_key: added
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "    key: updated" in result
        assert "    new_key: added" in result

    def test_error_when_search_not_found(self):
        """Raise error when search text not found."""
        engine = YAMLDiffEngine()

        content = "name: value\n"
        diff = """<<<<<<< SEARCH
nonexistent: key
=======
new: value
>>>>>>> REPLACE"""

        with pytest.raises(YAMLConfigError, match="Search text not found"):
            engine.apply_diff(content, diff)

    def test_error_when_search_appears_multiple_times(self):
        """Raise error when search text appears multiple times."""
        engine = YAMLDiffEngine()

        content = "name: value\nname: value\n"
        diff = """<<<<<<< SEARCH
name: value
=======
name: updated
>>>>>>> REPLACE"""

        with pytest.raises(YAMLConfigError, match="appears.*times"):
            engine.apply_diff(content, diff)

    def test_validate_yaml_after_diff(self):
        """Validate YAML syntax after applying diff."""
        engine = YAMLDiffEngine()

        content = "name: value\n"
        diff = """<<<<<<< SEARCH
name: value
=======
invalid: [unclosed bracket
>>>>>>> REPLACE"""

        with pytest.raises(YAMLSyntaxError, match="Invalid YAML after applying diff"):
            engine.apply_diff(content, diff)

    def test_apply_handles_special_characters(self):
        """Handle special characters in search/replace."""
        engine = YAMLDiffEngine()

        content = 'message: "Hello: World"\n'
        diff = """<<<<<<< SEARCH
message: "Hello: World"
=======
message: "Goodbye: Universe"
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert 'message: "Goodbye: Universe"' in result


class TestDiffPreview:
    """Test diff preview generation."""

    def test_generate_preview_single_change(self):
        """Generate preview for single change."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
name: old
=======
name: new
>>>>>>> REPLACE"""

        preview = engine.generate_diff_preview(diff)
        assert "Change 1:" in preview
        assert "Remove:" in preview
        assert "Add:" in preview
        assert "name: old" in preview
        assert "name: new" in preview

    def test_generate_preview_multiple_changes(self):
        """Generate preview for multiple changes."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH
key1: val1
=======
key1: updated1
>>>>>>> REPLACE

<<<<<<< SEARCH
key2: val2
=======
key2: updated2
>>>>>>> REPLACE"""

        preview = engine.generate_diff_preview(diff)
        assert "Change 1:" in preview
        assert "Change 2:" in preview

    def test_preview_truncates_long_content(self):
        """Preview truncates very long diff blocks."""
        engine = YAMLDiffEngine()

        long_search = "\n".join([f"line{i}: value" for i in range(20)])
        long_replace = "\n".join([f"line{i}: updated" for i in range(20)])

        diff = f"""<<<<<<< SEARCH
{long_search}
=======
{long_replace}
>>>>>>> REPLACE"""

        preview = engine.generate_diff_preview(diff)
        assert "..." in preview

    def test_preview_handles_invalid_diff(self):
        """Preview handles invalid diff gracefully."""
        engine = YAMLDiffEngine()

        preview = engine.generate_diff_preview("invalid diff")
        assert "Error" in preview


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_content(self):
        """Handle empty content."""
        engine = YAMLDiffEngine()

        diff = """<<<<<<< SEARCH

=======
new: content
>>>>>>> REPLACE"""

        result = engine.apply_diff("", diff)
        assert "new: content" in result

    def test_unicode_in_diff(self):
        """Handle unicode characters in diff."""
        engine = YAMLDiffEngine()

        content = "name: café\n"
        diff = """<<<<<<< SEARCH
name: café
=======
name: ☕
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "name: ☕" in result

    def test_very_large_diff(self):
        """Handle very large diff blocks."""
        engine = YAMLDiffEngine()

        large_content = "\n".join([f"line{i}: value{i}" for i in range(1000)])
        content = f"start: begin\n{large_content}\nend: finish\n"

        diff = """<<<<<<< SEARCH
start: begin
=======
start: updated
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "start: updated" in result
        assert "end: finish" in result


class TestCustomYAMLTags:
    """Test handling of custom YAML tags like Home Assistant's !include."""

    def test_apply_diff_with_include_tag(self):
        """Apply diff to YAML containing !include tag."""
        engine = YAMLDiffEngine()

        content = """homeassistant:
  name: Home
  unit_system: metric
"""
        diff = """<<<<<<< SEARCH
homeassistant:
  name: Home
  unit_system: metric
=======
homeassistant:
  name: Home
  unit_system: metric
  packages: !include_dir_named packages/
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "!include_dir_named" in result
        assert "packages/" in result

    def test_apply_diff_with_secret_tag(self):
        """Apply diff to YAML containing !secret tag."""
        engine = YAMLDiffEngine()

        content = "api_key: placeholder\n"
        diff = """<<<<<<< SEARCH
api_key: placeholder
=======
api_key: !secret my_api_key
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "!secret my_api_key" in result

    def test_apply_diff_preserves_existing_custom_tags(self):
        """Preserve existing custom tags when applying diff."""
        engine = YAMLDiffEngine()

        content = """automation: !include automations.yaml
sensor: !include_dir_list sensors/
timeout: 30
"""
        diff = """<<<<<<< SEARCH
timeout: 30
=======
timeout: 60
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "!include automations.yaml" in result
        assert "!include_dir_list sensors/" in result
        assert "timeout: 60" in result

    def test_apply_diff_complex_home_assistant_config(self):
        """Apply diff to complex Home Assistant configuration."""
        engine = YAMLDiffEngine()

        content = """homeassistant:
  name: Home
  packages: !include_dir_named packages/
  customize: !include customize.yaml

automation: !include_dir_list automations/
script: !include scripts.yaml

sensor:
  - platform: template
    sensors: !include sensors/templates.yaml
"""
        diff = """<<<<<<< SEARCH
automation: !include_dir_list automations/
=======
automation: !include_dir_merge_list automations/
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "!include_dir_merge_list automations/" in result
        assert "!include_dir_named packages/" in result
        assert "!secret" not in result  # Wasn't in original
        assert "!include customize.yaml" in result

    def test_apply_diff_adding_multiple_custom_tags(self):
        """Add multiple custom tags in a single diff."""
        engine = YAMLDiffEngine()

        content = "config:\n  name: test\n"
        diff = """<<<<<<< SEARCH
config:
  name: test
=======
config:
  name: test
  secrets: !secret config_secrets
  automations: !include automations.yaml
  sensors: !include_dir_list sensors/
>>>>>>> REPLACE"""

        result = engine.apply_diff(content, diff)
        assert "!secret config_secrets" in result
        assert "!include automations.yaml" in result
        assert "!include_dir_list sensors/" in result
