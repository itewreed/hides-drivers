"""Aufbau der Befehlszeilen (FFmpeg, TSDuck) und Prozessüberwachung."""

from __future__ import annotations

import asyncio
import collections
import os
import shlex
import signal
import tempfile
import time
from xml.sax.saxutils import escape as xml_escape
from dataclasses import dataclass, field

from .config import Config, Program
from .dvbt import useful_bitrate

BASE_PORT = 21000
PSI_OVERHEAD = 40_000      # PAT/PMT/SDT/PCR je Programm, bit/s
TS_OVERHEAD = 1.07         # TS-/PES-Header auf Video+Audio
MIN_VIDEO = {"mpeg2": 1_500_000, "h264": 700_000}
MAX_VIDEO = {("mpeg2", "sd"): 9_000_000, ("mpeg2", "hd"): 19_000_000, ("h264", "sd"): 8_000_000, ("h264", "hd"): 18_000_000}

FORMATS = {
    # Name: (Breite, Höhe, Anzeige-Seitenverhältnis, SD/HD)
    "sd169": (720, 576, "16/9", "sd"),
    "sd43": (720, 576, "4/3", "sd"),
    "hd720": (1280, 720, "16/9", "hd"),
    "hd1080": (1920, 1080, "16/9", "hd"),
}


SERVICE_TYPE_NAMES = {0x01: "digital_tv", 0x11: "mpeg2_digital_hdtv",
                      0x16: "advanced_codec_digital_sdtv", 0x19: "advanced_codec_digital_hdtv"}


class PlanError(ValueError):
    pass


@dataclass
class ProgramPlan:
    index: int
    program: Program
    service_id: int
    port: int
    pmt_pid: int
    start_pid: int
    video_bitrate: int
    mux_bitrate: int


@dataclass
class Plan:
    total_bitrate: int
    usable_bitrate: int
    programs: list[ProgramPlan]
    warnings: list[str] = field(default_factory=list)

    @property
    def allocated(self) -> int:
        return sum(p.mux_bitrate for p in self.programs)


def _mux_for(video: int, audio: int) -> int:
    return int((video + audio) * TS_OVERHEAD + PSI_OVERHEAD)


def _video_for(mux: int, audio: int) -> int:
    return int((mux - PSI_OVERHEAD) / TS_OVERHEAD - audio)


def make_plan(cfg: Config) -> Plan:
    """Verteilt die DVB-T-Nutzrate auf die aktiven Programme."""
    tx = cfg.transmitter
    total = useful_bitrate(tx.bandwidth, tx.constellation, tx.code_rate, tx.guard_interval, tx.transmission_mode)
    usable = int(total * (1 - cfg.multiplex.reserve_percent / 100))
    active = [(i, p) for i, p in enumerate(cfg.programs) if p.enabled]
    if not active:
        raise PlanError("Kein aktives Programm.")

    plans: list[ProgramPlan] = []
    warnings: list[str] = []
    used_ids: set[int] = set()
    fixed = sum(_mux_for(p.video_bitrate, p.audio_bitrate) for _, p in active if p.video_bitrate > 0)
    auto = [p for _, p in active if p.video_bitrate <= 0]
    per_auto = (usable - fixed) // len(auto) if auto else 0

    next_id = 1
    for slot, (i, p) in enumerate(active):
        sid = p.service_id
        if sid <= 0:
            while next_id in used_ids or any(q.service_id == next_id for _, q in active):
                next_id += 1
            sid = next_id
        if sid in used_ids:
            raise PlanError(f"Service-ID {sid} ist doppelt vergeben.")
        used_ids.add(sid)

        kind = FORMATS[p.video_format][3]
        if p.video_bitrate > 0:
            video = p.video_bitrate
        else:
            video = _video_for(per_auto, p.audio_bitrate)
            cap = MAX_VIDEO[(p.video_codec, kind)]
            if video > cap:
                video = cap
        if video < MIN_VIDEO[p.video_codec]:
            raise PlanError(
                f"Für „{p.name}“ bleiben nur {video / 1e6:.2f} Mbit/s Video. "
                "Weniger Programme, H.264 oder robustere Sendeparameter mit mehr Datenrate wählen."
            )
        if kind == "hd" and p.video_codec == "mpeg2":
            warnings.append(f"„{p.name}“: HD in MPEG-2 wird von vielen DVB-T-Empfängern nicht unterstützt.")
        plans.append(
            ProgramPlan(
                index=i,
                program=p,
                service_id=sid,
                port=BASE_PORT + slot,
                pmt_pid=0x1000 + slot * 0x10,
                start_pid=0x100 + slot * 0x20,
                video_bitrate=video,
                mux_bitrate=_mux_for(video, p.audio_bitrate),
            )
        )

    plan = Plan(total_bitrate=total, usable_bitrate=usable, programs=plans, warnings=warnings)
    if plan.allocated > total:
        raise PlanError(
            f"Die Programme brauchen {plan.allocated / 1e6:.2f} Mbit/s, "
            f"der Kanal trägt aber nur {total / 1e6:.2f} Mbit/s."
        )
    if plan.allocated > usable:
        warnings.append("Die Programme belegen auch die Reserve, das kann zu Aussetzern führen.")
    return plan


