import os

# 연결 IP — 환경변수로 분기 (Sphinx / 실기체 / SkyController)
#   Sphinx 시뮬레이터 : 10.202.0.1 (기본)
#   실기체 직접 WiFi   : 192.168.42.1
#   SkyController(USB) : 192.168.53.1
DRONE_IP = os.environ.get("DRONE_IP", "10.202.0.1")

# 컨트롤러 선택: "mock"(드론 없이 로직 검증) / "real"(Olympe 실연결)
CONTROLLER = os.environ.get("CONTROLLER", "mock")

# 안전 가드 (실내 기준 — 실외면 상향)
MAX_ALTITUDE_M = 2.5      # 최대 고도
MAX_STEP_CM = 100         # 한 번의 moveBy 최대 이동량
MIN_STEP_CM = 10          # 데드밴드 회피 (이하 명령은 거부)
MIN_BATTERY_PCT = 20      # 이하면 이동 명령 거부
COMMAND_TIMEOUT_S = 10    # expectation 타임아웃

# 텔레메트리 broadcast 주기
TELEMETRY_HZ = 10
