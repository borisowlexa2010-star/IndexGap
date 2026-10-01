# -*- coding: utf-8 -*-
"""
Тесты не ходят в сеть — и это проверяется, а не обещается.

Ревью нашло, что перевёрнутый флаг пробного прогона заставил бы один из тестов
отправить запрос на настоящий сервер IndexNow: набор прошёл бы, а адреса
уехали бы поисковику. Подмена `urlopen` в отдельных тестах от этого не
защищает — защищает запрет на само соединение.

Локальные адреса разрешены: тесты вправе поднимать сервер на 127.0.0.1.
"""

import socket

_LOCAL = ("127.0.0.1", "localhost", "::1")
_real_connect = socket.socket.connect


def _guarded(self, address, *args, **kwargs):
    host = address[0] if isinstance(address, tuple) else address
    if isinstance(host, str) and host not in _LOCAL and not host.startswith("/"):
        raise AssertionError(f"тест попытался выйти в сеть: {host}")
    return _real_connect(self, address, *args, **kwargs)


socket.socket.connect = _guarded
