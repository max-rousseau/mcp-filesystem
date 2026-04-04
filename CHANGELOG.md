# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-07

### Added

- MCP server with five core tools: read_file, create_file, update_file, grep_files, list_directory_structure
- Filesystem abstraction layer (FileSystemBackend) with local and SMB backends
- SMB compound requests for 3x directory scan performance
- SEARCH/REPLACE diff engine for surgical file edits
- Path traversal protection, extension whitelisting, and null byte injection prevention
- YAML syntax validation with custom tag support (Home Assistant compatible)
- Google OAuth token verification with email allowlist for HTTP transport
- HTTP streaming transport with configurable host, port, and endpoint path
- Config file permission enforcement (chmod 600)
- `--test` CLI flag for connection verification
- Docker deployment with non-root container user
- Comprehensive test suite (unit, integration, stdio transport)
