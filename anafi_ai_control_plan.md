# Parrot ANAFI Ai 실시간 제어 시스템 구현 계획

> 이 문서는 Claude Code(CLI)가 그대로 따라 작업할 수 있도록 작성된 실행 계획서다.
> 목표: 컴퓨터에서 Parrot ANAFI Ai 드론을 cm 단위로 제어하는 실시간 제어 화면(웹 UI) 구축.
> 환경: Ubuntu Linux. Olympe는 Linux 전용이므로 반드시 Ubuntu에서 작업한다.
>
> **⚠️ 환경 실측 완료 (2026-06-10) — 아래는 추측이 아니라 이 머신에서 실제로 검증된 값이다:**
> - OS: Ubuntu 22.04.5 LTS (jammy), x86_64, glibc 2.35
> - **기본 Python은 anaconda 3.13.9 → parrot-olympe 미지원. 절대 이걸로 설치 시도하지 말 것.**
> - **확정 환경: conda env `olympe` (Python 3.10). `parrot-olympe==8.4.0` import 성공 검증 완료.**
> - `python3.10-venv`는 ensurepip 결손으로 `venv` 생성 실패 → **venv 대신 conda 사용** (sudo 불필요).
> - GPU: RTX 3080 10GB → Sphinx UE 시뮬 가능.

---

## 0. 배경 지식 (작업 전 반드시 숙지)

### 0.1 SDK 구성
- **Olympe**: Parrot 공식 Python SDK. **현재 최신 `parrot-olympe==8.4.0`** (Python 3.9/3.10/3.11, Linux x86_64 전용). BSD-3 라이선스.
  - 문서: https://developer.parrot.com/docs/olympe/
  - GitHub: https://github.com/Parrot-Developers/olympe
- **Sphinx**: Parrot 공식 시뮬레이터 (Unreal Engine 기반). 실기체 없이 전체 파이프라인 검증 가능.
  - 문서: https://developer.parrot.com/docs/sphinx/
- **PDrAW**: 영상 스트리밍 파이프라인. Olympe에 내장된 streaming API로 RTSP 영상 수신 가능.

### 0.2 연결 IP (중요)
| 연결 방식 | DRONE_IP |
|---|---|
| Sphinx 시뮬레이터 | `10.202.0.1` |
| 실기체 직접 WiFi 연결 | `192.168.42.1` |
| SkyController 3 경유 (USB) | `192.168.53.1` |

코드에서는 `DRONE_IP = os.environ.get("DRONE_IP", "10.202.0.1")` 패턴으로 환경변수 분기.

### 0.3 좌표계 (가장 흔한 실수 지점)
`moveBy(dX, dY, dZ, dPsi)`는 **드론 기체 기준 NED 프레임**:
- `dX`: 전방(+) / 후방(−), 단위 **미터**
- `dY`: 우측(+) / 좌측(−), 단위 미터
- `dZ`: **아래(+) / 위(−)** ← 상승하려면 음수! 단위 미터
- `dPsi`: 시계방향 yaw 회전, 단위 **라디안**

cm 단위 제어 → UI에서 cm 입력받고 내부에서 `/100`으로 미터 변환.

### 0.4 상태 머신 제약 (두 번째로 흔한 실수)
- `moveBy`는 드론이 `hovering` 상태일 때만 수락됨. `takingoff` 상태에서 보내면 조용히 거부됨.
- 따라서 모든 이동 명령은 expectation 체이닝 필수:
```python
drone(TakeOff() >> FlyingStateChanged(state="hovering", _timeout=10)).wait()
drone(moveBy(0.5, 0, 0, 0) >> FlyingStateChanged(state="hovering", _timeout=10)).wait()
```
- `>>` 연산자는 "그리고 나서 기다림" 의미의 Olympe eDSL.
- `.wait().success()`로 성공 여부 확인하고, 실패 시 로그 남기기.

### 0.5 두 가지 제어 모드
1. **이산 이동 (moveBy)**: "오른쪽 30cm", "위로 50cm" 같은 스텝 이동. 본 프로젝트의 기본 모드.
2. **연속 조종 (PCMD)**: 게임패드/키보드 홀드 방식 실시간 조종. `olympe.messages.ardrone3.Piloting.PCMD`를 25~50ms 주기로 전송. Phase 5에서 선택 구현.

### 0.6 정밀도 한계 (사용자에게 고지할 사항)
- 실내(GPS 없음)에서는 visual odometry + 기압계 기반이라 cm 명령을 내려도 실제 오차 ±10~30cm 발생 가능.
- 1~5cm 단위 미세 이동은 명령 자체는 가능하나 데드밴드에 걸려 무시될 수 있음. 최소 이동 단위 10cm 권장.
- UI에 "명령값 vs 텔레메트리 실측값"을 둘 다 표시해서 오차를 사용자가 볼 수 있게 한다.

