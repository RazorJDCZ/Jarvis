from __future__ import annotations

import json
from pathlib import Path

from jarvis.capabilities.gaming import GameLibrary


def test_inventory_reads_only_injected_steam_and_epic_manifests(tmp_path: Path) -> None:
    steam = tmp_path / "steam-library"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_123.acf").write_text(
        "\n".join(
            (
                '"AppState"',
                "{",
                '  "appid" "123"',
                '  "name" "Juego Seguro"',
                '  "installdir" "JuegoSeguro"',
                "}",
            )
        ),
        encoding="utf-8",
    )
    epic = tmp_path / "epic-manifests"
    nested = epic / "current"
    nested.mkdir(parents=True)
    (nested / "game.item").write_text(
        json.dumps(
            {
                "AppName": "EpicGame_01",
                "DisplayName": "Juego Epic",
                "InstallLocation": r"C:\Games\EpicGame",
            }
        ),
        encoding="utf-8",
    )

    library = GameLibrary(steam_roots=(steam,), epic_manifest_roots=(epic,))
    games = library.inventory()

    assert [(game.platform, game.game_id, game.name) for game in games] == [
        ("epic", "EpicGame_01", "Juego Epic"),
        ("steam", "123", "Juego Seguro"),
    ]
    assert library.launch_target("123", platform="steam") == "steam://rungameid/123"
    assert library.launch_target("EpicGame_01", platform="epic") == (
        "com.epicgames.launcher://apps/EpicGame_01?action=launch&silent=true"
    )


def test_external_steam_library_reference_is_never_followed(tmp_path: Path) -> None:
    injected = tmp_path / "injected"
    steamapps = injected / "steamapps"
    steamapps.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside_apps = outside / "steamapps"
    outside_apps.mkdir(parents=True)
    (outside_apps / "appmanifest_999.acf").write_text(
        '"appid" "999"\n"name" "Fuera"\n"installdir" "Fuera"',
        encoding="utf-8",
    )
    (steamapps / "libraryfolders.vdf").write_text(
        f'"path" "{outside}"',
        encoding="utf-8",
    )

    games = GameLibrary(steam_roots=(injected,)).inventory()

    assert games == ()


def test_malformed_or_incomplete_manifests_are_ignored(tmp_path: Path) -> None:
    steam = tmp_path / "steam"
    steamapps = steam / "steamapps"
    steamapps.mkdir(parents=True)
    (steamapps / "appmanifest_1.acf").write_text(
        '"appid" "2"\n"name" "Mismatch"',
        encoding="utf-8",
    )
    epic = tmp_path / "epic"
    epic.mkdir()
    (epic / "incomplete.item").write_text(
        json.dumps(
            {
                "AppName": "Incomplete",
                "DisplayName": "Incomplete",
                "bIsIncompleteInstall": True,
            }
        ),
        encoding="utf-8",
    )
    (epic / "unsafe.item").write_text(
        json.dumps({"AppName": "bad/app", "DisplayName": "Unsafe"}),
        encoding="utf-8",
    )

    assert GameLibrary(steam_roots=(steam,), epic_manifest_roots=(epic,)).inventory() == ()
