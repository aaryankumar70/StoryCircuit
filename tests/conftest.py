import sys
import os
import pytest

# Ensure workspace root is in sys.path
workspace_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if workspace_dir not in sys.path:
    sys.path.insert(0, workspace_dir)

@pytest.fixture(autouse=True)
def mock_external_ai_in_unit_tests(monkeypatch, request):
    """By default in unit tests, mock local_model.is_available to False to prevent
    hitting real Ollama and generating on CPU during 240+ unit tests, unless marked 'live_ai'.
    """
    if "live_ai" in request.keywords:
        return
    try:
        from curiosity_engine.intelligence.local_model import local_model
        monkeypatch.setattr(local_model, "is_available", lambda: False)
        monkeypatch.setattr(local_model, "is_configured", lambda: False)
    except ImportError:
        pass
