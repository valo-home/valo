"""Служба видео: go2rtc как единая точка подключения к камерам, буфер последних секунд и клипы по событиям."""

import asyncio
import contextlib
import json
import os
import pathlib
import shutil
import socket
import struct
import time
import uuid
from datetime import datetime
from typing import Any

import httpx

from app.db.base import commit, session
from app.domain import cameras, media
from app.lib import log, rtc
from app.lib.kv import beat, kv, set_json
from app.lib.loops import forever
from app.lib.settings import env, settings
from app.lib.timeutil import zone

GO2RTC = env("GO2RTC_BIN", "/usr/local/bin/go2rtc")
FFMPEG = env("FFMPEG_BIN", "/usr/local/bin/ffmpeg")
BUFFER = pathlib.Path(env("CAMERAS_BUFFER", "/buffer"))
CONFIG = pathlib.Path(env("GO2RTC_CONFIG", "/tmp/go2rtc.json"))
SEG = 2
IDLE_KEEP = 40
PIECE = 600
NO_VIDEO_AFTER = 30
HEAL_AFTER = 180
HEAL_EVERY = 900
NTP_PORT = int(env("NTP_PORT", "0") or 0)
NTP_EPOCH = 2208988800
DEMO_PATTERNS = {"demo-yard": "testsrc2", "demo-door": "smptehdbars"}
_log = log.get("cameras_proc")


def demo_source(pattern: str) -> str:
    return (
        f"exec:{FFMPEG} -hide_banner -loglevel error -re -f lavfi -i {pattern}=size=1280x720:rate=10 "
        "-f lavfi -i sine=frequency=330:sample_rate=48000 -vf format=yuv420p -c:v libx264 -preset ultrafast "
        "-tune zerolatency -g 20 -c:a aac -b:a 48k -f rtsp {output}"
    )


def config() -> dict[str, Any]:
    streams = {name: demo_source(p) for name, p in DEMO_PATTERNS.items()} if settings.demo else {}
    return {
        "api": {"listen": f":{rtc.API_PORT}", "base_path": rtc.BASE, "username": rtc.USER, "password": rtc.password()},
        "rtsp": {"listen": f":{rtc.RTSP_PORT}", "username": rtc.USER, "password": rtc.password()},
        "webrtc": {"listen": ""},
        "srtp": {"listen": ""},
        "ffmpeg": {"bin": FFMPEG},
        "log": {"level": "warn", "format": "text"},
        "streams": streams,
    }


class Recorder:
    """Непрерывная запись потока кусками по SEG секунд во временную папку. Хранится только хвост."""

    def __init__(self, cid: str, name: str = "", audio: bool = True) -> None:
        self.cid = cid
        self.name = name or cid
        self.audio = audio
        self.dir = BUFFER / cid
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.error = ""
        self.since = time.time()

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                _log.error("buffer_stop_failed", camera=self.cid, error=str(e))
        self.task = None
        shutil.rmtree(self.dir, ignore_errors=True)

    async def _run(self) -> None:
        delay = 3.0
        while True:
            self.dir.mkdir(parents=True, exist_ok=True)
            started = time.monotonic()
            cmd = [
                FFMPEG,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                mp4_source(self.name),
                *tracks(self.audio),
                "-c",
                "copy",
                "-f",
                "segment",
                "-segment_time",
                str(SEG),
                "-reset_timestamps",
                "1",
                "-strftime",
                "1",
                str(self.dir / "%s.ts"),
            ]
            try:
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
                )
                _log.info("buffer_started", camera=self.cid, pid=self.proc.pid)
                _, err = await self.proc.communicate()
                self.error = rtc.mask(err.decode(errors="replace").strip()[-300:]) or f"exit {self.proc.returncode}"
                _log.warning("buffer_exited", camera=self.cid, code=self.proc.returncode, error=self.error)
            except asyncio.CancelledError:
                if self.proc and self.proc.returncode is None:
                    self.proc.terminate()
                    try:
                        await asyncio.wait_for(self.proc.wait(), 5)
                    except TimeoutError:
                        _log.warning("buffer_kill", camera=self.cid, pid=self.proc.pid)
                        self.proc.kill()
                raise
            except Exception as e:
                self.error = rtc.mask(str(e))
                _log.error("buffer_failed", camera=self.cid, error=self.error, exc_info=True)
            if time.monotonic() - started > 60:
                delay = 3.0
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)

    def segments(self) -> list[tuple[float, float, pathlib.Path]]:
        out = []
        for f in self.dir.glob("*.ts"):
            try:
                st = f.stat()
                out.append((float(f.stem), st.st_mtime, f))
            except ValueError, OSError:
                continue
        return sorted(out)

    def prune(self, keep_from: float) -> None:
        segs = self.segments()
        for _start, end, f in segs[:-1]:
            if end < keep_from:
                f.unlink(missing_ok=True)

    def age(self) -> float | None:
        segs = self.segments()
        return round(time.time() - segs[-1][1], 1) if segs else None