# ---------------------------------------------------------------------------
# Befehlszeilen
# ---------------------------------------------------------------------------

def ffmpeg_command(cfg: Config, pp: ProgramPlan, ffmpeg: str = "ffmpeg") -> list[str]:
    p = pp.program
    width, height, dar, kind = FORMATS[p.video_format]
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "warning", "-nostats",
           "-progress", "pipe:1", "-stats_period", "2"]

    if p.source_type == "testbild":
        cmd += ["-re", "-f", "lavfi", "-i", f"testsrc2=size={width}x{height}:rate=25",
                "-re", "-f", "lavfi", "-i", "sine=frequency=1000:sample_rate=48000"]
        cmd += ["-map", "0:v:0", "-map", "1:a:0"]
    else:
        if not p.source:
            raise PlanError(f"„{p.name}“ hat keine Quelle.")
        if p.source_type == "file" or p.throttle:
            cmd += ["-re"]
            if p.loop:
                cmd += ["-stream_loop", "-1"]
        cmd += ["-i", p.source, "-map", "0:v:0", "-map", "0:a:0?"]

    # Auf Zielformat bringen: einpassen, mit Schwarz auffüllen, 25 Bilder/s, 4:2:0.
    if kind == "sd":
        box_w = 1024 if dar == "16/9" else 768
        vf = (f"scale={box_w}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={box_w}:{height}:(ow-iw)/2:(oh-ih)/2,scale={width}:{height},setdar={dar}")
    else:
        vf = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1")
    vf += ",fps=25,format=yuv420p"
    cmd += ["-vf", vf]

    v = pp.video_bitrate
    if p.video_codec == "mpeg2":
        vbv = 1_835_008 if kind == "sd" else 9_781_248
        cmd += ["-c:v", "mpeg2video", "-b:v", str(v), "-minrate", str(v), "-maxrate", str(v),
                "-bufsize", str(min(vbv, v)), "-g", "12", "-bf", "2"]
    else:
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-profile:v", "high", "-level:v", "4.0",
                "-b:v", str(v), "-maxrate", str(v), "-bufsize", str(v),
                "-x264-params", "nal-hrd=cbr:force-cfr=1", "-g", "25", "-bf", "2"]

    cmd += ["-c:a", p.audio_codec, "-b:a", str(p.audio_bitrate), "-ar", "48000", "-ac", "2"]

    mux = cfg.multiplex
    cmd += ["-f", "mpegts", "-muxrate", str(pp.mux_bitrate),
            "-mpegts_service_id", str(pp.service_id),
            "-mpegts_pmt_start_pid", str(pp.pmt_pid),
            "-mpegts_start_pid", str(pp.start_pid),
            "-mpegts_transport_stream_id", str(mux.ts_id),
            "-mpegts_original_network_id", str(mux.original_network_id),
            "-mpegts_service_type", SERVICE_TYPE_NAMES[service_type(p)],
            "-mpegts_flags", "+resend_headers",
            "-metadata", f"service_name={p.name}",
            "-metadata", f"service_provider={p.provider or mux.network_name}",
            f"udp://127.0.0.1:{pp.port}?pkt_size=1316"]
    return cmd


def service_type(p: Program) -> int:
    hd = FORMATS[p.video_format][3] == "hd"
    if p.video_codec == "h264":
        return 0x19 if hd else 0x16
    return 0x11 if hd else 0x01


