import pytest

from crew.core.errors import NoFreePortError
from crew.core.ports import find_free_port


def test_skips_reserved_ports(monkeypatch):
    import crew.core.ports as ports
    monkeypatch.setattr(ports, "_is_free", lambda p: True)
    assert find_free_port(reserved={9120, 9121}, base=9120, max_port=9199) == 9122


def test_skips_os_occupied_ports(monkeypatch):
    import crew.core.ports as ports
    monkeypatch.setattr(ports, "_is_free", lambda p: p != 9120)
    assert find_free_port(reserved=set(), base=9120, max_port=9199) == 9121


def test_raises_when_range_exhausted(monkeypatch):
    import crew.core.ports as ports
    monkeypatch.setattr(ports, "_is_free", lambda p: False)
    with pytest.raises(NoFreePortError):
        find_free_port(reserved=set(), base=9120, max_port=9121)