def mp4_source(name: str) -> str:
    """Поток через выход MP4 самого go2rtc: звук и видео приходят уже согласованными по времени.
    Прямое чтение RTSP со звуком в ffmpeg задерживает куски буфера на 10 секунд."""
    return rtc.api(f"/api/stream.mp4?src={name}&mp4=aac", local=True)


def tracks(audio: bool) -> list[str]:
    return ["-map", "0:v:0", "-map", "0:a:0?"] if audio else ["-map", "0:v:0", "-an"]


def piece_start(name: str, tz: str) -> datetime | None:
    try:
        return datetime.strptime(name.removeprefix("rec-").removesuffix(".mp4"), "%Y%m%d-%H%M%S").replace(
            tzinfo=zone(tz)
        )
    except ValueError:
        return None


class Continuous:
    """Постоянная запись в папку записей кусками по PIECE секунд по границам часов. Каждый законченный кусок
    учитывается в хранилище как запись camera continuous."""

    def __init__(self, svc: Service, cid: str, name: str, audio: bool) -> None:
        self.svc = svc
        self.cid = cid
        self.name = name
        self.audio = audio
        self.task: asyncio.Task | None = None
        self.proc: asyncio.subprocess.Process | None = None
        self.error = ""
        self.last = time.time()
        self.key = (name, audio)

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.ensure_future(self._run())

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
        self.task = None

    def running(self) -> bool:
        return self.task is not None and not self.task.done() and self.proc is not None and self.proc.returncode is None

    async def _run(self) -> None:
        delay = 5.0
        while True:
            base, tz = self.svc.media_dir, self.svc.tz
            started = time.monotonic()
            try:
                self.svc.day_dirs(self.cid)
                await self.svc.adopt(self.cid)
                cmd = [
                    FFMPEG,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-i",
                    mp4_source(self.name),
                    *tracks(self.audio),
                    "-c",
                    "copy",
                    "-f",
                    "segment",
                    "-segment_time",
                    str(PIECE),
                    "-segment_atclocktime",
                    "1",
                    "-segment_format",
                    "mp4",
                    "-segment_format_options",
                    "movflags=+frag_keyframe+empty_moov+default_base_moof",
                    "-reset_timestamps",
                    "1",
                    "-strftime",
                    "1",
                    "-segment_list",
                    "pipe:1",
                    "-segment_list_type",
                    "csv",
                    str(base / self.cid / "%Y-%m-%d" / "rec-%Y%m%d-%H%M%S.mp4"),
                ]
                self.proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, "TZ": tz},
                )
                _log.info("continuous_started", camera=self.cid, pid=self.proc.pid)
                if self.proc.stdout is None:
                    raise RuntimeError("ffmpeg output pipe is missing")
                while line := await self.proc.stdout.readline():
                    await self.piece(base, tz, line.decode(errors="replace").strip())
                err = await self.proc.stderr.read() if self.proc.stderr else b""
                await self.proc.wait()
                self.error = rtc.mask(err.decode(errors="replace").strip()[-300:]) or f"exit {self.proc.returncode}"
                _log.warning("continuous_exited", camera=self.cid, code=self.proc.returncode, error=self.error)
            except asyncio.CancelledError:
                if self.proc and self.proc.returncode is None:
                    self.proc.terminate()
                    try:
                        await asyncio.wait_for(self.proc.wait(), 10)
                    except TimeoutError:
                        self.proc.kill()
                await self.svc.adopt(self.cid)
                raise
            except Exception as e:
                self.error = rtc.mask(str(e))
                _log.error("continuous_failed", camera=self.cid, error=self.error, exc_info=True)
            await self.svc.adopt(self.cid)
            if time.monotonic() - started > 120:
                delay = 5.0
            await asyncio.sleep(delay)
            delay = min(delay * 2, 120.0)

    async def piece(self, base: pathlib.Path, tz: str, line: str) -> None:
        name, _, rest = line.partition(",")
        parts = rest.split(",")
        when = piece_start(pathlib.Path(name).name, tz)
        if when is None:
            _log.warning("continuous_piece_unknown", camera=self.cid, line=line[:120])
            return
        f = base / self.cid / when.strftime("%Y-%m-%d") / pathlib.Path(name).name
        try:
            duration = round(float(parts[1]) - float(parts[0]), 1) if len(parts) >= 2 else None
        except ValueError:
            duration = None
        if not f.is_file():
            _log.warning("continuous_piece_missing", camera=self.cid, file=str(f))
            return
        self.last = time.time()
        await faststart(f)
        async with session() as s:
            await media.register(s, self.cid, f, media.CONTINUOUS, duration, when, {"continuous": True})
            await commit(s)


