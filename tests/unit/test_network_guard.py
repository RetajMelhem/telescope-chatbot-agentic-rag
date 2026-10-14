import socket

import pytest
from pytest_socket import SocketConnectBlockedError


def test_external_connections_are_blocked_before_connecting() -> None:
    # Loopback is permitted for Windows asyncio's internal socketpair only.
    # This test makes no actual connection: pytest-socket rejects this test-net address.
    with socket.socket() as connection:
        with pytest.warns(UserWarning), pytest.raises(SocketConnectBlockedError):
            connection.connect(("203.0.113.1", 443))
