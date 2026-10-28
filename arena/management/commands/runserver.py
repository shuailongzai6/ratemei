import socket

from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserverCommand
from django.core.servers.basehttp import WSGIServer


class DualStackWSGIServer(WSGIServer):
    def server_bind(self):
        if self.address_family == socket.AF_INET6 and self.server_address[0] == "::":
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


class Command(StaticRunserverCommand):
    server_cls = DualStackWSGIServer

    def handle(self, *args, **options):
        addrport = options["addrport"]
        if not addrport or addrport.isdigit():
            options["addrport"] = f"[::]:{addrport or self.default_port}"
        return super().handle(*args, **options)
