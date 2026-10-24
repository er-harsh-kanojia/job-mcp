"""Job MCP backend: multi-platform job search and application automation.

Public entry points (used by run.py and server.py):
    tools.session.interactive_login / SUPPORTED_PLATFORMS
    tools.search.search_jobs / filter_jobs
    tools.apply.bulk_apply
    tools.tracker.get_application_summary
"""

import logging

# Library-style logging: never print to stdout (the MCP server speaks JSON-RPC
# over stdout). Callers decide where logs go; by default warnings reach stderr.
logging.getLogger("job_mcp").addHandler(logging.NullHandler())

__all__ = ["config", "browser", "session", "search", "apply", "tracker"]
