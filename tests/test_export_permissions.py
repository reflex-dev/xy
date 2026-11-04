"""Atomic export permissions must not widen access across platforms or groups."""

from __future__ import annotations

import errno
import os
import stat
import struct
import sys
from types import SimpleNamespace

import pytest

from xy import export as export_module


def test_publish_mode_skips_non_posix_even_when_fchmod_exists(tmp_path, monkeypatch):
    target = tmp_path / "chart.html"
    target.write_text("original")

    def reject(*args):
        pytest.fail("non-POSIX export attempted to set POSIX permissions")

    simulated_windows = SimpleNamespace(**{**vars(os), "name": "nt", "fchmod": reject})
    monkeypatch.setattr(export_module, "os", simulated_windows)
    export_module._publish_mode(-1, target)
    assert target.read_text() == "original"


@pytest.mark.skipif(os.name != "posix", reason="POSIX group ownership")
@pytest.mark.parametrize("writer", ["bytes", "text"])
@pytest.mark.parametrize("deny_group_change", [False, True])
def test_existing_export_preserves_group_or_stays_private(
    tmp_path, monkeypatch, writer, deny_group_change
):
    target = tmp_path / "chart.html"
    target.write_text("old")
    original_group = target.stat().st_gid
    other_groups = set(os.getgroups()) - {original_group}
    if not other_groups:
        pytest.skip("requires membership in a second group")
    restricted_group = min(other_groups)
    os.chown(target, -1, restricted_group)
    target.chmod(0o640)
    if deny_group_change:

        def reject_group_change(fd, uid, gid):
            assert uid == -1 and gid == restricted_group
            raise OSError(errno.EPERM, "cannot preserve group")

        monkeypatch.setattr(export_module.os, "fchown", reject_group_change)
    if writer == "bytes":
        export_module._atomic_write_bytes(target, b"new chart")
    else:
        export_module._atomic_write_text(target, "new chart")
    assert target.read_bytes() == b"new chart"
    published = target.stat()
    if deny_group_change:
        assert stat.S_IMODE(published.st_mode) == 0o600
    else:
        assert published.st_gid == restricted_group
        assert stat.S_IMODE(published.st_mode) == 0o640
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux POSIX ACL xattrs")
@pytest.mark.parametrize("existing_acl", [False, True])
def test_replacement_does_not_inherit_new_named_user_access(tmp_path, existing_acl):
    def acl_for(user):
        entries = [
            (1, 6, 0xFFFFFFFF),
            (2, 4, user),
            (4, 0, 0xFFFFFFFF),
            (16, 4, 0xFFFFFFFF),
            (32, 0, 0xFFFFFFFF),
        ]
        return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in entries)

    try:
        os.setxattr(tmp_path, "system.posix_acl_default", acl_for(12345))
    except OSError as error:
        if error.errno in (errno.ENOTSUP, errno.EOPNOTSUPP):
            pytest.skip("filesystem does not support POSIX ACLs")
        raise
    target = tmp_path / "chart.html"
    target.write_text("old")
    os.removexattr(target, "system.posix_acl_access")
    target.chmod(0o640)
    if existing_acl:
        os.setxattr(target, "system.posix_acl_access", acl_for(12346))
    export_module._atomic_write_text(target, "new")
    assert target.read_text() == "new"
    if existing_acl:
        assert os.getxattr(target, "system.posix_acl_access") == acl_for(12346)
    else:
        with pytest.raises(OSError) as missing:
            os.getxattr(target, "system.posix_acl_access")
        assert missing.value.errno == errno.ENODATA


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux POSIX ACL xattrs")
def test_unreadable_existing_acl_leaves_export_private(tmp_path, monkeypatch):
    target = tmp_path / "chart.html"
    target.write_text("old")
    target.chmod(0o640)

    def reject_acl(*args):
        raise OSError(errno.EPERM, "cannot inspect access ACL")

    monkeypatch.setattr(export_module.os, "getxattr", reject_acl)
    export_module._atomic_write_text(target, "new")
    assert target.read_text() == "new"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(tmp_path.glob(".*.tmp"))


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux POSIX ACL xattrs")
@pytest.mark.parametrize("writer", ["bytes", "text"])
@pytest.mark.parametrize(
    "read_error, remove_error, expected_mode",
    [
        (errno.ENOTSUP, errno.ENOTSUP, 0o640),
        (errno.EOPNOTSUPP, errno.EOPNOTSUPP, 0o640),
        (errno.ENODATA, errno.ENOTSUP, 0o640),
        (errno.ENOTSUP, errno.ENODATA, 0o640),
        (errno.ENOTSUP, errno.EPERM, 0o600),
    ],
)
def test_unsupported_acl_keeps_mode_but_denied_acl_stays_private(
    tmp_path, monkeypatch, writer, read_error, remove_error, expected_mode
):
    target = tmp_path / "chart.html"
    target.write_text("old")
    target.chmod(0o640)

    def no_acl(*args):
        raise OSError(read_error, "cannot read access ACL")

    def no_acl_removal(*args):
        raise OSError(remove_error, "cannot remove access ACL")

    monkeypatch.setattr(export_module.os, "getxattr", no_acl)
    monkeypatch.setattr(export_module.os, "removexattr", no_acl_removal)
    if writer == "bytes":
        export_module._atomic_write_bytes(target, b"new")
    else:
        export_module._atomic_write_text(target, "new")
    assert target.read_bytes() == b"new"
    assert stat.S_IMODE(target.stat().st_mode) == expected_mode
    assert not list(tmp_path.glob(".*.tmp"))
