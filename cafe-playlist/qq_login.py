"""QQ 音乐扫码登录 — 获取并保存 Credential.

用法:
    python qq_login.py          # QQ 扫码登录（默认）
    python qq_login.py --wx     # 微信扫码登录
    python qq_login.py --check  # 检查已保存的凭证是否过期
    python qq_login.py --refresh # 刷新已过期的凭证
"""

import asyncio
import json
import sys
import os
from pathlib import Path

# ── 凭证文件路径 ──────────────────────────────
CREDENTIAL_FILE = Path(__file__).parent / "data" / "qq_credential.json"


async def do_login(login_type_str: str = "qq"):
    """扫码登录并保存凭证."""
    from qqmusic_api import Client
    from qqmusic_api.models.login import QRLoginType, QRCodeLoginEvents

    client = Client()
    login_api = client.login

    # 选择登录类型
    if login_type_str == "wx":
        login_type = QRLoginType.WX
        print("📱 微信扫码登录")
    else:
        login_type = QRLoginType.QQ
        print("📱 QQ 扫码登录")

    # 获取二维码
    print("正在获取二维码...")
    qr = await login_api.get_qrcode(login_type)

    # 保存二维码图片
    qr_dir = Path(__file__).parent / "data"
    qr_dir.mkdir(exist_ok=True)
    qr_path = qr_dir / f"login_qr.png"
    qr_path.write_bytes(qr.data)
    print(f"✅ 二维码已保存到: {qr_path}")
    print("   请用 QQ/微信 扫描这个二维码")

    # 自动打开二维码图片
    if sys.platform == "win32":
        os.startfile(str(qr_path))
    print()

    # 轮询等待扫码
    print("等待扫码...")
    while True:
        result = await login_api.check_qrcode(qr)
        event = result.event

        if event == QRCodeLoginEvents.SCAN:
            print("  ⏳ 等待扫码...")
        elif event == QRCodeLoginEvents.CONF:
            print("  📲 已扫码，请在手机上确认...")
        elif event == QRCodeLoginEvents.DONE:
            print("  ✅ 登录成功！")
            credential = result.credential
            break
        elif event == QRCodeLoginEvents.TIMEOUT:
            print("  ❌ 二维码已过期，请重新运行")
            return
        elif event == QRCodeLoginEvents.REFUSE:
            print("  ❌ 用户拒绝了登录")
            return
        else:
            print(f"  ❓ 未知状态: {event}")

        await asyncio.sleep(2)

    # 保存凭证
    if credential:
        cred_dict = credential.model_dump()
        CREDENTIAL_FILE.parent.mkdir(exist_ok=True)
        CREDENTIAL_FILE.write_text(json.dumps(cred_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n💾 凭证已保存到: {CREDENTIAL_FILE}")
        print(f"   musicid: {credential.musicid}")
        print(f"   musickey: {credential.musickey[:20]}...")
        print(f"   login_type: {credential.login_type}")


async def check_credential():
    """检查已保存的凭证是否有效."""
    from qqmusic_api import Client
    from qqmusic_api.models.request import Credential

    if not CREDENTIAL_FILE.exists():
        print("❌ 未找到凭证文件，请先运行 python qq_login.py 登录")
        return

    cred_data = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    credential = Credential(**cred_data)

    print(f"📋 凭证信息:")
    print(f"   musicid:    {credential.musicid}")
    print(f"   login_type: {credential.login_type}")
    print(f"   is_expired: {credential.is_expired()}")

    client = Client(credential=credential)
    expired = await client.login.check_expired()
    print(f"   服务端验证: {'❌ 已过期' if expired else '✅ 有效'}")

    if not expired:
        # 尝试获取用户信息
        try:
            user_info = await client.user.get_info()
            print(f"   用户昵称:  {user_info}")
        except Exception as e:
            print(f"   获取用户信息失败: {e}")


async def refresh_credential():
    """刷新已过期的凭证."""
    from qqmusic_api import Client
    from qqmusic_api.models.request import Credential

    if not CREDENTIAL_FILE.exists():
        print("❌ 未找到凭证文件，请先运行 python qq_login.py 登录")
        return

    cred_data = json.loads(CREDENTIAL_FILE.read_text(encoding="utf-8"))
    credential = Credential(**cred_data)

    client = Client(credential=credential)
    print("🔄 正在刷新凭证...")

    try:
        new_cred = await client.login.refresh_credential()
        cred_dict = new_cred.model_dump()
        CREDENTIAL_FILE.write_text(json.dumps(cred_dict, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ 凭证刷新成功！")
        print(f"   musicid: {new_cred.musicid}")
        print(f"   musickey: {new_cred.musickey[:20]}...")
    except Exception as e:
        print(f"❌ 刷新失败: {e}")
        print("   请重新运行 python qq_login.py 扫码登录")


def main():
    args = sys.argv[1:]

    if "--check" in args:
        asyncio.run(check_credential())
    elif "--refresh" in args:
        asyncio.run(refresh_credential())
    elif "--wx" in args:
        asyncio.run(do_login("wx"))
    else:
        asyncio.run(do_login("qq"))


if __name__ == "__main__":
    main()
