"""MockController 단독 검증 — 드론/서버 없이 컨트롤러 로직과 ±10% drift 확인.

실행: anafi-control/ 에서  python scripts/test_mock_controller.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drone.mock import MockController


def main():
    c = MockController()
    assert c.connect()
    t = c.get_telemetry()
    assert t.connected and t.flying_state == "landed"

    # hovering 아닐 때 move 거부되는지
    assert c.move_cm(right_cm=30) is False, "landed 상태에서 move 가 거부돼야 함"

    assert c.takeoff()
    assert c.get_telemetry().flying_state == "hovering"

    # 이동 + drift 확인
    assert c.move_cm(forward_cm=50, right_cm=30, up_cm=20)
    t = c.get_telemetry()
    cmd, act = t.last_cmd, t.last_actual
    print("명령값 :", cmd)
    print("실측값 :", act)
    for axis in ("forward_cm", "right_cm", "up_cm"):
        err_ratio = abs(act[axis] - cmd[axis]) / cmd[axis]
        assert err_ratio <= 0.10 + 1e-9, f"{axis} drift {err_ratio:.3f} > 10%"
        print(f"  {axis}: 오차 {act[axis]-cmd[axis]:+.1f}cm ({err_ratio*100:.1f}%)")

    # 누적 위치 / 복귀
    print("이동 후 추정 위치:", t.est_x_cm, t.est_y_cm, t.est_z_cm)
    assert c.return_home_initial()
    t = c.get_telemetry()
    print("복귀 후 추정 위치:", round(t.est_x_cm, 1), round(t.est_y_cm, 1))

    # 고도 이동
    assert c.go_to_altitude(2.0)
    print("고도 이동 후:", round(c.get_telemetry().altitude_m, 2), "m")

    assert c.land()
    assert c.get_telemetry().flying_state == "landed"
    print("\n✅ MockController 전체 시나리오 통과")


if __name__ == "__main__":
    main()
