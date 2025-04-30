import os

import pytest


def pytest_collection_modifyitems(items: list) -> None:
    """Automatically mark tests based on directory structure."""
    for item in items:
        filepath = os.path.relpath(item.fspath)

        if "tests/unit/" in filepath:
            item.add_marker(pytest.mark.unit)
        elif "tests/integration/" in filepath:
            item.add_marker(pytest.mark.integration)