def nit_xml(cfg: Config, plan: Plan) -> str:
    """NIT mit Netzwerkname, Service-Liste und Senderplätzen (LCN, EACEM)."""
    mux = cfg.multiplex
    services = "\n".join(
        f'          <service service_id="{pp.service_id}" service_type="{service_type(pp.program)}"/>'
        for pp in plan.programs)
    lcns = "\n".join(
        f'          <service service_id="{pp.service_id}" logical_channel_number="{k + 1}" visible_service="true"/>'
        for k, pp in enumerate(plan.programs))
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<tsduck>
  <NIT version="0" current="true" network_id="{mux.network_id}" actual="true">
    <network_name_descriptor network_name="{xml_escape(mux.network_name, {'"': '&quot;'})}"/>
    <transport_stream transport_stream_id="{mux.ts_id}" original_network_id="{mux.original_network_id}">
      <service_list_descriptor>
{services}
      </service_list_descriptor>
      <private_data_specifier_descriptor private_data_specifier="0x00000028"/>
      <eacem_logical_channel_number_descriptor>
{lcns}
      </eacem_logical_channel_number_descriptor>
    </transport_stream>
  </NIT>
</tsduck>
"""


def tsp_command(cfg: Config, plan: Plan, tsp: str = "tsp", nit_file: str = "nit.xml") -> list[str]:
    tx, mux = cfg.transmitter, cfg.multiplex
    # --bitrate: der Null-Eingang hat sonst keine Bitrate, dann erzeugen pat/sdt --create nie Tabellen.
    cmd = [tsp, "--verbose", "--bitrate", str(plan.total_bitrate), "--max-flushed-packets", "70", "-I", "null"]
    # Leere PAT/SDT als Grundgerüst; merge trägt die Programme dort ein.
    cmd += ["-P", "pat", "--create", "--ts-id", str(mux.ts_id)]
    cmd += ["-P", "sdt", "--create", "--ts-id", str(mux.ts_id), "--original-network-id", str(mux.original_network_id)]
    for pp in plan.programs:
        child = f"{shlex.quote(tsp)} -I ip --local-address 127.0.0.1 {pp.port}"
        cmd += ["-P", "merge", "--bitrate", str(pp.mux_bitrate), "--no-wait", child]
    cmd += ["-P", "inject", "--pid", "16", "--bitrate", "3000", "--xml", nit_file]
    if tx.output == "hides":
        cmd += ["-O", "hides", "--frequency", str(tx.frequency), "--bandwidth", str(tx.bandwidth),
                "--constellation", tx.constellation, "--high-priority-fec", tx.code_rate,
                "--guard-interval", tx.guard_interval, "--transmission-mode", tx.transmission_mode,
                "--spectral-inversion", tx.spectral_inversion]
        if tx.device:
            cmd += ["--device", tx.device]
        else:
            cmd += ["--adapter", str(tx.adapter)]
        if tx.gain is not None:
            cmd += ["--gain", str(tx.gain)]
        if tx.dc_i is not None and tx.dc_q is not None:
            cmd += ["--dc-compensation", f"{tx.dc_i}/{tx.dc_q}"]
    else:
        # Ohne Gerät gibt niemand den Takt vor: auf die DVB-T-Nutzrate regeln.
        cmd += ["-P", "regulate", "--bitrate", str(plan.total_bitrate)]
        if tx.output == "file":
            cmd += ["-O", "file", tx.file_path]
        else:
            cmd += ["-O", "ip", "--enforce-burst", tx.udp_address]
    return cmd


# ---------------------------------------------------------------------------
# Prozessüberwachung
# ---------------------------------------------------------------------------

class Proc:
    def __init__(self, name: str, cmd: list[str], restart: bool):
        self.name = name
        self.cmd = cmd
        self.restart = restart
        self.process: asyncio.subprocess.Process | None = None
        self.log: collections.deque[str] = collections.deque(maxlen=300)
        self.progress: dict[str, str] = {}
        self.state = "gestoppt"
        self.restarts = 0
        self.started_at = 0.0
        self._tasks: list[asyncio.Task] = []

    def add_log(self, line: str) -> None:
        self.log.append(f"{time.strftime('%H:%M:%S')} {line}")

    async def start(self) -> None:
        self.add_log("Start: " + shlex.join(self.cmd))
        self.process = await asyncio.create_subprocess_exec(
            *self.cmd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        self.state = "läuft"
        self.started_at = time.time()
        self._tasks = [
            asyncio.create_task(self._read(self.process.stdout, progress=True)),
            asyncio.create_task(self._read(self.process.stderr, progress=False)),
        ]

    async def _read(self, stream: asyncio.StreamReader | None, progress: bool) -> None:
        if stream is None:
            return
        current: dict[str, str] = {}
        while True:
            raw = await stream.readline()
            if not raw:
                return
            line = raw.decode(errors="replace").rstrip()
            if progress and "=" in line and " " not in line.split("=", 1)[0]:
                k, v = line.split("=", 1)
                current[k] = v.strip()
                if k == "progress":
                    self.progress = current
                    current = {}
            elif line:
                self.add_log(line)

    def alive(self) -> bool:
        return self.process is not None and self.process.returncode is None

    async def wait(self) -> int:
        assert self.process is not None
        rc = await self.process.wait()
        for t in self._tasks:
            try:
                await asyncio.wait_for(t, 2)
            except Exception:
                pass
        return rc

    async def stop(self) -> None:
        if not self.alive():
            return
        assert self.process is not None
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(self.process.wait(), 5)
        except asyncio.TimeoutError:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.process.wait()
        self.state = "gestoppt"

    def status(self) -> dict:
        return {
            "name": self.name,
            "state": self.state,
            "restarts": self.restarts,
            "uptime": int(time.time() - self.started_at) if self.alive() else 0,
            "progress": self.progress,
            "log": list(self.log)[-60:],
        }


class Supervisor:
    """Startet tsp (Multiplexer + Ausgabe) und je Programm einen FFmpeg-Prozess."""

    def __init__(self, tsp: str = "tsp", ffmpeg: str = "ffmpeg"):
        self.tsp = tsp
        self.ffmpeg = ffmpeg
        self.running = False
        self.error = ""
        self.plan: Plan | None = None
        self.mux: Proc | None = None
        self.encoders: list[Proc] = []
        self._watchers: list[asyncio.Task] = []
        self._lock = asyncio.Lock()
        self._workdir = tempfile.mkdtemp(prefix="dvbt-sender-")

    async def start(self, cfg: Config) -> Plan:
        async with self._lock:
            if self.running:
                raise PlanError("Der Sender läuft bereits.")
            plan = make_plan(cfg)
            enc_cmds = [(pp, ffmpeg_command(cfg, pp, self.ffmpeg)) for pp in plan.programs]
            self.plan = plan
            self.error = ""
            nit_file = os.path.join(self._workdir, "nit.xml")
            with open(nit_file, "w", encoding="utf-8") as f:
                f.write(nit_xml(cfg, plan))
            self.mux = Proc("Multiplexer / Ausgabe (tsp)", tsp_command(cfg, plan, self.tsp, nit_file), restart=False)
            self.encoders = [Proc(f"{pp.service_id}: {pp.program.name}", c, restart=True) for pp, c in enc_cmds]
            self.running = True
            await self.mux.start()
            # merge-Kindprozesse müssen ihre UDP-Ports öffnen, bevor FFmpeg sendet.
            await asyncio.sleep(1.0)
            if not self.mux.alive():
                rc = await self.mux.wait()
                self.running = False
                self.mux.state = f"beendet ({rc})"
                self.error = "tsp konnte nicht starten, siehe Protokoll."
                raise PlanError(self.error)
            self._watchers = [asyncio.create_task(self._watch_mux())]
            for enc in self.encoders:
                await enc.start()
                self._watchers.append(asyncio.create_task(self._watch_encoder(enc)))
            return plan

    async def _watch_mux(self) -> None:
        assert self.mux is not None
        rc = await self.mux.wait()
        self.mux.state = f"beendet ({rc})"
        if self.running:
            self.error = "Der Multiplexer (tsp) hat sich beendet, siehe Protokoll."
            await self.stop(keep_error=True)

    async def _watch_encoder(self, enc: Proc) -> None:
        backoff = 2.0
        while True:
            rc = await enc.wait()
            if not self.running:
                return
            enc.state = f"Neustart (Fehler {rc})"
            enc.add_log(f"FFmpeg beendet mit Code {rc}, Neustart in {backoff:.0f} s")
            await asyncio.sleep(backoff)
            if not self.running:
                return
            if time.time() - enc.started_at > 60:
                backoff = 2.0
            else:
                backoff = min(backoff * 2, 30.0)
            enc.restarts += 1
            await enc.start()

    async def stop(self, keep_error: bool = False) -> None:
        self.running = False
        procs = [*self.encoders, *([self.mux] if self.mux else [])]
        await asyncio.gather(*(p.stop() for p in procs), return_exceptions=True)
        current = asyncio.current_task()
        for w in self._watchers:
            if w is not current:
                w.cancel()
        self._watchers = []
        if not keep_error:
            self.error = ""

    def status(self) -> dict:
        return {
            "running": self.running,
            "error": self.error,
            "mux": self.mux.status() if self.mux else None,
            "encoders": [e.status() for e in self.encoders],
        }
