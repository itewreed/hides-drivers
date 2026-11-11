"""FastAPI-Server mit Weboberfläche."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config as cfgmod
from .config import Config
from .dvbt import channel_list
from .pipeline import PlanError, Supervisor, ffmpeg_command, make_plan, tsp_command

STATIC = Path(__file__).parent / "static"
VIDEO_EXT = {".ts", ".mts", ".m2ts", ".mp4", ".mkv", ".avi", ".mov", ".mpg", ".mpeg", ".vob",
             ".webm", ".wmv", ".flv", ".m4v", ".dv", ".3gp", ".ogv"}


def create_app(tsp: str = "tsp", ffmpeg: str = "ffmpeg", tshides: str = "tshides") -> FastAPI:
    app = FastAPI(title="DVB-T Sender")
    sup = Supervisor(tsp=tsp, ffmpeg=ffmpeg)
    state = {"cfg": cfgmod.load_config()}

    def plan_dict(cfg: Config) -> dict:
        try:
            plan = make_plan(cfg)
        except PlanError as e:
            return {"ok": False, "error": str(e)}
        return {
            "ok": True,
            "total_bitrate": plan.total_bitrate,
            "usable_bitrate": plan.usable_bitrate,
            "allocated": plan.allocated,
            "warnings": plan.warnings,
            "programs": [
                {"index": p.index, "name": p.program.name, "service_id": p.service_id,
                 "video_bitrate": p.video_bitrate, "mux_bitrate": p.mux_bitrate}
                for p in plan.programs
            ],
        }

    @app.get("/")
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/config")
    async def get_config():
        return state["cfg"].model_dump()

    @app.put("/api/config")
    async def put_config(cfg: Config):
        state["cfg"] = cfg
        cfgmod.save_config(cfg)
        return {"plan": plan_dict(cfg)}

    @app.post("/api/plan")
    async def plan(cfg: Config):
        return plan_dict(cfg)

    @app.post("/api/commands")
    async def commands(cfg: Config):
        """Zeigt die Befehlszeilen, die beim Start ausgeführt würden."""
        try:
            plan = make_plan(cfg)
            return {
                "tsp": tsp_command(cfg, plan, tsp),
                "ffmpeg": [ffmpeg_command(cfg, pp, ffmpeg) for pp in plan.programs],
            }
        except PlanError as e:
            raise HTTPException(400, str(e))

    @app.get("/api/channels")
    async def channels():
        return channel_list()

    @app.post("/api/start")
    async def start():
        try:
            await sup.start(state["cfg"])
        except PlanError as e:
            raise HTTPException(400, str(e))
        return sup.status()

    @app.post("/api/stop")
    async def stop():
        await sup.stop()
        return sup.status()

    @app.get("/api/status")
    async def status():
        return sup.status()

    @app.get("/api/tools")
    async def tools():
        return {name: shutil.which(path) for name, path in
                (("tsp", tsp), ("ffmpeg", ffmpeg), ("tshides", tshides))}

    @app.get("/api/devices")
    async def devices():
        return {"output": await _run([tshides, "--verbose"])}

    @app.get("/api/gain-range")
    async def gain_range():
        tx = state["cfg"].transmitter
        cmd = [tshides, "--gain-range", "--frequency", str(tx.frequency), "--bandwidth", str(tx.bandwidth)]
        cmd += ["--device", tx.device] if tx.device else ["--adapter", str(tx.adapter)]
        return {"output": await _run(cmd)}

    @app.get("/api/files")
    async def files(path: str = ""):
        p = Path(path).expanduser() if path else Path.home()
        if not p.is_dir():
            raise HTTPException(404, "Ordner nicht gefunden")
        entries = []
        try:
            for e in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if e.name.startswith("."):
                    continue
                if e.is_dir():
                    entries.append({"name": e.name, "dir": True})
                elif e.suffix.lower() in VIDEO_EXT:
                    entries.append({"name": e.name, "dir": False, "size": e.stat().st_size})
        except PermissionError:
            raise HTTPException(403, "Keine Berechtigung")
        return {"path": str(p.resolve()), "parent": str(p.resolve().parent), "entries": entries}

    @app.on_event("shutdown")
    async def shutdown():
        await sup.stop()

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


async def _run(cmd: list[str]) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
        out, _ = await asyncio.wait_for(proc.communicate(), 15)
        return out.decode(errors="replace")
    except FileNotFoundError:
        return f"{cmd[0]} nicht gefunden. Ist TSDuck installiert?"
    except asyncio.TimeoutError:
        return "Zeitüberschreitung"


def main() -> None:
    ap = argparse.ArgumentParser(description="Weboberfläche zum Senden von Videos als DVB-T über HiDes UT-100C")
    ap.add_argument("--host", default="127.0.0.1",
                    help="Adresse, auf der der Server lauscht (0.0.0.0 = im ganzen Netz erreichbar)")
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--tsp", default=os.environ.get("TSP", "tsp"))
    ap.add_argument("--ffmpeg", default=os.environ.get("FFMPEG", "ffmpeg"))
    ap.add_argument("--tshides", default=os.environ.get("TSHIDES", "tshides"))
    args = ap.parse_args()

    import uvicorn
    uvicorn.run(create_app(args.tsp, args.ffmpeg, args.tshides), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
