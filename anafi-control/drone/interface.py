from abc import ABC, abstractmethod

from .telemetry import Telemetry


class AnafiController(ABC):
    """드론 제어 인터페이스.

    설계 원칙: 이 인터페이스 수준에서만 서버/UI 로직을 검증한다.
    - MockController : sleep + 상태변수로 구현. 명령 큐 직렬화, broadcast, UI 흐름 검증용.
    - RealController : Olympe 호출부. 얇게 유지하고 실제 검증은 Sphinx에서만 한다.

    모든 cm/도 단위는 '사용자 직관' 좌표 (up_cm 양수 = 상승, right_cm 양수 = 우측).
    NED 부호 반전은 RealController.move_cm 내부에서만 일어난다.
    """

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self): ...

    @abstractmethod
    def takeoff(self) -> bool: ...

    @abstractmethod
    def land(self) -> bool: ...

    @abstractmethod
    def move_cm(self, forward_cm: float = 0, right_cm: float = 0,
                up_cm: float = 0, yaw_deg: float = 0) -> bool: ...

    @abstractmethod
    def go_to_altitude(self, target_m: float) -> bool: ...

    @abstractmethod
    def return_home_initial(self) -> bool: ...

    @abstractmethod
    def emergency_cutoff(self): ...

    @abstractmethod
    def get_telemetry(self) -> Telemetry: ...
