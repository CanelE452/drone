from dataclasses import dataclass, asdict, field


@dataclass
class Telemetry:
    """드론 상태 스냅숏. 서버가 WebSocket으로 broadcast 한다."""

    connected: bool = False
    flying_state: str = "landed"   # landed/takingoff/hovering/flying/landing
    altitude_m: float = 0.0        # 이륙 지점 기준 실측 고도
    yaw_deg: float = 0.0
    battery_pct: int = 100
    gps_fix: bool = False

    # 이륙 지점 대비 추정 위치 (실측 누적). initial state 복귀에 사용.
    est_x_cm: float = 0.0          # 전방+
    est_y_cm: float = 0.0          # 우측+
    est_z_cm: float = 0.0          # 상승+ (UI 표시는 +상승, 내부 NED 변환은 controller가 캡슐화)

    # 마지막 이동의 명령값 vs 실측값 — UI에 오차를 보여주기 위함
    last_cmd: dict = field(default_factory=dict)
    last_actual: dict = field(default_factory=dict)

    def to_dict(self):
        return asdict(self)
