"""
Module: diff_engine

Purpose:
    Diff-based YAML update engine providing precise, surgical modifications to
    YAML files using exact search/replace blocks. Enables safe, predictable
    updates by requiring exact content matching before replacement.

Classes:
    - YAMLDiffEngine: Engine for parsing and applying diff-based updates

Methods (on YAMLDiffEngine):
    - parse_diff: Parse diff content into search/replace pairs
    - apply_diff: Apply diff blocks to content with validation
    - generate_diff_preview: Preview changes without applying

Diff Format:
    Uses three-marker format for exact search/replace:

    <<<<<<< SEARCH
    exact content to find (whitespace-sensitive)
    =======
    replacement content
    >>>>>>> REPLACE

    Multiple diff blocks can be included in single update.

Usage Example:
    from mcp_yamlfilesystem.diff_engine import YAMLDiffEngine

    engine = YAMLDiffEngine()

    diff = '''
    <<<<<<< SEARCH
    timeout: 30
    =======
    timeout: 60
    >>>>>>> REPLACE
    '''

    original = "timeout: 30\\nretries: 3\\n"
    updated = engine.apply_diff(original, diff)
    print(updated)  # "timeout: 60\\nretries: 3\\n"

Design Principles:
    - Exact matching only (no fuzzy matching)
    - Whitespace-sensitive (indentation matters)
    - Single replacement per search block
    - YAML validation after all changes
    - Clear error messages for mismatches

Happy Path Flow:

```mermaid
sequenceDiagram
    participant Client
    participant YAMLDiffEngine
    participant Parser
    participant Validator

    Client->>YAMLDiffEngine: apply_diff(content, diff)
    YAMLDiffEngine->>Parser: parse_diff(diff)
    Parser->>Parser: regex findall SEARCH/REPLACE
    Parser-->>YAMLDiffEngine: [(search, replace), ...]

    loop For each diff block
        YAMLDiffEngine->>YAMLDiffEngine: count occurrences
        alt Found exactly once
            YAMLDiffEngine->>YAMLDiffEngine: replace text
        else Not found
            YAMLDiffEngine-->>Client: error: not found
        else Multiple matches
            YAMLDiffEngine-->>Client: error: ambiguous
        end
    end

    YAMLDiffEngine->>Validator: validate_yaml(result)
    Validator->>Validator: safe_load_yaml() with custom tag support
    Validator-->>YAMLDiffEngine: valid
    YAMLDiffEngine-->>Client: updated content
```
"""

import re
import yaml
import logging
from typing import List, Tuple

from .exceptions import YAMLConfigError, YAMLSyntaxError
from .yaml_manager import safe_load_yaml

logger = logging.getLogger(__name__)


