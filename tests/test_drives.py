import plistlib
import subprocess
from unittest.mock import Mock

import pytest

from pulse.core import drives


def response(data):
    return subprocess.CompletedProcess([], 0, plistlib.dumps(data), b"")


@pytest.fixture(autouse=True)
def macos(monkeypatch):
    monkeypatch.setattr(drives.sys, "platform", "darwin")


def test_read_physical_devices_and_unsupported_smart(monkeypatch):
    run = Mock(
        side_effect=[
            response({"WholeDisks": ["disk0", "disk2", "disk0"]}),
            response(
                {
                    "DeviceIdentifier": "disk0",
                    "WholeDisk": True,
                    "MediaName": "Test SSD",
                    "TotalSize": 1_000_000_000,
                    "Internal": True,
                    "SolidState": True,
                    "SMARTStatus": "Verified",
                    "BusProtocol": "Test bus",
                    "SMARTDeviceSpecificKeysMayVaryNotGuaranteed": {"TEMPERATURE": 300},
                }
            ),
            response(
                {
                    "DeviceIdentifier": "disk2",
                    "WholeDisk": True,
                    "SMARTStatus": "Not Supported",
                    "TotalSize": True,
                }
            ),
        ]
    )
    monkeypatch.setattr(drives.subprocess, "run", run)
    result = drives.get_drives()
    assert result.complete and len(result.drives) == 2
    assert result.drives[0].smart_attributes == {"TEMPERATURE": 300}  # No guessed unit conversion.
    assert result.drives[1].smart_status == "Not Supported"
    assert result.drives[1].total_bytes is None and result.drives[1].solid_state is None
    assert run.call_args_list[0].args[0] == ("/usr/sbin/diskutil", "list", "-plist", "physical")
    assert run.call_args_list[1].args[0] == ("/usr/sbin/diskutil", "info", "-plist", "disk0")
    assert all(
        0 < call.kwargs["timeout"] <= 5 and not call.kwargs.get("shell")
        for call in run.call_args_list
    )


@pytest.mark.parametrize("payload", [b"not plist", b"<plist><dict>", plistlib.dumps([])])
def test_bad_disk_response_is_unavailable(monkeypatch, payload):
    monkeypatch.setattr(
        drives.subprocess,
        "run",
        Mock(return_value=subprocess.CompletedProcess([], 0, payload, b"")),
    )
    result = drives.get_drives()
    assert not result.complete and result.problems and result.drives == ()


def test_unexpected_identifier_never_becomes_command_argument(monkeypatch):
    run = Mock(return_value=response({"WholeDisks": ["disk0; rm", "disk0s1", 42]}))
    monkeypatch.setattr(drives.subprocess, "run", run)
    result = drives.get_drives()
    assert not result.complete and not result.drives
    assert run.call_count == 1


def test_device_disappearing_keeps_other_measurements(monkeypatch):
    run = Mock(
        side_effect=[
            response({"WholeDisks": ["disk0", "disk1"]}),
            subprocess.TimeoutExpired([], 5),
            response({"DeviceIdentifier": "disk1", "WholeDisk": True}),
        ]
    )
    monkeypatch.setattr(drives.subprocess, "run", run)
    result = drives.get_drives()
    assert not result.complete and len(result.drives) == 1 and result.problems
    assert result.drives[0].smart_status is None


def test_unavailable_platform_never_starts_tool(monkeypatch):
    monkeypatch.setattr(drives.sys, "platform", "linux")
    run = Mock()
    monkeypatch.setattr(drives.subprocess, "run", run)
    assert not drives.get_drives().complete
    run.assert_not_called()


def test_replaced_device_is_rejected(monkeypatch):
    monkeypatch.setattr(
        drives.subprocess,
        "run",
        Mock(
            side_effect=[
                response({"WholeDisks": ["disk0"]}),
                response({"DeviceIdentifier": "disk1", "WholeDisk": True}),
            ]
        ),
    )
    result = drives.get_drives()
    assert not result.complete and not result.drives
