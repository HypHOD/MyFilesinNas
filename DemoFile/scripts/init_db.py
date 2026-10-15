"""建表 + 灌初始数据。可以重复执行，不会重复插入。

用法：
    cd ~/Documents/workbase/DemoFile && source .venv/bin/activate
    python scripts/init_db.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.core.db import Base, SessionLocal, engine
from app.models import SystemConfig, User

# (name, title, value) —— value 为 None 表示没默认值
#
# 数据来源：把 db/migration-sqlite 下所有迁移按 Flyway 的顺序在 sqlite3 里执行一遍，
# 再 dump 出 system_config 的最终状态，共 77 行。
#
# 为什么不能 grep 提取：
#   1. R__data.sql 是可重复迁移，Flyway 在所有 V 文件之后才跑它 ——
#      V32 删掉的 domain 又被它插了回来，最终库里是有的。
#   2. V26 的值是子查询算出来的，V9/V35 后面还有 UPDATE 改过值，grep 只能看到中间态。
SEED_ROWS: list[tuple[str, str, str | None]] = [
    ("fileClickMode", "默认文件点击模式", "dbclick"),
    ("authCode", "授权码", None),
    ("maxFileUploads", "最大同时上传文件数", "5"),
    ("onlyOfficeUrl", "onlineOffice 地址", "https://office.zfile.vip"),
    ("webdavEnable", "启用 WebDAV 服务", "false"),
    ("webdavProxy", "是否启用 WebDAV 服务器中转下载", "true"),
    ("webdavUsername", "WebDAV 账号", ""),
    ("webdavPassword", "WebDAV 密码", ""),
    ("allowPathLinkAnonAccess", "是否允许路径直链可直接访问", "false"),
    ("maxShowSize", "默认最大显示文件数", "1000"),
    ("loadMoreSize", "每次加载更多文件数", "50"),
    ("siteHomeName", "站点 Home 名称", "首页"),
    ("siteHomeLogo", "站点 Home Logo", None),
    ("siteHomeLogoLink", "站点 Logo 打开链接", "/"),
    ("siteHomeLogoTargetMode", "站点 Logo 链接打开方式", "_blank"),
    ("defaultSortField", "默认排序字段", "name"),
    ("defaultSortOrder", "默认排序字段", "asc"),
    ("linkLimitSecond", "限制直链下载秒数", "3600"),
    ("linkDownloadLimit", "限制直链下载次数", "10000"),
    ("faviconUrl", "网站 favicon 图标地址", None),
    ("linkExpireTimes", "短链过期时间设置", '[{ "value": 1, "unit": "d", "seconds": 86400 }]'),
    ("defaultSavePwd", "是否默认记住密码", "false"),
    ("onlyOfficeSecret", "OnlyOffice Secret，用于生成 JWT Token", None),
    ("enableHoverMenu", "是否启用悬浮菜单", "true"),
    ("accessIpBlocklist", "ip 黑名单", None),
    ("accessUaBlocklist", "ua 黑名单", None),
    ("loginImgVerify", "是否启用登录图片验证码", "false"),
    ("adminTwoFactorVerify", "是否为管理员启用双因素认证", "false"),
    ("siteAdminLogoTargetMode", "管理员页面点击 Logo 回到首页打开方式", "_blank"),
    ("siteAdminVersionOpenChangeLog", "管理员页面点击版本号打开更新日志", "true"),
    ("webdavAllowAnonymous", "是否允许匿名访问", "false"),
    ("loginLogMode", "登录日志模式", "ignoreAllPwd"),
    ("mobileLayout", "移动端布局", "full"),
    ("customOfficeSuffix", "Office 预览类型", "doc,docx,csv,xls,xlsx,ppt,pptx,xlsm"),
    ("guestIndexHtml", "匿名用户首页显示内容", ""),
    ("mobileFileClickMode", "移动端默认文件点击模式", "dbclick"),
    ("forceBackendAddress", "强制后端地址", ""),
    ("kkFileViewUrl", "kkFileView 地址", ""),
    ("customKkFileViewSuffix", "kkFileView 预览类型", "3dm,3ds,3mf,7z,bim,bpmn,brep,cf2,dcm,dng,doc,docx,dot,dotm,dotx,dps,drawio,dwf,dwfx,dwg,dwt,dxf,emf,eml,eps,et,ett,fbx,fcstd,flv,fodt,fods,glb,gltf,gzip,ifc,iges,jar,jfif,jpg,js,md,mkv,mov,mp3,mp4,mpeg,mpg,obj,odp,ods,odt,ofd,off,ogg,otp,ots,ott,pages,pdf,php,plt,ply,png,ppt,pptx,psd,py,rar,rm,rmvb,rtf,six,stl,step,svg,swf,tar,tga,tif,tiff,ts,tsv,txt,vsd,vsdx,wav,webm,webp,wmf,wmv,wps,wpt,wrl,xla,xlam,xls,xlsm,xlsx,xlt,xltm,xmind,xml,zip"),
    ("kkFileViewOpenMode", "kkFileView 预览方式", "iframe"),
    ("mobileShowSize", "移动端显示文件大小", "true"),
    ("secureLoginEntry", "安全登录入口", None),
    ("enableNormalDownloadConfirm", "普通下载是否启用确认弹窗", "true"),
    ("enablePackageDownloadConfirm", "打包下载是否启用确认弹窗", "true"),
    ("enableBatchDownloadConfirm", "批量下载是否启用确认弹窗", "true"),
    ("siteName", "站点名称", None),
    ("username", "管理员账号", None),
    ("password", "管理员密码", None),
    ("domain", "站点域名", None),
    ("customCss", "自定义 CSS", None),
    ("customJs", "自定义 JS (可用于统计代码)", None),
    ("tableSize", "表格大小", "small"),
    ("showDocument", "是否显示文档", "true"),
    ("announcement", "网站公告", None),
    ("showAnnouncement", "是否显示网站公告", "true"),
    ("layout", "页面布局", "full"),
    ("showLinkBtn", "是否显示生成直链按钮", "true"),
    ("showShortLink", "是否显示短链", "true"),
    ("showPathLink", "是否显示路径直链", "true"),
    ("installed", "是否已初始化安装", "false"),
    ("avatar", "头像地址", None),
    ("icp", "ICP 备案号", None),
    ("customVideoSuffix", "自定义视频文件后缀格式", None),
    ("customImageSuffix", "自定义图像文件后缀格式", None),
    ("customAudioSuffix", "自定义音频文件后缀格式", None),
    ("customTextSuffix", "自定义文本文件后缀格式", None),
    ("directLinkPrefix", "直链前缀地址", "directlink"),
    ("refererType", "直链 Referer 防盗链类型", "off"),
    ("refererAllowEmpty", "直链 Referer 是否允许为空", "true"),
    ("refererValue", "直链 Referer 值", None),
    ("loginVerifyMode", "登陆验证方式，支持验证码和 2FA 认证", "off"),
    ("loginVerifySecret", "登陆验证 Secret", None),
    ("rootShowStorage", "根目录是否显示所有存储源", "true"),
    ("frontDomain", "前端域名，前后端分离情况下需要配置", None),
    ("recordDownloadLog", "是否记录下载日志", "true"),
    ("showLogin", "是否在前台显示登陆按钮", "true"),
    ("rsaHexKey", "RSA 算法 HEX 格式密钥", None),
]

# (id, username, nickname, default_permissions)
# 这三行是 V28 + V46 两个迁移脚本建的，不是代码建的。
# id=1 的 username/password 故意留空：由安装向导填，Java 的 initAdminUser 是 update 不是 insert。
SEED_USERS: list[tuple[int, str | None, str | None, str | None]] = [
    (1, None, "管理员", "createShareLink,customShareKey"),
    (2, "guest", "匿名用户", None),
    (0, "template", "虚拟新用户", None),
]


def main() -> None:
    """幂等：已存在的 name / id 直接跳过，所以反复跑不会重复插入。"""
    Base.metadata.create_all(engine)

    with SessionLocal() as db:
        existing = set(db.scalars(select(SystemConfig.name)).all())
        for name, title, value in SEED_ROWS:
            if name in existing:
                continue
            db.add(SystemConfig(name=name, title=title, value=value))

        for uid, username, nickname, permissions in SEED_USERS:
            if db.get(User, uid) is not None:
                continue
            db.add(User(
                id=uid,
                username=username,
                nickname=nickname,
                enable=True,
                create_time=datetime.now(),
                default_permissions=permissions,
            ))

        db.commit()

    print("init_db done")


if __name__ == "__main__":
    main()
