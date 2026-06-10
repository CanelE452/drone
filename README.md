# drone — Parrot ANAFI Ai 실시간 제어

컴퓨터에서 Parrot ANAFI Ai 드론을 **cm 단위로 제어**하는 실시간 웹 UI.
좌우/상하 cm 이동, 바닥 기준 목표 고도 이동, 초기 위치 복귀를 브라우저에서 조작한다.

> Parrot 공식 Python SDK **Olympe**(Linux 전용) 기반. 드론 없이 **Mock 모드**로 UI 전체를
> 먼저 검증하고, **Sphinx 시뮬레이터** → 실기체 순으로 넘어가는 구조.

## Quick Start (Mock — 드론 없이 바로 실행)

```bash
git clone https://github.com/CanelE452/drone.git
cd drone/anafi-control
conda env create -f environment.yml && conda activate olympe
CONTROLLER=mock uvicorn server.app:app --host 0.0.0.0
# 브라우저: http://localhost:8000
```

Mock 모드는 sleep+상태변수로 동작하며 텔레메트리에 ±10% 가짜 오차를 넣어, 실기체 전에
명령값/실측값 병기 UI와 명령 큐·안전 가드·이착륙 흐름을 전부 검증할 수 있다.

## Sphinx / 실기체 연결

```bash
# Sphinx 시뮬레이터
CONTROLLER=real DRONE_IP=10.202.0.1 uvicorn server.app:app
# 실기체 WiFi
CONTROLLER=real DRONE_IP=192.168.42.1 uvicorn server.app:app
```

## 저장소 구조

```
anafi_ai_control_plan.md   전체 구현 계획서 (배경지식·함정·Phase별 작업)
anafi-control/             제어 시스템 코드 (상세: anafi-control/README.md)
  ├ config.py              DRONE_IP/CONTROLLER 분기 + 안전 가드
  ├ drone/                 interface / mock / real / telemetry
  ├ server/                FastAPI+WebSocket 서버 + 제어 UI
  ├ scripts/               검증 스크립트
  └ environment.yml        conda 환경 정의
_docs/history/             작업 기록 (날짜별)
```

## 환경 (실측 확정)

- Ubuntu 22.04, conda env `olympe` (**Python 3.10**), `parrot-olympe 8.4.0`
- ⚠️ 기본 anaconda(3.13)로는 parrot-olympe 설치 불가 → 반드시 conda 3.10 환경 사용
- 자세한 환경 함정은 `anafi_ai_control_plan.md` 7절 참조

## 안전

- **긴급 착륙** (Space / 빨간 버튼): 즉시 착륙. 대부분의 정지는 이걸로.
- **모터 컷오프** (1초 hold): `Emergency` — 공중이면 추락. 오조작 방지 hold-to-confirm.
- 안전 가드: 스텝 10~100cm, 최대 고도 2.5m, 배터리 20% 미만 이동 거부.
