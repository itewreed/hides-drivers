"""Konfiguration (pydantic) und Speicherung als JSON."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal, Optional

from pydantic import BaseModel, Field

CONFIG_PATH = Path(os.environ.get("DVBT_SENDER_CONFIG", Path.home() / ".config" / "dvbt-sender" / "config.json"))


class Program(BaseModel):
    name: str = "Programm"
    provider: str = ""
    enabled: bool = True
    source_type: Literal["file", "url", "testbild"] = "file"
    source: str = ""
    loop: bool = True
    # Nur für URLs: mit -re auf Echtzeit drosseln (für Dateien auf HTTP/SMB, nicht für Live-Streams).
    throttle: bool = False
    video_format: Literal["sd169", "sd43", "hd720", "hd1080"] = "sd169"
    video_codec: Literal["mpeg2", "h264"] = "mpeg2"
    audio_codec: Literal["mp2", "ac3"] = "mp2"
    audio_bitrate: int = 192_000
    # 0 = automatisch aus der verfügbaren Nutzrate berechnen.
    video_bitrate: int = 0
    service_id: int = 0  # 0 = automatisch (1, 2, 3, ...)


class Transmitter(BaseModel):
    output: Literal["hides", "file", "udp"] = "hides"
    adapter: int = 0
    device: str = ""  # z.B. /dev/usb-it950x0; leer = --adapter verwenden
    frequency: int = 482_000_000
    bandwidth: int = 8_000_000
    constellation: Literal["QPSK", "16-QAM", "64-QAM"] = "64-QAM"
    code_rate: Literal["1/2", "2/3", "3/4", "5/6", "7/8"] = "2/3"
    guard_interval: Literal["1/32", "1/16", "1/8", "1/4"] = "1/32"
    transmission_mode: Literal["2K", "4K", "8K"] = "8K"
    gain: Optional[int] = None
    dc_i: Optional[int] = None
    dc_q: Optional[int] = None
    spectral_inversion: Literal["auto", "on", "off"] = "auto"
    file_path: str = str(Path.home() / "dvbt-ausgabe.ts")
    udp_address: str = "127.0.0.1:1234"


class Multiplex(BaseModel):
    ts_id: int = 1
    original_network_id: int = 0x2000
    network_id: int = 0x3001
    network_name: str = "Heimsender"
    reserve_percent: float = 6.0  # Puffer für PSI/SI und Schwankungen


class Config(BaseModel):
    transmitter: Transmitter = Field(default_factory=Transmitter)
    multiplex: Multiplex = Field(default_factory=Multiplex)
    programs: list[Program] = Field(default_factory=list)


def load_config(path: Path = CONFIG_PATH) -> Config:
    if path.exists():
        try:
            return Config.model_validate_json(path.read_text())
        except Exception:
            pass
    return Config(programs=[Program(name="Testbild", source_type="testbild")])


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg.model_dump(), indent=2, ensure_ascii=False))
    tmp.replace(path)
