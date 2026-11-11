# DVB-T Sender (Weboberfläche)

Bündelt mehrere Videodateien oder Streams zu einem DVB-T-Multiplex und sendet ihn
über den HiDes UT-100C (oder zum Testen als UDP-Stream bzw. in eine `.ts`-Datei).
Bedienung im Browser, auch vom Handy aus.

## So funktioniert es

```
Datei/Stream 1 ─ FFmpeg ─┐ UDP 127.0.0.1:21000
Datei/Stream 2 ─ FFmpeg ─┤ UDP 127.0.0.1:21001      tsp -I null
Testbild       ─ FFmpeg ─┘ ...                  ──▶  -P pat/sdt --create
                                                     -P merge (je Programm)
                                                     -P nit --create
                                                     -O hides --frequency ... --gain ...
```

* **FFmpeg** wandelt jede Quelle in DVB-taugliches Format: 25 Bilder/s, 4:2:0,
  SD 720×576 (16:9 oder 4:3, mit schwarzen Rändern eingepasst) oder HD,
  Video MPEG-2 oder H.264 mit konstanter Bitrate, Audio MP2 oder AC-3 mit 48 kHz.
  Der Programmname landet im SDT (`service_name`).
* **TSDuck (`tsp`)** fügt die Programme mit dem `merge`-Plugin zu einem Multiplex
  zusammen, baut PAT, SDT und NIT und gibt ihn über das `hides`-Plugin aus.
  Der Stick gibt den Takt vor.
* Die Software rechnet aus Bandbreite, Modulation, Coderate und Guard-Intervall die
  exakte DVB-T-Nutzrate aus (z. B. 8 MHz, 64-QAM, 2/3, 1/32 = 24,13 Mbit/s) und
  verteilt sie auf die Programme. Man kann je Programm auch eine feste Video-Bitrate
  vorgeben.
* Bricht eine Quelle ab, wird nur deren FFmpeg neu gestartet, die anderen Programme
  laufen weiter.

## Voraussetzungen

* Treiber aus diesem Repo (`linux-drivers`), Gerät erscheint als `/dev/usb-it950x0`
* TSDuck (`tsp`, `tshides`) mit HiDes-Unterstützung
* FFmpeg mit `libx264` (für H.264)
* Python ≥ 3.10

## Installation und Start

```sh
cd dvbt-sender
python3 -m venv ~/pyvenvs/dvbt-sender
~/pyvenvs/dvbt-sender/bin/pip install .
~/pyvenvs/dvbt-sender/bin/dvbt-sender
```

Dann im Browser <http://127.0.0.1:8095> öffnen.

Vom Handy oder einem anderen Rechner aus: `dvbt-sender --host 0.0.0.0` und
`http://<rechner>:8095` aufrufen. **Achtung:** Es gibt keine Anmeldung. Wer die Seite
erreicht, kann senden und die Ordner auf dem Rechner durchsuchen. Nur im eigenen Netz
verwenden.

Weitere Optionen: `--port`, `--tsp`, `--ffmpeg`, `--tshides` (Pfade zu den Programmen).
Die Einstellungen liegen in `~/.config/dvbt-sender/config.json`.

## Sendeparameter

| Feld | Bedeutung |
|---|---|
| Kanal / Frequenz | Kanalraster VHF K5–K12 (7 MHz) und UHF K21–K69 (8 MHz), oder freie Frequenz |
| Bandbreite | 5, 6, 7, 8 MHz |
| Modulation | QPSK, 16-QAM, 64-QAM: mehr Bits pro Träger, aber empfindlicher |
| Coderate | 1/2 (robust) bis 7/8 (mehr Datenrate). Damit stellt man den Fehlerschutz ein. Die Bitfehlerrate (BER) selbst ist ein Messwert am Empfänger. |
| Guard-Intervall | 1/32 bis 1/4: Schutz gegen Echos |
| Modus | 2K, 4K, 8K |
| Verstärkung | `--gain` in dB. Mit „Bereich“ fragt `tshides --gain-range` den erlaubten Bereich für Frequenz und Bandbreite ab. Leer = Gerätestandard. |
| DC-Kompensation | Optionaler I/Q-Offset gegen Trägerrest |

Hinweis zur Leistung: Der UT-100C liefert nur wenige Milliwatt. Senden ohne
Genehmigung ist nur über Kabel/Dämpfungsglied oder in abgeschirmter Umgebung zulässig.

## Testen ohne Stick

Ausgabe auf „UDP“ stellen und mit `vlc udp://@127.0.0.1:1234` ansehen, oder „Datei“
wählen und die Datei mit `tsanalyze` oder `ffprobe` prüfen.

## Entwicklung

```sh
pip install -e . pytest
pytest
```
