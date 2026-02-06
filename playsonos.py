import soco
from soco import SoCo
import sys
import re
import html
import urllib.parse

# ================= 配置区域 =================
target_fav_name = "每日推荐"  # 🎯 只需修改这个参数即可切换频道!

# 【抓包发现的魔法数字】
# 抓包 parentID="10142064..." -> 这里的 2064 就是前缀
MAGIC_HEX_PREFIX = "2064" 
# ===========================================

try:
    # 1. 自动发现并连接设备
    print("正在搜索网络中的 Sonos 设备...")
    devices = soco.discover()
    
    if not devices:
        print("❌ 未发现任何 Sonos 设备")
        sys.exit(1)
    
    # 优先选择组长设备
    device = None
    for d in devices:
        if d.is_coordinator:
            device = d
            break
    
    # 如果没有组长,选择第一个设备
    if not device:
        device = list(devices)[0]
    
    print(f"连接到: {device.player_name} ({device.ip_address})")

    # 自动切换到组长
    if device.group.coordinator.uid != device.uid:
        print(f"👉 切换到组长: {device.group.coordinator.player_name}")
        sonos = device.group.coordinator
    else:
        sonos = device

    # 2. 从收藏夹提取所需参数 (UUID, SERVICE_ID, ACCOUNT_ID)
    print(f"正在分析收藏夹 '{target_fav_name}'...")
    favorites = sonos.music_library.get_sonos_favorites()
    target_uuid = None
    target_title = ""
    MY_SERVICE_ID = None
    MY_ACCOUNT_ID = None
    
    for fav in favorites:
        if target_fav_name.lower() in fav.title.lower():
            # 提取元数据
            raw_meta = getattr(fav, 'resource_meta_data', '') or getattr(fav, 'metadata', '')
            clean_meta = html.unescape(raw_meta)
            print(clean_meta)
            
            # 提取 UUID (格式: 2b123ac0-...)
            uuid_match = re.search(r'id="[^"]*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', clean_meta)
            if uuid_match:
                target_uuid = uuid_match.group(1)
                target_title = fav.title
                print(f"✅ 提取到列表 UUID: {target_uuid}")
                print(f"✅ 提取到列表 Title: {target_title}")
            
            # 提取 ACCOUNT_ID (从 <desc> 标签)
            account_match = re.search(r'<desc[^>]*>(SA_RINCON[^<]+)</desc>', clean_meta)
            if account_match:
                MY_ACCOUNT_ID = account_match.group(1)
                print(f"✅ 自动提取 ACCOUNT_ID: {MY_ACCOUNT_ID}")
            
            # 提取 SERVICE_ID (从 ACCOUNT_ID 中提取数字部分)
            if MY_ACCOUNT_ID:
                service_match = re.search(r'SA_RINCON(\d+)_', MY_ACCOUNT_ID)
                if service_match:
                    MY_SERVICE_ID = service_match.group(1)
                    print(f"✅ 自动提取 SERVICE_ID: {MY_SERVICE_ID}")
            
            break
    
    # 验证是否成功提取所有必需参数
    if not target_uuid or not MY_SERVICE_ID or not MY_ACCOUNT_ID:
        print("❌ 无法提取必需参数:")
        if not target_uuid:
            print("   - 缺少 UUID")
        if not MY_SERVICE_ID:
            print("   - 缺少 SERVICE_ID")
        if not MY_ACCOUNT_ID:
            print("   - 缺少 ACCOUNT_ID")
        print(f"\n请检查收藏夹 '{target_fav_name}' 是否存在。")
        sys.exit(1)

    # 3. 构造 URI (基于抓包数据修正)
    print("正在构造播放 URI...")
    
    # URL 编码 UUID (虽然 UUID 一般不需要编码，但为了保险)
    safe_uuid = urllib.parse.quote(target_uuid)
    
    # 构造格式: x-rincon-cpcontainer:1006[Hex前缀][UUID]
    # 1006 是 Container 的标准头
    # 2064 是从抓包 parentID 10142064... 里推导出来的
    container_uri = f"x-rincon-cpcontainer:1006{MAGIC_HEX_PREFIX}{safe_uuid}?sid={MY_SERVICE_ID}&flags=8300&sn={MY_ACCOUNT_ID}"
    
    print(f"   构造的 URI: {container_uri}")

    # 4. 构造 Metadata
    # 注意：这里 class 必须是 playlistContainer
    didl_metadata = (
        f'<DIDL-Lite xmlns:dc="http://purl.org/dc/elements/1.1/" '
        f'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        f'xmlns:r="urn:schemas-rinconnetworks-com:metadata-1-0/" '
        f'xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/">'
        f'<item id="1006{MAGIC_HEX_PREFIX}{safe_uuid}" parentID="root" restricted="true">'
        f'<dc:title>{target_title}</dc:title>'
        f'<upnp:class>object.container.playlistContainer</upnp:class>'
        f'<desc id="cdudn" nameSpace="urn:schemas-rinconnetworks-com:metadata-1-0/">'
        f'{MY_ACCOUNT_ID}'
        f'</desc>'
        f'</item>'
        f'</DIDL-Lite>'
    )

    # 5. 发送指令
    print("正在发送 AddURIToQueue...")
    sonos.clear_queue()
    
    # 使用底层调用
    sonos.avTransport.AddURIToQueue([
        ('InstanceID', 0),
        ('EnqueuedURI', container_uri),
        ('EnqueuedURIMetaData', didl_metadata),
        ('DesiredFirstTrackNumberEnqueued', 0),
        ('EnqueueAsNext', 1)
    ])
    
    print("✅ 入队成功！")
    print("播放中...")
    sonos.play_from_queue(0)

except Exception as e:
    print(f"❌ 失败: {e}")
    if "800" in str(e):
        print("\n💡 分析: 如果还是 800 错误，尝试把脚本里的 MAGIC_HEX_PREFIX 改成 '6028' (抓包里的 flags) 试试。")