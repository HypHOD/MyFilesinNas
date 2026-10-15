"""API 冒烟测试：health / program 启停 / config / rss / bangumi。

所有 TestClient 共享同一临时 cwd 下的 data/data.db（lifespan 建表），
因此断言避免依赖默认配置值或跨测试遗留状态。
"""

from fastapi.testclient import TestClient

from main import create_app


def test_health_ok():
    with TestClient(create_app()) as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["db_ok"] is True


def test_program_start_stop():
    with TestClient(create_app()) as client:
        # 归零，避免上一用例遗留的运行状态（配置非默认时 lifespan 会自动启动）
        client.post("/api/v1/program/stop")
        assert client.get("/api/v1/program/status").json()["status"] is False

        resp = client.post("/api/v1/program/start")
        assert resp.status_code == 200
        assert client.get("/api/v1/program/status").json()["status"] is True

        resp = client.post("/api/v1/program/stop")
        assert resp.status_code == 200
        assert client.get("/api/v1/program/status").json()["status"] is False


def test_config_get_masks_secrets_and_patch_roundtrip():
    with TestClient(create_app()) as client:
        body = client.get("/api/v1/config").json()
        # 敏感字段以掩码返回
        assert body["downloader"]["password"] == "********"

        body["program"]["rss_time"] = 1234
        resp = client.patch("/api/v1/config", json=body)
        assert resp.status_code == 200
        assert resp.json()["program"]["rss_time"] == 1234
        # 掩码原样回传 → 真实值未被覆盖
        assert resp.json()["downloader"]["password"] == "********"

        # 重新 GET 验证磁盘状态
        body = client.get("/api/v1/config").json()
        assert body["program"]["rss_time"] == 1234


def test_rss_crud_api():
    url = "https://example.com/rss/crud-test"
    with TestClient(create_app()) as client:
        resp = client.post("/api/v1/rss/add", json={"name": "Test", "url": url})
        assert resp.status_code == 200

        # 重复 URL 拒绝
        resp = client.post("/api/v1/rss/add", json={"name": "Dup", "url": url})
        assert resp.status_code == 400

        items = client.get("/api/v1/rss").json()
        rss_id = next(i["id"] for i in items if i["url"] == url)

        assert client.patch(f"/api/v1/rss/disable/{rss_id}").status_code == 200
        assert client.patch(f"/api/v1/rss/enable/{rss_id}").status_code == 200
        assert client.delete(f"/api/v1/rss/delete/{rss_id}").status_code == 200

        items = client.get("/api/v1/rss").json()
        assert all(i["url"] != url for i in items)


def test_bangumi_crud_api():
    with TestClient(create_app()) as client:
        resp = client.post(
            "/api/v1/bangumi/add",
            json={"official_title": "冒烟番剧", "title_raw": "Smoke Anime"},
        )
        assert resp.status_code == 200

        items = client.get("/api/v1/bangumi").json()
        b = next(i for i in items if i["title_raw"] == "Smoke Anime")

        resp = client.patch(
            f"/api/v1/bangumi/update/{b['id']}", json={"episode_offset": 3}
        )
        assert resp.status_code == 200
        assert (
            client.get(f"/api/v1/bangumi/get/{b['id']}").json()["episode_offset"] == 3
        )

        assert client.delete(f"/api/v1/bangumi/delete/{b['id']}").status_code == 200
        items = client.get("/api/v1/bangumi").json()
        assert all(i["title_raw"] != "Smoke Anime" for i in items)
