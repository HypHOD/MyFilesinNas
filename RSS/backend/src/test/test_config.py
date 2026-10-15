from module.conf.config import CONFIG_PATH, Settings


def test_config_file_created_on_first_use():
    # conftest 已把 cwd 切到临时目录，Settings() 应把默认配置落盘
    Settings()
    assert CONFIG_PATH.exists()


def test_settings_save_load_roundtrip():
    s = Settings()
    s.program.rss_time = 123
    s.save()

    s2 = Settings()
    assert s2.program.rss_time == 123
    assert s2.downloader.type == "qbittorrent"
