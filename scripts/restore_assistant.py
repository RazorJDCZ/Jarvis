"""Restore a named encrypted backup after stopping Jarvis; resume explicitly afterwards."""

from __future__ import annotations

import argparse
import socket

from jarvis.config import Settings
from jarvis.services.recovery import Recovery


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", help="Name listed in Hoy, for example jarvis-123.jbackup")
    args = parser.parse_args()
    config = Settings()
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", config.port)) == 0:
            parser.error("Pausa el supervisor y detén Jarvis antes de restaurar")
    with socket.socket() as probe:
        if (
            probe.connect_ex(("127.0.0.1", 18765)) == 0
            and not (config.data_dir / "supervisor.pause").exists()
        ):
            parser.error("Pausa primero el supervisor")
    print(Recovery(config).restore(args.backup))


if __name__ == "__main__":
    main()