class YAMLDiffEngine:
    """Precise diff-based YAML update engine.

    Uses strict three-marker format for surgical file modifications:
        <<<<<<< SEARCH
        exact content to find
        =======
        replacement content
        >>>>>>> REPLACE

    Features:
    - Exact matching (whitespace-sensitive)
    - Multiple diff blocks per update
    - YAML validation after changes
    - Single replacement per search block

    Attributes:
        DIFF_PATTERN: Compiled regex for parsing diff blocks

    Example:
        >>> engine = YAMLDiffEngine()
        >>> diff = '''<<<<<<< SEARCH
        ... old: value
        ... =======
        ... new: value
        ... >>>>>>> REPLACE'''
        >>> result = engine.apply_diff("old: value\\n", diff)
        >>> print(result)
        new: value
    """

    DIFF_PATTERN = re.compile(
        r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE", re.DOTALL
    )

    def parse_diff(self, diff_content: str) -> List[Tuple[str, str]]:
        """Parse diff content into search/replace pairs.

        Extracts all SEARCH/REPLACE blocks from diff content using regex.
        Each block must have exactly three markers in correct order.

        Args:
            diff_content: Diff text with SEARCH/REPLACE blocks.

        Returns:
            List of (search_text, replace_text) tuples.

        Raises:
            YAMLConfigError: If no valid diff blocks found or format invalid.

        Example:
            >>> engine = YAMLDiffEngine()
            >>> diff = '''<<<<<<< SEARCH
            ... key1: value1
            ... =======
            ... key1: updated
            ... >>>>>>> REPLACE
            ...
            ... <<<<<<< SEARCH
            ... key2: value2
            ... =======
            ... key2: changed
            ... >>>>>>> REPLACE'''
            >>> pairs = engine.parse_diff(diff)
            >>> len(pairs)
            2
            >>> pairs[0]
            ('key1: value1', 'key1: updated')
        """
        matches = self.DIFF_PATTERN.findall(diff_content)

        if not matches:
            raise YAMLConfigError(
                "No valid diff blocks found. Expected format:\n"
                "<<<<<<< SEARCH\n"
                "content to find\n"
                "=======\n"
                "replacement content\n"
                ">>>>>>> REPLACE"
            )

        logger.debug(f"Parsed {len(matches)} diff block(s)")
        return matches

    def apply_diff(self, content: str, diff_content: str) -> str:
        """Apply diff to file content.

        Processes all diff blocks sequentially, replacing matched text with
        new content. Each search text must match exactly once in current content.

        Args:
            content: Original file content.
            diff_content: Diff with SEARCH/REPLACE blocks.

        Returns:
            Modified content with all replacements applied.

        Raises:
            YAMLConfigError: If search text not found or appears multiple times.
            YAMLSyntaxError: If result is invalid YAML.

        Example:
            >>> engine = YAMLDiffEngine()
            >>> original = "database:\\n  host: localhost\\n  port: 5432\\n"
            >>> diff = '''<<<<<<< SEARCH
            ... database:
            ...   host: localhost
            ... =======
            ... database:
            ...   host: prod-db
            ... >>>>>>> REPLACE'''
            >>> result = engine.apply_diff(original, diff)
            >>> "prod-db" in result
            True

            >>> bad_diff = '''<<<<<<< SEARCH
            ... nonexistent: value
            ... =======
            ... new: value
            ... >>>>>>> REPLACE'''
            >>> engine.apply_diff(original, bad_diff)
            Traceback (most recent call last):
            ...
            YAMLConfigError: Search text not found in file...
        """
        diffs = self.parse_diff(diff_content)
        result = content

        for search_text, replace_text in diffs:
            count = result.count(search_text)

            if count == 0:
                preview = search_text[:200] if len(search_text) > 200 else search_text
                raise YAMLConfigError(
                    f"Search text not found in file:\n{preview}\n\n"
                    "Make sure the search text matches exactly, including whitespace and indentation."
                )

            if count > 1:
                preview = search_text[:200] if len(search_text) > 200 else search_text
                raise YAMLConfigError(
                    f"Search text appears {count} times (must be unique):\n{preview}\n\n"
                    "Make the search text more specific to match exactly once."
                )

            result = result.replace(search_text, replace_text, 1)
            logger.debug(
                f"Applied diff: replaced {len(search_text)} chars with {len(replace_text)} chars"
            )

        try:
            safe_load_yaml(result)
        except yaml.YAMLError as e:
            raise YAMLSyntaxError(f"Invalid YAML after applying diff: {e}")

        return result

    def generate_diff_preview(self, diff_content: str) -> str:
        """Generate preview of changes without applying them.

        Creates human-readable preview showing what will be removed and added
        for each diff block. Useful for validation before applying changes.

        Args:
            diff_content: Diff with SEARCH/REPLACE blocks.

        Returns:
            Human-readable preview of changes, showing first 5 lines of each
            search/replace with line counts for longer blocks. On parse errors,
            returns an error description string instead of raising.

        Example:
            >>> engine = YAMLDiffEngine()
            >>> diff = '''<<<<<<< SEARCH
            ... old_key: old_value
            ... nested:
            ...   item: 1
            ... =======
            ... new_key: new_value
            ... nested:
            ...   item: 2
            ... >>>>>>> REPLACE'''
            >>> preview = engine.generate_diff_preview(diff)
            >>> "Change 1:" in preview
            True
            >>> "Remove:" in preview
            True
            >>> "Add:" in preview
            True
        """
        try:
            diffs = self.parse_diff(diff_content)
            preview = []

            for i, (search, replace) in enumerate(diffs, 1):
                preview.append(f"Change {i}:")
                preview.append("  Remove:")
                for line in search.split("\n")[:5]:
                    preview.append(f"    - {line}")
                newline_count = search.count("\n")
                if newline_count > 5:
                    preview.append(f"    ... ({newline_count - 5} more lines)")

                preview.append("  Add:")
                for line in replace.split("\n")[:5]:
                    preview.append(f"    + {line}")
                newline_count = replace.count("\n")
                if newline_count > 5:
                    preview.append(f"    ... ({newline_count - 5} more lines)")
                preview.append("")

            return "\n".join(preview)
        except Exception as e:
            return f"Error generating preview: {e}"
