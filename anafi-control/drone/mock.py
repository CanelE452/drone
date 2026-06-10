import copy
import random
import threading
import time

import config

from .interface import AnafiController
from .telemetry import Telemetry


class MockController(AnafiController):
    """드론 없이 서버/UI 로직을 검증하기 위한 가짜 컨트롤러.

    - 내부는 sleep + 상태변수 수준 (Olympe eDSL은 재현하지 않는다).
    - 이동 시 명령값 대비 ±10% 가짜 drift를 줘서, UI의 '명령값 vs 실측값'
      병기 표시가 실기체 전에 검증되도록 한다.
    """

    def __init__(self, ip=None):
        self._ip = ip
        self._t = Telemetry()
        self._lock = threading.Lock()

    def connect(self) -> bool:
        with self._lock:
            self._t.connected = True
            self._t.battery_pct = 100
        return True

    def disconnect(self):
        with self._lock:
            self._t.connected = False

    def takeoff(self) -> bool:
        with self._lock:
            if self._t.flying_state != "landed":
                return False
            self._t.flying_state = "takingoff"
        time.sleep(1.5)
        with self._lock:
            self._t.flying_state = "hovering"
            self._t.altitude_m = 1.0      # 기본 이륙 고도 1m
            self._t.est_z_cm = 100.0
            self._t.battery_pct = max(self._t.battery_pct - 1, 0)
        return True

    def land(self) -> bool:
        with self._lock:
            if self._t.flying_state == "landed":
                return True
            self._t.flying_state = "landing"
        time.sleep(1.0)
        with self._lock:
            self._t.flying_state = "landed"
            self._t.altitude_m = 0.0
            self._t.est_z_cm = 0.0
        return True

    @staticmethod
    def _drift(cmd_cm: float) -> float:
        """명령값에 ±10% 가짜 오차를 입혀 실측값을 만든다."""
        if cmd_cm == 0:
            return 0.0
        return cmd_cm * (1.0 + random.uniform(-0.10, 0.10))

    def move_cm(self, forward_cm=0, right_cm=0, up_cm=0, yaw_deg=0) -> bool:
        with self._lock:
            if self._t.flying_state != "hovering":
                return False
            if self._t.battery_pct < config.MIN_BATTERY_PCT:
                return False
            self._t.flying_state = "flying"

        dist = max(abs(forward_cm), abs(right_cm), abs(up_cm))
        time.sleep(min(0.3 + dist / 100.0, 3.0))

        actual_f = self._drift(forward_cm)
        actual_r = self._drift(right_cm)
        actual_u = self._drift(up_cm)

        with self._lock:
            self._t.est_x_cm += actual_f
            self._t.est_y_cm += actual_r
            self._t.est_z_cm += actual_u
            self._t.altitude_m = max(self._t.est_z_cm / 100.0, 0.0)
            self._t.yaw_deg = (self._t.yaw_deg + yaw_deg) % 360
            self._t.battery_pct = max(self._t.battery_pct - 1, 0)
            self._t.last_cmd = {
                "forward_cm": forward_cm, "right_cm": right_cm,
                "up_cm": up_cm, "yaw_deg": yaw_deg,
            }
            self._t.last_actual = {
                "forward_cm": round(actual_f, 1), "right_cm": round(actual_r, 1),
                "up_cm": round(actual_u, 1), "yaw_deg": yaw_deg,
            }
            self._t.flying_state = "hovering"
        return True

    def go_to_altitude(self, target_m: float) -> bool:
        with self._lock:
            cur = self._t.altitude_m
        return self.move_cm(up_cm=(target_m - cur) * 100.0)

    def return_home_initial(self) -> bool:
        with self._lock:
            dx, dy = self._t.est_x_cm, self._t.est_y_cm
        return self.move_cm(forward_cm=-dx, right_cm=-dy)

    def emergency_cutoff(self):
        # mock: 모터 즉시 컷오프 = 그 자리에서 바닥으로
        with self._lock:
            self._t.flying_state = "landed"
            self._t.altitude_m = 0.0
            self._t.est_z_cm = 0.0

    def get_telemetry(self) -> Telemetry:
        with self._lock:
            return copy.deepcopy(self._t)
