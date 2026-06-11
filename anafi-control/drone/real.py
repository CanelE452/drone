import copy
import math
import os
import threading

import config

from .interface import AnafiController
from .telemetry import Telemetry

# Olympe import 는 모듈 로드 시 무겁고 sdl2/OpenGL 의존성이 있으므로
# RealController 가 실제로 선택될 때만 import 한다 (mock 실행 시 불필요).


def _configure_runtime_dirs():
    """Olympe 런타임 캐시를 프로젝트 안에 격리 (WSL/권한 오염 회피)."""
    root = os.environ.get("OLYMPE_RUNTIME_ROOT", ".olympe_runtime")
    for sub, var in (("share", "XDG_DATA_HOME"), ("cache", "XDG_CACHE_HOME")):
        path = os.path.abspath(os.path.join(root, sub))
        os.makedirs(path, exist_ok=True)
        os.environ.setdefault(var, path)


class RealController(AnafiController):
    """Olympe 실연결 컨트롤러. 의도적으로 얇게 유지한다.

    이 클래스의 Olympe 호출부는 mock 으로 검증되지 않는다 — 실제 검증은
    Sphinx(또는 실기체)에 붙는 첫날에만 일어난다. 따라서 여기에 로직을
    얹지 말 것. 좌표 변환(NED 부호 반전)과 expectation 체이닝만 담당한다.
    """

    def __init__(self, ip):
        import olympe

        _configure_runtime_dirs()
        self._ip = ip
        # ANAFI Ai 전용 컨트롤러 클래스 우선, 없으면 범용 Drone 으로 fallback
        controller_cls = getattr(olympe, "AnafiAi", None) or olympe.Drone
        self._drone = controller_cls(ip)
        self._t = Telemetry()
        self._lock = threading.Lock()

    def connect(self) -> bool:
        # Olympe 연결은 충분한 타임아웃이 필요하다 (최소 45초 권장)
        ok = bool(self._drone.connect(
            timeout=config.CONNECT_TIMEOUT_S, retry=config.CONNECT_RETRY))
        with self._lock:
            self._t.connected = ok
        return ok

    def disconnect(self):
        self._drone.disconnect()
        with self._lock:
            self._t.connected = False

    def takeoff(self) -> bool:
        from olympe.messages.ardrone3.Piloting import TakeOff
        from olympe.messages.ardrone3.PilotingState import FlyingStateChanged

        ok = self._drone(
            TakeOff()
            >> FlyingStateChanged(state="hovering", _timeout=config.COMMAND_TIMEOUT_S)
        ).wait().success()
        self._refresh()
        return ok

    def land(self) -> bool:
        from olympe.messages.ardrone3.Piloting import Landing
        from olympe.messages.ardrone3.PilotingState import FlyingStateChanged

        ok = self._drone(
            Landing()
            >> FlyingStateChanged(state="landed", _timeout=config.COMMAND_TIMEOUT_S)
        ).wait().success()
        self._refresh()
        return ok

    def move_cm(self, forward_cm=0, right_cm=0, up_cm=0, yaw_deg=0) -> bool:
        from olympe.messages.ardrone3.Piloting import moveBy
        from olympe.messages.ardrone3.PilotingState import FlyingStateChanged

        # 사용자 직관 좌표 → 기체 NED 프레임 (dZ 음수 = 상승)
        dX = forward_cm / 100.0
        dY = right_cm / 100.0
        dZ = -up_cm / 100.0
        dPsi = math.radians(yaw_deg)

        ok = self._drone(
            moveBy(dX, dY, dZ, dPsi)
            >> FlyingStateChanged(state="hovering", _timeout=config.COMMAND_TIMEOUT_S)
        ).wait().success()

        if ok:
            # TODO(Sphinx 검증): 누적 변위는 moveByEnd 이벤트의 실측 dX/dY/dZ 로 보정.
            #   from olympe.messages.ardrone3.PilotingEvent import moveByEnd
            #   evt = self._drone.get_state(moveByEnd)  # 실측 변위 (m)
            # 지금은 명령값을 그대로 누적 (mock 과 동일한 인터페이스 유지).
            with self._lock:
                self._t.est_x_cm += forward_cm
                self._t.est_y_cm += right_cm
                self._t.est_z_cm += up_cm
                self._t.last_cmd = {
                    "forward_cm": forward_cm, "right_cm": right_cm,
                    "up_cm": up_cm, "yaw_deg": yaw_deg,
                }
            self._refresh()
        return ok

    def go_to_altitude(self, target_m: float) -> bool:
        self._refresh()
        with self._lock:
            cur = self._t.altitude_m
        return self.move_cm(up_cm=(target_m - cur) * 100.0)

    def return_home_initial(self) -> bool:
        with self._lock:
            dx, dy = self._t.est_x_cm, self._t.est_y_cm
        return self.move_cm(forward_cm=-dx, right_cm=-dy)

    def emergency_cutoff(self):
        from olympe.messages.ardrone3.Piloting import Emergency

        self._drone(Emergency()).wait()

    def get_telemetry(self) -> Telemetry:
        self._refresh()
        with self._lock:
            return copy.deepcopy(self._t)

    def _refresh(self):
        """Olympe get_state 폴링으로 텔레메트리 스냅숏 갱신 (얇게)."""
        from olympe.messages.ardrone3.PilotingState import (
            FlyingStateChanged, AltitudeChanged, AttitudeChanged,
        )
        from olympe.messages.common.CommonState import BatteryStateChanged

        def safe(msg, key, default):
            try:
                return self._drone.get_state(msg)[key]
            except Exception:
                return default

        with self._lock:
            fs = safe(FlyingStateChanged, "state", None)
            self._t.flying_state = fs.name if fs is not None else self._t.flying_state
            self._t.altitude_m = safe(AltitudeChanged, "altitude", self._t.altitude_m)
            yaw = safe(AttitudeChanged, "yaw", None)
            if yaw is not None:
                self._t.yaw_deg = math.degrees(yaw) % 360
            self._t.battery_pct = safe(BatteryStateChanged, "percent", self._t.battery_pct)