async def faststart(f: pathlib.Path) -> bool:
    """Перепаковать законченный кусок из фрагментированного MP4 в обычный с индексом в начале для быстрой
    перемотки в браузере. Фрагментированный кусок остается читаемым и после обрыва записи, если перепаковка
    не удалась, он сохраняется как есть."""
    tmp = f.with_name(f".{f.stem}.tmp.mp4")
    p = await asyncio.create_subprocess_exec(
        FFMPEG,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(f),
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, err = await asyncio.wait_for(p.communicate(), 300)
    except TimeoutError:
        p.kill()
        err = b"timeout"
    if p.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        _log.warning("continuous_faststart_failed", file=f.name, error=err.decode(errors="replace")[-200:])
        return False
    tmp.replace(f)
    return True


class Service:
    def __init__(self) -> None:
        self.go2rtc: asyncio.subprocess.Process | None = None
        self.applied: dict[str, str] = {}
        self.cams: dict[str, dict[str, Any]] = {}
        self.recorders: dict[str, Recorder] = {}
        self.open: dict[int, dict[str, Any]] = {}
        self.holds: dict[str, tuple[str, float]] = {}
        self.ready = asyncio.Event()
        self.tasks: set[asyncio.Task] = set()
        self.continuous: dict[str, Continuous] = {}
        self.tz = "UTC"
        self.media_dir = media.root()
        self.low = False
        self.seen: dict[str, tuple[float, int, float]] = {}
        self.vstate: dict[str, tuple[str, float]] = {}
        self.healed: dict[str, float] = {}

    def spawn(self, coro: Any) -> None:
        t = asyncio.ensure_future(coro)
        self.tasks.add(t)
        t.add_done_callback(self._done)

    def _done(self, t: asyncio.Task) -> None:
        self.tasks.discard(t)
        if not t.cancelled() and t.exception() is not None:
            e = t.exception()
            _log.error("task_failed", task=t.get_coro().__name__, error=rtc.mask(str(e)), exc_info=e)

    async def run_go2rtc(self) -> None:
        CONFIG.write_text(json.dumps(config()))
        CONFIG.chmod(0o600)
        self.applied = {}
        self.go2rtc = proc = await asyncio.create_subprocess_exec(GO2RTC, "-config", str(CONFIG))
        _log.info("go2rtc_started", pid=proc.pid)
        try:
            for _ in range(50):
                with contextlib.suppress(httpx.HTTPError):
                    async with httpx.AsyncClient(timeout=2) as c:
                        if (await c.get(rtc.api("/api", local=True))).status_code < 500:
                            break
                if proc.returncode is not None:
                    break
                await asyncio.sleep(0.2)
            else:
                _log.error("go2rtc_not_answering", pid=proc.pid)
            if proc.returncode is None:
                self.ready.set()
                await self.sync()
            code = await proc.wait()
            _log.error("go2rtc_exited", code=code)
        finally:
            self.ready.clear()
            if proc.returncode is None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()

    async def sync(self) -> None:
        if not self.ready.is_set():
            return
        async with session() as s:
            self.cams = await cameras.sources(s)
            self.tz = await cameras.timezone(s)
            self.media_dir = await media.directory(s)
        wanted: dict[str, str] = {}
        for cid, c in self.cams.items():
            wanted[rtc.stream(cid)] = c["main"]
            if c.get("sub"):
                wanted[rtc.stream(cid, sub=True)] = c["sub"]
        async with httpx.AsyncClient(timeout=5) as cl:
            for name, url in wanted.items():
                if self.applied.get(name) == url:
                    continue
                r = await cl.patch(rtc.api("/api/streams", local=True), params={"name": name, "src": url})
                if r.status_code >= 400:
                    r = await cl.put(rtc.api("/api/streams", local=True), params={"name": name, "src": url})
                if r.status_code < 400:
                    self.applied[name] = url
                    _log.info("stream_set", name=name, src=rtc.mask(url))
                else:
                    _log.error("stream_set_failed", name=name, status=r.status_code, body=r.text[:200])
            for name in [n for n in self.applied if n not in wanted]:
                r = await cl.delete(rtc.api("/api/streams", local=True), params={"src": name})
                if r.status_code < 400:
                    self.applied.pop(name, None)
                    _log.info("stream_removed", name=name)
                else:
                    _log.error("stream_remove_failed", name=name, status=r.status_code)
        for cid, c in self.cams.items():
            rec = c["record"]
            if rec["mode"] == "off":
                continue
            name = self.record_stream(cid)
            cur = self.recorders.get(cid)
            if cur is not None and (cur.name, cur.audio) != (name, rec["audio"]):
                await self.recorders.pop(cid).stop()
            self.recorders.setdefault(cid, Recorder(cid, name, rec["audio"])).start()
        for cid in [c for c in self.recorders if c not in self.cams or self.cams[c]["record"]["mode"] == "off"]:
            await self.recorders.pop(cid).stop()
        await self.sync_continuous()

    def record_stream(self, cid: str) -> str:
        c = self.cams[cid]
        return rtc.stream(cid, sub=c["record"]["stream"] == "sub" and bool(c.get("sub")))

    def wanted_continuous(self, cid: str) -> bool:
        c = self.cams.get(cid)
        if c is None or c["record"]["mode"] != "continuous" or self.low:
            return False
        return cameras.scheduled(c["record"], datetime.now(zone(self.tz)))

    async def sync_continuous(self) -> None:
        for cid in list(self.cams):
            want = self.wanted_continuous(cid)
            cur = self.continuous.get(cid)
            key = (self.record_stream(cid), self.cams[cid]["record"]["audio"])
            if cur is not None and (not want or cur.key != key):
                await self.continuous.pop(cid).stop()
                cur = None
            if want and cur is None:
                self.continuous[cid] = Continuous(self, cid, *key)
                self.continuous[cid].start()
        for cid in [c for c in self.continuous if c not in self.cams]:
            await self.continuous.pop(cid).stop()

    def day_dirs(self, cid: str) -> None:
        now = time.time()
        for off in (0, 3600 * 6):
            day = datetime.fromtimestamp(now + off, zone(self.tz)).strftime("%Y-%m-%d")
            (self.media_dir / cid / day).mkdir(parents=True, exist_ok=True)

    async def adopt(self, cid: str) -> None:
        """Учесть куски постоянной записи, которые ffmpeg закончил, но не успел сообщить. Недописанные удаляются."""
        root = self.media_dir / cid
        if not root.is_dir():
            return
        for day in sorted(root.iterdir())[-2:]:
            for f in sorted(day.glob("rec-*.mp4")):
                cont = self.continuous.get(cid)
                if cont is not None and cont.running() and time.time() - f.stat().st_mtime < 30:
                    continue
                when = piece_start(f.name, self.tz)
                if when is None:
                    continue
                async with session() as s:
                    known = await media.known(s, f)
                if known:
                    continue
                await faststart(f)
                dur = await self.duration(f)
                if dur is None:
                    _log.warning("continuous_piece_broken", camera=cid, file=f.name, size=f.stat().st_size)
                    f.unlink(missing_ok=True)
                    continue
                async with session() as s:
                    if await media.register(s, cid, f, media.CONTINUOUS, dur, when, {"continuous": True}):
                        _log.info("continuous_piece_adopted", camera=cid, file=f.name)
                    await commit(s)

    async def duration(self, f: pathlib.Path) -> float | None:
        p = await asyncio.create_subprocess_exec(
            env("FFPROBE_BIN", "/usr/local/bin/ffprobe"),
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(f),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await p.communicate()
        try:
            return round(float(out.decode().strip()), 1)
        except ValueError:
            return None

    async def snapshot(self, cid: str, eid: int | None, label: str, origin: str) -> None:
        try:
            async with session() as s:
                m = await cameras.capture(s, cid, origin, event_id=eid, label=label, local=True)
                if eid is not None:
                    await cameras.attach(s, eid, snapshot_id=m.id)
                await commit(s)
        except Exception as e:
            _log.warning("event_snapshot_failed", camera=cid, event_id=eid, error=rtc.mask(str(e)))

    async def cut(self, cid: str, t0: float, t1: float) -> tuple[pathlib.Path, float] | None:
        rec = self.recorders.get(cid)
        if rec is None:
            return None
        segs = [x for x in rec.segments() if x[1] > t0 and x[0] < t1]
        if not segs:
            _log.warning("clip_no_segments", camera=cid, t0=round(t0), t1=round(t1))
            return None
        work = BUFFER / f".clip-{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        lst = work / "list.txt"
        lst.write_text("".join(f"file '{f}'\n" for _, _, f in segs))
        out = work / "clip.mp4"
        p = await asyncio.create_subprocess_exec(
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(lst),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(p.communicate(), 120)
        except TimeoutError:
            p.kill()
            err = b"timeout"
        if p.returncode != 0 or not out.exists():
            _log.error("clip_failed", camera=cid, error=err.decode(errors="replace")[-300:])
            shutil.rmtree(work, ignore_errors=True)
            return None
        return out, segs[-1][1] - segs[0][0]

    async def record_direct(self, cid: str, seconds: int) -> tuple[pathlib.Path, float] | None:
        work = BUFFER / f".clip-{uuid.uuid4().hex[:8]}"
        work.mkdir(parents=True, exist_ok=True)
        out = work / "clip.mp4"
        p = await asyncio.create_subprocess_exec(
            FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            mp4_source(self.record_stream(cid) if cid in self.cams else rtc.stream(cid)),
            "-t",
            str(seconds),
            *tracks(bool(self.cams.get(cid, {}).get("record", {}).get("audio", True))),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(out),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            _, err = await asyncio.wait_for(p.communicate(), seconds + 30)
        except TimeoutError:
            p.kill()
            err = b"timeout"
        if p.returncode != 0 or not out.exists():
            _log.error("direct_clip_failed", camera=cid, error=rtc.mask(err.decode(errors="replace")[-300:]))
            shutil.rmtree(work, ignore_errors=True)
            return None
        return out, float(seconds)

    async def finalize(
        self,
        cid: str,
        eid: int | None,
        t0: float,
        t1: float,
        label: str,
        origin: str,
        direct: int = 0,
        exact: bool = False,
    ) -> None:
        cam = self.cams.get(cid)
        if cam is None:
            return
        rec = cam["record"]
        hold = uuid.uuid4().hex
        if not direct:
            if rec["mode"] == "off" or cid not in self.recorders:
                return
            if not cameras.wants_label(rec, label):
                _log.info("clip_skipped_label", camera=cid, event_id=eid, label=label)
                return
            if not exact and not cameras.scheduled(rec, datetime.fromtimestamp(t0, zone(self.tz))):
                _log.info("clip_skipped_schedule", camera=cid, event_id=eid)
                return
            if not exact:
                t0 -= rec["pre"]
                t1 = min(t1, t0 + rec["pre"] + rec["max"]) + rec["post"]
            self.holds[hold] = (cid, t0)
            wait = t1 + SEG + 1 - time.time()
            if wait > 0:
                await asyncio.sleep(wait)
        try:
            await self._finish(cid, eid, t0, t1, label, origin, direct)
        finally:
            self.holds.pop(hold, None)

    async def _finish(
        self, cid: str, eid: int | None, t0: float, t1: float, label: str, origin: str, direct: int
    ) -> None:
        async with session() as s:
            state = await media.rotate(s)
            await commit(s)
        if state["low"]:
            _log.warning("clip_skipped_low_space", camera=cid, event_id=eid, free=state["free"])
            return
        res = await (self.record_direct(cid, direct) if direct else self.cut(cid, t0, t1))
        if res is None:
            return
        path, duration = res
        try:
            async with session() as s:
                m = await media.save(
                    s, cid, "video", path, origin, event_id=eid, duration=round(duration, 1), label=label
                )
                if eid is not None:
                    await cameras.attach(s, eid, clip_id=m.id)
                await commit(s)
            _log.info("clip_saved", camera=cid, event_id=eid, seconds=round(duration, 1))
        except Exception as e:
            _log.error("clip_not_saved", camera=cid, event_id=eid, error=str(e), exc_info=True)
        finally:
            shutil.rmtree(path.parent, ignore_errors=True)

    async def on_event(self, msg: dict[str, Any]) -> None:
        cid, eid, label, phase = msg.get("camera"), msg.get("event"), msg.get("label", "motion"), msg.get("phase")
        if not isinstance(cid, str) or not isinstance(eid, int):
            return
        at = float(msg.get("at") or time.time())
        if phase in ("start", "once"):
            if not str(msg.get("source") or "").startswith("ext:"):
                if self.cams.get(cid, {}).get("record", {}).get("snapshots", True):
                    self.spawn(self.snapshot(cid, eid, label, "event"))
                else:
                    _log.info("event_snapshot_off", camera=cid, event_id=eid)
            if phase == "once":
                self.spawn(self.finalize(cid, eid, at, at, label, "event"))
            else:
                self.open[eid] = {"cam": cid, "t0": at, "label": label}
        elif phase == "end":
            ev = self.open.pop(eid, None)
            if ev is not None:
                self.spawn(self.finalize(cid, eid, ev["t0"], at, label, "event"))

    async def on_job(self, msg: dict[str, Any]) -> None:
        cid = msg.get("camera")
        if not isinstance(cid, str) or cid not in self.cams:
            return
        seconds = int(msg.get("seconds") or 15)
        origin = str(msg.get("origin") or "flow")
        at = float(msg.get("at") or time.time())
        if self.cams[cid]["record"]["mode"] != "off" and cid in self.recorders:
            await self.finalize(cid, None, at, at + seconds, "clip", origin, exact=True)
        else:
            await self.finalize(cid, None, at, at + seconds, "clip", origin, direct=seconds)

    async def listen(self) -> None:
        ps = kv().pubsub()
        await ps.subscribe(cameras.CHANGED, cameras.EVENTS, cameras.JOBS)
        async for m in ps.listen():
            if m.get("type") != "message":
                continue
            ch = m.get("channel")
            try:
                if ch == cameras.CHANGED:
                    data = str(m.get("data") or "")
                    if data.startswith("reset:"):
                        await self.reset(data[6:])
                    await asyncio.sleep(0.3)
                    await self.sync()
                    continue
                body = json.loads(m.get("data") or "{}")
                if ch == cameras.EVENTS:
                    await self.on_event(body)
                elif ch == cameras.JOBS:
                    self.spawn(self.on_job(body))
            except Exception as e:
                _log.error("message_failed", channel=ch, error=str(e), exc_info=True)

    async def reset(self, cid: str) -> None:
        """Переподключить камеру в Valo: убрать потоки из go2rtc и перезапустить запись."""
        async with httpx.AsyncClient(timeout=5) as cl:
            for name in (rtc.stream(cid), rtc.stream(cid, sub=True)):
                if name in self.applied:
                    await cl.delete(rtc.api("/api/streams", local=True), params={"src": name})
                    self.applied.pop(name, None)
        for group in (self.recorders, self.continuous):
            if cid in group:
                await group.pop(cid).stop()
        self.seen.pop(cid, None)
        _log.info("camera_reset", camera=cid)

    async def video_state(self) -> None:
        """Состояние видео каждой камеры для интерфейса: битрейт, кодеки, возраст буфера и ошибки."""
        async with httpx.AsyncClient(timeout=4) as cl:
            for cid in list(self.cams):
                name = rtc.stream(cid)
                kbps, codecs, recv = None, [], None
                try:
                    r = await cl.get(rtc.api("/api/streams", local=True), params={"src": name})
                    body = r.json() if r.status_code == 200 else {}
                    prods = body.get("producers") or [] if isinstance(body, dict) else []
                    recv = sum(int(p.get("bytes_recv") or 0) for p in prods)
                    codecs = sorted(
                        {
                            str(rc["codec"].get("codec_name"))
                            for p in prods
                            for rc in p.get("receivers") or []
                            if isinstance(rc.get("codec"), dict)
                        }
                    )
                except (httpx.HTTPError, ValueError) as e:
                    _log.warning("video_state_failed", camera=cid, error=str(e))
                now = time.time()
                prev = self.seen.get(cid)
                if recv is not None:
                    if prev and recv > prev[1]:
                        kbps = round((recv - prev[1]) * 8 / 1000 / max(now - prev[0], 1))
                        self.seen[cid] = (now, recv, now)
                    elif prev and recv >= prev[1]:
                        kbps = 0
                        self.seen[cid] = (now, recv, prev[2])
                    else:
                        self.seen[cid] = (now, recv, now)
                rec = self.recorders.get(cid)
                age = rec.age() if rec else None
                last_data = self.seen.get(cid, (now, 0, now))[2]
                state = "idle"
                if rec is not None:
                    stalled = now - last_data > NO_VIDEO_AFTER or age is None or age > NO_VIDEO_AFTER
                    state = "no_video" if stalled and now - rec.since > NO_VIDEO_AFTER else "ok"
                old = self.vstate.get(cid)
                if old is None or old[0] != state:
                    self.vstate[cid] = (state, now)
                    if state == "no_video":
                        _log.warning("camera_no_video", camera=cid, buffer_age=age, error=rec.error if rec else "")
                if state == "no_video" and self.due_heal(cid, now):
                    self.healed[cid] = now
                    self.spawn(self.heal(cid))
                cont = self.continuous.get(cid)
                await set_json(
                    cameras.VIDEO + cid,
                    {
                        "state": state,
                        "since": datetime.fromtimestamp(self.vstate[cid][1]).astimezone().isoformat(),
                        "kbps": kbps,
                        "codecs": codecs,
                        "buffer_age": age,
                        "error": rec.error if rec else "",
                        "continuous": bool(cont and cont.running()),
                        "continuous_age": round(now - cont.last) if cont else None,
                        "continuous_error": cont.error if cont else "",
                        "at": datetime.now().astimezone().isoformat(),
                    },
                    ttl=60,
                )

    def due_heal(self, cid: str, now: float) -> bool:
        return now - self.vstate[cid][1] >= HEAL_AFTER and now - self.healed.get(cid, 0.0) >= HEAL_EVERY

    async def heal(self, cid: str) -> None:
        async with session() as s:
            how = await cameras.heal(s, cid)
            await commit(s)
        if how in ("skipped", "missing"):
            self.healed[cid] = time.time() - HEAL_EVERY + 60

    async def housekeeping(self) -> None:
        while True:
            await beat("cameras", 30)
            await self.sync()
            await self.video_state()
            for cid in self.continuous:
                self.day_dirs(cid)
            for cid, rec in list(self.recorders.items()):
                keep = time.time() - IDLE_KEEP
                for ev in self.open.values():
                    if ev["cam"] == cid:
                        keep = min(keep, ev["t0"] - self.cams.get(cid, {}).get("record", {}).get("pre", 5) - SEG)
                for hcid, t0 in self.holds.values():
                    if hcid == cid:
                        keep = min(keep, t0 - SEG)
                rec.prune(keep)
                limit = time.time() - self.cams.get(cid, {}).get("record", {}).get("max", 120) - 60
                for eid, ev in list(self.open.items()):
                    if ev["cam"] == cid and ev["t0"] < limit:
                        self.open.pop(eid, None)
                        self.spawn(self.finalize(cid, eid, ev["t0"], time.time(), ev["label"], "event"))
            await asyncio.sleep(10)

    async def rotation(self) -> None:
        while True:
            async with session() as s:
                state = await media.rotate(s)
                stale = await cameras.close_stale(s)
                await cameras.watch_offline(s)
                await commit(s)
                await cameras.keep_time(s)
            if state["low"] != self.low:
                self.low = state["low"]
                await self.sync_continuous()
            if state["low"]:
                _log.warning("media_low_space", free=state["free"])
            if stale:
                _log.info("stale_events_closed", n=stale)
            await asyncio.sleep(60)

    async def main(self) -> None:
        BUFFER.mkdir(parents=True, exist_ok=True)
        for old in BUFFER.glob(".clip-*"):
            shutil.rmtree(old, ignore_errors=True)
        jobs = [
            forever("go2rtc", self.run_go2rtc, _log),
            forever("cameras_listen", self.listen, _log),
            forever("cameras_housekeeping", self.housekeeping, _log),
            forever("media_rotation", self.rotation, _log),
        ]
        if NTP_PORT:
            jobs.append(forever("ntp", ntp_serve, _log))
        await asyncio.gather(*jobs)


def ntp_reply(req: bytes, received: float, now: float) -> bytes | None:
    """Ответ SNTP (RFC 4330) по часам узла Valo для камер без интернета."""
    if len(req) < 48 or req[0] & 0x07 != 3:
        return None
    version = (req[0] >> 3) & 0x07

    def ts(t: float) -> bytes:
        sec = int(t) + NTP_EPOCH
        return struct.pack("!II", sec & 0xFFFFFFFF, int((t % 1) * 2**32) & 0xFFFFFFFF)

    head = struct.pack("!BBbb", (version << 3) | 4, 3, req[2], -20)
    return head + struct.pack("!II", 0, 1 << 12) + b"VALO" + ts(now) + req[40:48] + ts(received) + ts(time.time())


class _Ntp(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.t = transport

    def datagram_received(self, data: bytes, addr: Any) -> None:
        got = time.time()
        out = ntp_reply(data, got, got)
        if out is not None and isinstance(self.t, asyncio.DatagramTransport):
            self.t.sendto(out, addr)


async def ntp_serve() -> None:
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(_Ntp, local_addr=("0.0.0.0", NTP_PORT), family=socket.AF_INET)
    _log.info("ntp_started", port=NTP_PORT)
    try:
        await asyncio.Event().wait()
    finally:
        transport.close()


def run() -> None:
    log.setup("cameras")
    _log.info("cameras_start", buffer=str(BUFFER), media=str(media.root()), pid=os.getpid())
    asyncio.run(Service().main())


if __name__ == "__main__":
    run()