---

## 1. Phase 1 — 환경 구축

### 1.1 시스템 요구사항 (이 머신 기준 실측 확정 — 재확인 불필요)
```
OS          Ubuntu 22.04.5 LTS (jammy), x86_64, glibc 2.35   ✓
기본 Python  anaconda 3.13.9                                  ✗ 사용 금지 (Olympe 미지원)
대상 Python  conda env "olympe" / Python 3.10                 ✓ import 검증 완료
GPU         RTX 3080 10GB                                     ✓ Sphinx 가능
```
- **핵심 함정 (이미 겪음)**: 기본 python3은 anaconda 3.13이라 `pip install parrot-olympe`가 wheel 없음으로 실패한다. 반드시 conda env(3.10)에서 설치한다.
- **venv는 쓰지 않는다**: `/usr/bin/python3.10`은 `python3.10-venv`의 ensurepip가 결손이라 `python3.10 -m venv`가 실패한다(sudo apt 필요). conda는 sudo 없이 되므로 conda로 간다.

### 1.2 프로젝트 구조 생성
```
anafi-control/
├── .venv/
├── requirements.txt
├── README.md
├── config.py              # DRONE_IP, 안전 한계값 등 설정
├── drone/
│   ├── __init__.py
│   ├── controller.py      # Olympe 래퍼: connect, takeoff, move_cm, land, go_to_altitude
│   ├── telemetry.py       # 상태 구독: 고도, 자세, 속도, 배터리, flying state
│   └── video.py           # PDrAW 스트리밍 → JPEG 프레임 (Phase 4)
├── server/
│   ├── app.py             # FastAPI + WebSocket 서버
│   └── static/
│       └── index.html     # 제어 UI (단일 파일: HTML+CSS+JS)
└── scripts/
    ├── test_connect.py    # 연결 스모크 테스트
    ├── test_takeoff_land.py
    └── test_moveby.py
```

### 1.3 의존성 설치 (실측 검증된 절차 — 이대로 실행)
```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda create -y -n olympe python=3.10
conda activate olympe
# parrot-olympe 본체
pip install parrot-olympe                     # → 8.4.0
# ⚠️ import olympe 가 영상 렌더러를 강제 로드하므로 아래 3개 없으면 import 자체가 실패한다 (실측)
pip install PySDL2 pysdl2-dll PyOpenGL        # sdl2 / OpenGL 결손 메우기
# 서버/영상
pip install fastapi "uvicorn[standard]" websockets opencv-python
pip freeze > requirements.txt
# 검증: 아래가 "olympe OK, version: 8.4.0" 찍으면 성공
python -c "import olympe; print('olympe OK, version:', olympe.__version__)"
```
- **이미 겪은 함정**: `import olympe` → `ModuleNotFoundError: No module named 'sdl2'` → 고치면 다음은 `'OpenGL'`. 둘 다 영상 렌더러(PdrawRenderer) 의존성이라 MJPEG 방식엔 실제로 불필요하지만 import가 강제 로드한다. 위 3개 패키지로 해결됨(검증 완료).

### 1.4 Sphinx 시뮬레이터 설치 (실기체 테스트 전 필수)
- https://developer.parrot.com/docs/sphinx/installation.html 절차를 따른다 (apt repo 추가 → `parrot-sphinx` 설치 → UE 앱 설치).
- 실행: `sphinx "/opt/parrot-sphinx/usr/share/sphinx/drones/anafi_ai.drone"::firmware="..."` + UE 환경 앱 실행.
- 이 머신은 RTX 3080이 있어 UE 환경 실행 가능성이 높다. 다만 Sphinx+UE 설치는 의존성이 무거워 실패율이 있다.
- **Sphinx 설치 실패 시 — 실기체 직행 금지(추락 리스크)**. 대신 단계적 폴백:
  1. **헤드리스 텔레메트리 경로**: UE 비주얼 없이 `sphinx ...drone` 펌웨어 프로세스만 띄우면 Olympe 연결·TakeOff·moveBy·텔레메트리는 다 검증된다(영상만 없음). 이걸로 Phase 2~3 + UI 로직 전부 검증 가능.
  2. UI/서버는 드론 없이도 controller를 mock으로 갈아끼워 단독 테스트(WebSocket·큐·버튼 흐름).
  3. 실기체 전환은 위 둘이 통과한 뒤 Phase 5에서만, 빈 실외 개활지에서.

---

## 2. Phase 2 — 코어 제어 모듈 (`drone/controller.py`)

