"""
杭电图书馆预约系统 API 模块。

认证使用杭电 CAS SSO（统一身份认证）：
- AES-128-ECB 加密密码
- CAS ticket 重定向验证
- 认证后获得 zhishulib.com 会话

使用示例：:

    from api.client import APIClient
    from api.auth import AuthAPI
    from api.seats import SeatAPI
    from api.rooms import RoomAPI

    client = APIClient(base_url="https://hdu.huitu.zhishulib.com")
    auth = AuthAPI(client)
    seat_api = SeatAPI(client)
    room_api = RoomAPI(client)

    # 登录
    auth.login_by_password("学号", "密码")

    # 获取区域
    areas = seat_api.get_areas()

    # 查询座位
    seats = seat_api.get_seats(area_id=1)
"""
from .client import APIClient
from .auth import AuthAPI
from .seats import SeatAPI, SeatArea, SeatInfo, BookingResult, SeatMapInfo
from .rooms import RoomAPI, RoomInfo, RoomBookingResult

__all__ = [
    "APIClient",
    "AuthAPI",
    "SeatAPI",
    "SeatArea",
    "SeatInfo",
    "BookingResult",
    "SeatMapInfo",
    "RoomAPI",
    "RoomInfo",
    "RoomBookingResult",
]
