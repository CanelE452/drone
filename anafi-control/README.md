# ANAFI Ai 실시간 제어

Parrot ANAFI Ai를 컴퓨터에서 cm 단위로 제어하는 웹 UI. 설계/배경은 상위 폴더
`anafi_ai_control_plan.md` 참조.

## 환경 (실측 확정)

- Ubuntu 22.04, conda env `olympe` (Python 3.10), `parrot-olympe 8.4.0`
- 기본 anaconda 3.13으로는 설치 불가 — 반드시 conda 3.10 환경 사용

```bash
source ~/anaconda3/etc/profile.d/conda.sh
conda activate olympe
pip install fastapi "uvicorn[standard]" websockets opencv-python   # 서버 의존성
```

## 실행

### 1) Mock 모드 — 드론 없이 UI/로직 검증 (지금 바로 가능)
```bash
cd anafi-control
python scripts/test_mock_controller.py          # 컨트롤러 단독 검증
CONTROLLER=mock uvicorn server.app:app --reload  # 브라우저: http://localhost:8000
```

### 2) Real 모드 — Sphinx 또는 실기체
```bash
# Sphinx (기본 IP 10.202.0.1)
CONTROLLER=real DRONE_IP=10.202.0.1 uvicorn server.app:app
# 실기체 WiFi
CONTROLLER=real DRONE_IP=192.168.42.1 uvicorn server.app:app
```

## 구조

```
config.py            DRONE_IP, CONTROLLER, 안전 가드 값
drone/
  interface.py       AnafiController 추상 인터페이스
  mock.py            sleep+상태변수, ±10% 가짜 drift (로직 검증용)
  real.py            Olympe 호출부 (얇게 — 실검증은 Sphinx에서만)
  telemetry.py       상태 스냅숏 dataclass
server/
  app.py             FastAPI + WebSocket + 명령 큐 직렬화 + 안전 가드
  static/index.html  제어 UI (방향패드, 명령/실측 병기, hold-to-confirm 컷오프)
scripts/
  test_mock_controller.py
```

## 안전

- **긴급 착륙 (Space / 빨간 버튼)**: 즉시 착륙. 대부분의 정지는 이걸로.
- **모터 컷오프 (1초 hold)**: `Emergency` — 공중이면 추락. 오조작 방지용 hold-to-confirm.
- 안전 가드: 최소 10cm / 최대 100cm 스텝, 최대 2.5m 고도, 배터리 20% 미만 이동 거부.
