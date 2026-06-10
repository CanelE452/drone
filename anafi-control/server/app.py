import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
from drone.interface import AnafiController


def make_controller() -> AnafiController:
    if config.CONTROLLER == "real":
        from drone.real import RealController
        return RealController(config.DRONE_IP)
    from drone.mock import MockController
    return MockController(config.DRONE_IP)


controller = make_controller()
command_queue: "asyncio.Queue[dict]" = asyncio.Queue()
clients: set[WebSocket] = set()
busy = False           # 이동 명령 실행 중 (UI 버튼 비활성화 신호)
last_error = ""        # 마지막 거부 사유 (안전 가드 위반 등)


# ---------- 안전 가드 ----------
def guard_move(forward_cm, right_cm, up_cm, yaw_deg) -> str | None:
    """이동 명령 사전 검사. 위반 시 사유 문자열, 통과 시 None."""
    t = controller.get_telemetry()
    if t.battery_pct < config.MIN_BATTERY_PCT:
        return f"배터리 {t.battery_pct}% < {config.MIN_BATTERY_PCT}% — 이동 거부, 착륙 권장"
    for axis, v in (("forward", forward_cm), ("right", right_cm), ("up", up_cm)):
        if v != 0 and abs(v) < config.MIN_STEP_CM:
            return f"{axis} {v}cm < 최소 {config.MIN_STEP_CM}cm (데드밴드) — 거부"
        if abs(v) > config.MAX_STEP_CM:
            return f"{axis} {v}cm > 최대 {config.MAX_STEP_CM}cm — 거부"
    if t.altitude_m + up_cm / 100.0 > config.MAX_ALTITUDE_M:
        return f"목표 고도 {t.altitude_m + up_cm/100.0:.2f}m > 한계 {config.MAX_ALTITUDE_M}m — 거부"
    return None


# ---------- 명령 실행 (블로킹 — executor에서 호출) ----------
def execute_command(cmd: dict):
    kind = cmd.get("cmd")
    if kind == "takeoff":
        return controller.takeoff()
    if kind == "land":
        return controller.land()
    if kind == "move":
        return controller.move_cm(
            forward_cm=cmd.get("forward_cm", 0),
            right_cm=cmd.get("right_cm", 0),
            up_cm=cmd.get("up_cm", 0),
            yaw_deg=cmd.get("yaw_deg", 0),
        )
    if kind == "goto_altitude":
        return controller.go_to_altitude(cmd.get("target_m", 1.0))
    if kind == "return_home":
        return controller.return_home_initial()
    return False


# ---------- 명령 워커 (직렬화) ----------
async def command_worker():
    global busy, last_error
    loop = asyncio.get_event_loop()
    while True:
        cmd = await command_queue.get()
        # move 계열은 안전 가드 통과해야 실행
        if cmd.get("cmd") == "move":
            reason = guard_move(
                cmd.get("forward_cm", 0), cmd.get("right_cm", 0),
                cmd.get("up_cm", 0), cmd.get("yaw_deg", 0),
            )
            if reason:
                last_error = reason
                command_queue.task_done()
                await broadcast()
                continue
        busy = True
        last_error = ""
        await broadcast()
        try:
            ok = await loop.run_in_executor(None, execute_command, cmd)
            if not ok:
                last_error = f"명령 실패: {cmd.get('cmd')}"
        except Exception as e:
            last_error = f"예외: {e}"
        finally:
            busy = False
            command_queue.task_done()
            await broadcast()


# ---------- broadcast ----------
async def broadcast():
    t = controller.get_telemetry().to_dict()
    payload = json.dumps({
        "telemetry": t,
        "busy": busy,
        "queued": command_queue.qsize(),
        "error": last_error,
        "controller": config.CONTROLLER,
    })
    dead = []
    for ws in clients:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def telemetry_loop():
    period = 1.0 / config.TELEMETRY_HZ
    while True:
        await broadcast()
        await asyncio.sleep(period)


@asynccontextmanager
async def lifespan(app: FastAPI):
    controller.connect()
    worker = asyncio.create_task(command_worker())
    telem = asyncio.create_task(telemetry_loop())
    yield
    worker.cancel()
    telem.cancel()
    controller.disconnect()


app = FastAPI(lifespan=lifespan)


@app.get("/")
async def index():
    return FileResponse("server/static/index.html")


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await broadcast()
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("cmd")
            # 안전 정지는 큐를 거치지 않고 즉시 실행
            if kind == "emergency":
                controller.emergency_cutoff()
                await broadcast()
            elif kind == "land_now":
                # 긴급 착륙: 대기 중인 명령 비우고 즉시 착륙
                _drain_queue()
                await asyncio.get_event_loop().run_in_executor(None, controller.land)
                await broadcast()
            else:
                await command_queue.put(msg)
    except WebSocketDisconnect:
        clients.discard(ws)
    except Exception:
        clients.discard(ws)


def _drain_queue():
    while not command_queue.empty():
        try:
            command_queue.get_nowait()
            command_queue.task_done()
        except Exception:
            break


app.mount("/static", StaticFiles(directory="server/static"), name="static")
