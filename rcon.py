"""Minimal asynchronous SA-MP RCON client (UDP). The server needs "query 1" in server.cfg."""
import asyncio
import re
import socket
import struct

ENC = "cp1251"


def build_packet(ip: str, port: int, password: str, command: str) -> bytes:
    pw = password.encode("latin-1")
    cmd = command.encode(ENC, errors="replace")
    head = b"SAMP" + socket.inet_aton(ip) + struct.pack("<H", port) + b"x"
    return head + struct.pack("<H", len(pw)) + pw + struct.pack("<H", len(cmd)) + cmd


class _Proto(asyncio.DatagramProtocol):
    def __init__(self, idle: float, max_total: float):
        self.lines: list[str] = []
        self.done: asyncio.Future = asyncio.get_running_loop().create_future()
        self.idle, self.max_total = idle, max_total
        self._timer = None
        self._hard = None

    def connection_made(self, transport):
        self.transport = transport
        loop = asyncio.get_running_loop()
        self._hard = loop.call_later(self.max_total, self._finish)
        self._timer = loop.call_later(max(self.idle, 1.5), self._finish)

    def datagram_received(self, data, addr):
        if len(data) < 13 or data[:4] != b"SAMP" or data[10:11] != b"x":
            return
        (length,) = struct.unpack("<H", data[11:13])
        self.lines.append(data[13:13 + length].decode(ENC, errors="replace"))
        if self._timer:
            self._timer.cancel()
        self._timer = asyncio.get_running_loop().call_later(self.idle, self._finish)

    def error_received(self, exc):
        if not self.done.done():
            self.done.set_exception(exc)

    def _finish(self):
        if not self.done.done():
            self.done.set_result(self.lines)


async def rcon(host: str, port: int, password: str, command: str,
               idle: float = 0.7, max_total: float = 6.0) -> list[str]:
    if re.search(r"[\r\n\x00]", command):
        raise ValueError("Command contains control characters")
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port, family=socket.AF_INET, type=socket.SOCK_DGRAM)
    ip = infos[0][4][0]
    transport, proto = await loop.create_datagram_endpoint(
        lambda: _Proto(idle, max_total), remote_addr=(ip, port))
    try:
        transport.sendto(build_packet(ip, port, password, command))
        return await proto.done
    finally:
        for t in (proto._timer, proto._hard):
            if t:
                t.cancel()
        transport.close()