### 2.1 구현할 클래스 인터페이스
```python
class AnafiController:
    def __init__(self, ip: str): ...
    def connect(self) -> bool
    def disconnect(self)
    def takeoff(self) -> bool                      # TakeOff >> hovering 대기
    def land(self) -> bool                         # Landing >> landed 대기
    def move_cm(self, forward_cm=0, right_cm=0, up_cm=0, yaw_deg=0) -> bool
        # 내부: moveBy(forward_cm/100, right_cm/100, -up_cm/100, radians(yaw_deg))
        # up_cm 양수 = 상승 (부호 반전 캡슐화가 이 함수의 존재 이유)
    def go_to_altitude(self, target_m: float) -> bool
        # 텔레메트리에서 현재 고도(AltitudeChanged) 읽고 delta = target - current
        # moveBy(0, 0, -delta, 0) 실행. 수렴 확인 후 1회 보정 재시도(최대 2회).
    def return_home_initial(self) -> bool
        # "initial state 복귀": 이륙 지점 기준 누적 변위를 소프트웨어로 추적해 역이동
        # 또는 GPS 있으면 moveTo / RTH 사용. 실내면 누적 변위 방식.
    def land(self) -> bool                         # (재게시) 긴급 착륙도 이 메서드 재사용 — 즉시 실행
    def emergency_cutoff(self)                      # ardrone3.Piloting.Emergency — 모터 즉시 컷오프
        # ⚠️ 공중에서 호출하면 그대로 추락. UI에서 hold-to-confirm(1초 홀드)로만 노출.
```

### 2.2 핵심 import
```python
import olympe
from olympe.messages.ardrone3.Piloting import TakeOff, Landing, moveBy, PCMD, Emergency
from olympe.messages.ardrone3.PilotingState import (
    FlyingStateChanged, AltitudeChanged, PositionChanged, SpeedChanged, AttitudeChanged
)
from olympe.messages.common.CommonState import BatteryStateChanged
```

### 2.3 안전 가드 (`config.py`)
```python
MAX_ALTITUDE_M = 2.5        # 실내 기준. 실외면 상향
MAX_STEP_CM = 100           # 한 번의 moveBy 최대 이동량
MIN_STEP_CM = 10            # 데드밴드 회피
MIN_BATTERY_PCT = 20        # 이하면 이동 명령 거부, 착륙 유도
COMMAND_TIMEOUT_S = 10
```
- 모든 이동 명령 전에 가드 체크. 위반 시 명령 거부 + 사유를 UI로 push.

### 2.4 테스트 (Sphinx에서)
- `scripts/test_takeoff_land.py`: 이륙 → 5초 호버 → 착륙.
- `scripts/test_moveby.py`: 이륙 → 전진 50cm → 우측 30cm → 상승 50cm → 제자리 복귀(역이동) → 착륙.
- 각 단계 `.wait().success()` assert + 텔레메트리 고도 로그 출력.

---

## 3. Phase 3 — 텔레메트리 모듈 (`drone/telemetry.py`)

- `olympe.EventListener` 서브클래스 또는 `drone.get_state()` 폴링(5~10Hz)으로 다음 수집:
  - flying state (landed/takingoff/hovering/flying/landing)
  - 고도 (AltitudeChanged — 이륙 지점 기준)
  - 자세 (roll/pitch/yaw)
  - 속도 (SpeedChanged)
  - 배터리 %
  - GPS fix 여부 (실외)
- 수집한 상태를 thread-safe한 dataclass 스냅숏으로 보관 → 서버가 WebSocket으로 broadcast.
- **누적 변위 추적**: moveBy 완료 이벤트 `moveByEnd`의 실측 dX/dY/dZ를 누적해 "이륙 지점 대비 추정 위치" 유지. initial state 복귀에 사용.
  - **⚠️ import 위치 주의 (실측 확정)**: `moveByEnd`는 `PilotingState`에 **없다**. 정확한 경로는
    `from olympe.messages.ardrone3.PilotingEvent import moveByEnd` (PilotingState로 쓰면 `KeyError: 'moveByEnd'`).

---

## 4. Phase 4 — 웹 제어 UI (`server/`)

### 4.1 아키텍처
```
브라우저(index.html) ←WebSocket→ FastAPI(app.py) → AnafiController → 드론
                      ←WebSocket←  telemetry broadcast (10Hz)
                      ←HTTP MJPEG← video.py (영상, 선택)
```
- 제어 명령은 WebSocket JSON 메시지: `{"cmd": "move", "forward_cm": 0, "right_cm": 30, "up_cm": 0, "yaw_deg": 0}`
- 서버는 명령을 **큐에 직렬화** (moveBy는 동시 실행 불가 — 이전 명령 완료 후 다음 실행).
- 진행 중 명령이 있으면 UI 버튼 비활성화 + "이동 중" 표시.

