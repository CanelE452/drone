#!/usr/bin/env python3
"""
Safe Parrot ANAFI Ai connection check — Phase 5.0 지상 게이트 구현체.

연결만 하고 수동 상태를 읽어 보고한 뒤 끊는다. takeoff/landing/piloting/
mission/flight-plan/camera 등 어떤 비행 명령도 절대 보내지 않는다.
실기체를 처음 컴퓨터에 붙이는 날, 이륙 없이 연결 계층 버그를 잡는 용도.

실행 (드론은 책상 위, 프로펠러 제거 권장):
    conda activate olympe
    python scripts/connection_check.py --controller direct          # 192.168.42.1
    python scripts/connection_check.py --controller skycontroller4  # 192.168.53.1

출처: j/ (타인 작성). 사용 API(AnafiAi/query_state/connect)는 olympe 8.4.0 존재 확인 완료.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Any


DEFAULT_DIRECT_IP = "192.168.42.1"
DEFAULT_SKYCTRL4_IP = "192.168.53.1"
MIN_OLYMPE_CONNECTION_TIMEOUT = 45.0
DEFAULT_OLYMPE_RUNTIME_DIR = ".olympe_runtime"


class SafetyError(RuntimeError):
    """Raised when the script is asked to do something outside check-only mode."""


@dataclass(frozen=True)
class ConnectionConfig:
    ip: str
    controller: str
    timeout: float
    retry: int


def parse_args() -> ConnectionConfig:
    parser = argparse.ArgumentParser(
        description="Connect to a Parrot ANAFI Ai and verify the connection without flying."
    )
    parser.add_argument(
        "--controller",
        choices=("direct", "skycontroller4"),
        default=os.getenv("ANAFI_AI_CONTROLLER", "direct"),
        help="Use direct ANAFI Ai connection mode or SkyController 4.",
    )
    parser.add_argument(
        "--ip",
        default=os.getenv("ANAFI_AI_IP"),
        help=(
            "Drone/controller IP address. Defaults to 192.168.42.1 for direct "
            "or 192.168.53.1 for SkyController 4."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("ANAFI_AI_TIMEOUT", str(MIN_OLYMPE_CONNECTION_TIMEOUT))),
        help="Total connection timeout in seconds. Olympe requires at least 45 seconds.",
    )
    parser.add_argument(
        "--retry",
        type=int,
        default=int(os.getenv("ANAFI_AI_RETRY", "1")),
        help="Number of connection attempts.",
    )
    args = parser.parse_args()

    if args.timeout < MIN_OLYMPE_CONNECTION_TIMEOUT:
        raise SafetyError("--timeout must be at least 45 seconds for Olympe.")
    if args.retry < 1:
        raise SafetyError("--retry must be at least 1.")

    default_ip = DEFAULT_DIRECT_IP if args.controller == "direct" else DEFAULT_SKYCTRL4_IP
    return ConnectionConfig(
        ip=args.ip or default_ip,
        controller=args.controller,
        timeout=args.timeout,
        retry=args.retry,
    )


def import_controller_class(controller: str) -> type[Any]:
    try:
        import olympe
    except ImportError as exc:
        raise RuntimeError(
            "Unable to import the Olympe SDK from this Python environment. "
            f"python={sys.executable!r}; import_error={exc!r}. "
            "Install/activate Parrot Olympe in this exact environment."
        ) from exc

    class_names = (
        ("AnafiAi", "Drone")
        if controller == "direct"
        else ("SkyController4", "SkyController")
    )
    for class_name in class_names:
        controller_class = getattr(olympe, class_name, None)
        if controller_class is not None:
            return controller_class

    raise RuntimeError(
        "The Olympe SDK is importable, but this version does not expose any "
        f"supported {controller!r} controller class. Tried: "
        f"{', '.join(f'olympe.{name}' for name in class_names)}."
    )


def configure_olympe_runtime_dirs() -> None:
    runtime_root = os.getenv("OLYMPE_RUNTIME_ROOT", DEFAULT_OLYMPE_RUNTIME_DIR)
    data_home = os.path.abspath(os.path.join(runtime_root, "share"))
    cache_home = os.path.abspath(os.path.join(runtime_root, "cache"))
    os.makedirs(data_home, exist_ok=True)
    os.makedirs(cache_home, exist_ok=True)
    os.environ.setdefault("XDG_DATA_HOME", data_home)
    os.environ.setdefault("XDG_CACHE_HOME", cache_home)


def running_inside_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8") as version_file:
            version = version_file.read().lower()
    except OSError:
        return False
    return "microsoft" in version or "wsl" in version


def print_environment_notes(config: ConnectionConfig) -> None:
    if running_inside_wsl():
        print(
            "NOTE: WSL detected. If Olympe reports 'Too many ping failures', "
            "run this from native Ubuntu/Linux, use WSL2 mirrored networking, "
            "or connect through SkyController 4."
        )

    if config.controller == "direct":
        print(
            "Direct mode selected. ANAFI Ai must have Direct Connection mode enabled."
        )


def print_connection_troubleshooting(config: ConnectionConfig) -> None:
    print("Connection failed before a stable Olympe session was established.")
    print("Safe troubleshooting checklist:")
    print("- Keep propellers removed while testing connection code indoors.")
    print(f"- Confirm this machine can reach {config.ip}.")
    print("- Confirm ANAFI Ai Direct Connection mode is enabled when using --controller direct.")
    print("- If running in WSL, try native Ubuntu/Linux or WSL2 mirrored networking.")
    print("- If using SkyController 4, run with --controller skycontroller4.")


def summarize_state_value(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 300 else f"{text[:297]}..."


def query_state_safely(device: Any, query: str) -> dict[str, Any]:
    try:
        result = device.query_state(query)
    except Exception as exc:  # Olympe can raise SDK/runtime exceptions per device state.
        return {"error": f"{type(exc).__name__}: {exc}"}
    return dict(result or {})


def is_possibly_airborne(flying_states: dict[str, Any]) -> bool:
    if not flying_states or "error" in flying_states:
        return False

    landed_markers = ("landed", "emergency", "motor_ramping", "usertakeoff")
    airborne_markers = ("takingoff", "hovering", "flying", "landing")
    state_text = repr(flying_states).lower()

    if any(marker in state_text for marker in airborne_markers):
        return True
    if any(marker in state_text for marker in landed_markers):
        return False
    return False


def print_report(device: Any, config: ConnectionConfig) -> int:
    connected_prop = bool(getattr(device, "connected", False))

    try:
        connection_state = device.drone_connection_state()
    except Exception as exc:
        connection_state = f"unknown ({type(exc).__name__}: {exc})"

    print("=== ANAFI Ai connection check ===")
    print(f"controller: {config.controller}")
    print(f"ip: {config.ip}")
    print(f"connected property: {connected_prop}")
    print(f"drone_connection_state(): {connection_state}")

    state_queries = {
        "battery": "Battery",
        "flying_state": "FlyingStateChanged",
        "gps": "GpsLocationChanged",
        "product": "Product",
    }
    snapshots: dict[str, dict[str, Any]] = {}
    for label, query in state_queries.items():
        snapshots[label] = query_state_safely(device, query)

    for label, snapshot in snapshots.items():
        print(f"{label}: {summarize_state_value(snapshot)}")

    if is_possibly_airborne(snapshots["flying_state"]):
        print(
            "WARNING: The drone state looks airborne or transitioning. "
            "This script will not send landing or piloting commands."
        )

    return 0 if connected_prop and bool(connection_state) else 2


def main() -> int:
    connected = False
    device: Any | None = None

    try:
        config = parse_args()
        configure_olympe_runtime_dirs()
        print(f"Using Python: {sys.executable}")
        controller_class = import_controller_class(config.controller)
        device = controller_class(config.ip)

        print_environment_notes(config)
        print("Connecting in check-only mode. No flight commands will be sent.")
        connected = bool(device.connect(timeout=config.timeout, retry=config.retry))
        if not connected:
            print("Connection failed: device.connect(...) returned False.")
            print_connection_troubleshooting(config)
            return 2

        print(f"Connection succeeded: {config.controller} at {config.ip}")
        return print_report(device, config)
    except KeyboardInterrupt:
        print("Interrupted by user. Disconnecting without sending flight commands.")
        return 130
    except SafetyError as exc:
        print(f"Safety configuration error: {exc}")
        return 2
    except Exception as exc:
        print(f"Connection check failed safely: {type(exc).__name__}: {exc}")
        return 1
    finally:
        if connected and device is not None:
            try:
                disconnected = bool(device.disconnect(timeout=5.0))
                print(f"disconnected: {disconnected}")
            except Exception as exc:
                print(f"Disconnect raised an exception: {type(exc).__name__}: {exc}")
        if device is not None:
            try:
                device.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
