"""Test package. The autopilot scheduler never runs under tests."""
import os

os.environ.setdefault("JOB_MCP_NO_SCHEDULER", "1")