### 4.2 UI 구성 (단일 index.html, 프레임워크 없이 vanilla JS)
- 상단: 연결 상태, flying state, 배터리, 고도(목표 vs 실측), yaw
- 중앙: 방향 패드 (전/후/좌/우/상/하/yaw±) + 스텝 크기 선택 (10/30/50/100 cm)
- 하단:
  - "이륙" / "착륙" 버튼
  - "고도 설정" 입력란 (m) + 이동 버튼 → `go_to_altitude`
  - "초기 위치 복귀" 버튼 → `return_home_initial`
  - **안전 정지는 2단 분리** (실수 1번으로 추락 방지 + 진짜 비상엔 즉시 대응):
    - **긴급 착륙 (Landing)** — 크고 빨갛게, 즉시 실행. "멈춰야 해"의 99%는 이걸로 충분. → `land()`
    - **모터 컷오프 (Emergency)** — 별도 위치에 작게, **1초 hold-to-confirm**. 공중이면 추락하므로 오조작 방지. 확인 대화상자보다 빠름. → `emergency_cutoff()`
- 키보드 바인딩: WASD(수평), R/F(상승/하강), Q/E(yaw), Space(착륙)

### 4.3 영상 스트리밍 (선택, 후순위)
- Olympe streaming API(`drone.streaming.set_callbacks` + yuv_frame_cb)로 프레임 수신 → OpenCV로 BGR 변환 → MJPEG HTTP 응답 (`multipart/x-mixed-replace`).
- 공식 예제: https://github.com/Parrot-Developers/olympe/blob/master/src/olympe/doc/examples/streaming.py
- 실패하거나 지연이 크면 일단 영상 없이 텔레메트리만으로 완성하고 별도 이슈로 분리.

---

## 5. Phase 5 — 실기체 전환 + 고급 기능 (선택)

1. `DRONE_IP=192.168.42.1`로 환경변수만 바꿔 실기체 연결 (노트북 WiFi를 드론 AP에 연결).
2. 첫 실기체 테스트는 **실외 개활지**, 고도 1.5m 이하, 비상정지 손에 들고.
3. PCMD 기반 연속 조종 모드 추가 (키 홀드 → 25ms 주기 PCMD 전송, 키 릴리즈 → 0 전송).
4. 게임패드 지원 (Gamepad API).

---

## 6. 작업 순서 요약 (CLI 체크리스트)

- [ ] 1. Ubuntu/Python 버전 확인, venv 생성, parrot-olympe 설치 성공 확인
- [ ] 2. 프로젝트 구조 생성
- [ ] 3. Sphinx 설치 시도 (실패 시 사용자에게 보고 후 실기체 경로 협의)
- [ ] 4. `test_connect.py` → 연결 성공 확인
- [ ] 5. `controller.py` 구현 + `test_takeoff_land.py` 통과
- [ ] 6. `move_cm` / `go_to_altitude` 구현 + `test_moveby.py` 통과
- [ ] 7. `telemetry.py` 구현, 10Hz 스냅숏 확인
- [ ] 8. FastAPI + WebSocket 서버 + index.html UI 구현
- [ ] 9. 시뮬레이터에서 UI 통합 테스트 (이륙→스텝이동→고도설정→복귀→착륙 전체 시나리오)
- [ ] 10. (선택) 영상 스트리밍, 실기체 전환

## 7. 흔한 함정 정리

| 증상 | 원인 | 해결 |
|---|---|---|
| moveBy가 무시됨 | hovering 아닌 상태에서 전송 | `>> FlyingStateChanged(state="hovering")` 체이닝 |
| 위로 가라는데 아래로 감 | dZ 부호 (NED) | `move_cm`에서 부호 반전 캡슐화 |
| pip 설치 실패 | Python 버전 미지원 | PyPI에서 지원 버전 확인 후 pyenv |
| 5cm 이동 안 됨 | 데드밴드 | 최소 스텝 10cm 강제 |
| 명령 겹쳐서 드론 멈춤 | moveBy 동시 전송 | 서버 측 명령 큐 직렬화 |
| 실내에서 위치 drift | GPS 없음, VO 오차 | UI에 실측값 병기, 복귀는 누적변위 기반 |
| Olympe import 에러 (macOS/Windows) | Linux 전용 SDK | Ubuntu에서만 작업 |
| `pip install parrot-olympe` wheel 없음 | 기본 python이 anaconda 3.13 (미지원) | conda env python=3.10 에서 설치 [실측] |
| `import olympe` → No module named 'sdl2' / 'OpenGL' | 영상 렌더러 의존성 결손 | `pip install PySDL2 pysdl2-dll PyOpenGL` [실측] |
| `python3.10 -m venv` 실패 (ensurepip 없음) | python3.10-venv 패키지 결손 | venv 대신 conda 사용 [실측] |
| `KeyError: 'moveByEnd'` | PilotingState엔 없음 | `from olympe.messages.ardrone3.PilotingEvent import moveByEnd` [실측] |
