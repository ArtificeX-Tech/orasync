from __future__ import annotations

import pytest

from orasync.errors import UnsafeArchiveError
from orasync.paths import validate_archive_name


@pytest.mark.parametrize("name", ["mimetype", "stack.xml", "data/layer.png", "Thumbnails/thumbnail.png"])
def test_validate_archive_name_accepts_safe_names(name: str):
    assert validate_archive_name(name) == name


@pytest.mark.parametrize("name", ["", "/tmp/file", "../file", "data/../file", "C:/file", "data\\file"])
def test_validate_archive_name_rejects_unsafe_names(name: str):
    with pytest.raises(UnsafeArchiveError):
        validate_archive_name(name)

