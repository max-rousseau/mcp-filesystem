FROM python:3.13-slim

WORKDIR /app

# Install the package
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash mcp
USER mcp

# Create config directory structure
RUN mkdir -p /home/mcp/.config/mcp-yamlfilesystem

# Default to HTTP mode on all interfaces
ENV MCP_HTTP_ENABLED=true
ENV MCP_HTTP_HOST=0.0.0.0
ENV MCP_HTTP_PORT=8000

EXPOSE 8000

ENTRYPOINT ["mcp-yamlfilesystem"]
