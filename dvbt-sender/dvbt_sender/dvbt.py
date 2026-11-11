"""DVB-T (EN 300 744) Hilfsfunktionen: Nutzdatenrate, Kanalraster."""

from __future__ import annotations

from fractions import Fraction

BANDWIDTHS_HZ = (5_000_000, 6_000_000, 7_000_000, 8_000_000)

CONSTELLATIONS = {"QPSK": 2, "16-QAM": 4, "64-QAM": 6}
CODE_RATES = {
    "1/2": Fraction(1, 2),
    "2/3": Fraction(2, 3),
    "3/4": Fraction(3, 4),
    "5/6": Fraction(5, 6),
    "7/8": Fraction(7, 8),
}
GUARD_INTERVALS = {
    "1/32": Fraction(1, 32),
    "1/16": Fraction(1, 16),
    "1/8": Fraction(1, 8),
    "1/4": Fraction(1, 4),
}
# Datenträger pro OFDM-Symbol und FFT-Größe.
TRANSMISSION_MODES = {"2K": (1512, 2048), "4K": (3024, 4096), "8K": (6048, 8192)}


def useful_bitrate(
    bandwidth_hz: int,
    constellation: str,
    code_rate: str,
    guard_interval: str,
    transmission_mode: str = "8K",
) -> int:
    """Nutzdatenrate des Transportstroms in bit/s (inkl. Nullpakete).

    Elementarperiode T = 7 / (8 * B[MHz]) µs, nutzbare Symboldauer Tu = FFT * T.
    Rate = Datenträger * Bits/Träger * Coderate * 188/204 / (Tu * (1 + GI)).
    Das Ergebnis hängt nicht vom Modus 2K/4K/8K ab, wird aber exakt so berechnet.
    """
    carriers, fft = TRANSMISSION_MODES[transmission_mode]
    t_elem = Fraction(7, 8) / Fraction(bandwidth_hz, 1_000_000) / 1_000_000  # Sekunden
    tu = fft * t_elem
    symbol = tu * (1 + GUARD_INTERVALS[guard_interval])
    bits = carriers * CONSTELLATIONS[constellation] * CODE_RATES[code_rate] * Fraction(188, 204)
    return int(bits / symbol)


def channel_list() -> list[dict]:
    """Kanalraster für Europa: VHF Band III (7 MHz) und UHF Band IV/V (8 MHz)."""
    chans = []
    for ch in range(5, 13):
        chans.append({"name": f"K{ch:02d} (VHF)", "frequency": int((142.5 + 7 * ch) * 1_000_000), "bandwidth": 7_000_000})
    for ch in range(21, 70):
        chans.append({"name": f"K{ch:02d} (UHF)", "frequency": (306 + 8 * ch) * 1_000_000, "bandwidth": 8_000_000})
    return chans
