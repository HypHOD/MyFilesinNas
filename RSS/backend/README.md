
backend/src/
  ├── main.py                 FastAPI 入口：create_app + lifespan（启停编排）
  └── module/
      ├── api/                REST 层：program(启停) / rss / bangumi / config / health + deps
      ├── core/               编排层：AppContext(组合根) + Scheduler + loops(tick 函数)
      ├── manager/            重命名业务：Renamer
      ├── rss/                追番业务：RSSAnalyser(建订阅) + RSSEngine(拉取→匹配→投递)
      ├── parser/             解析层：tokenizer → ParsedRelease；TorrentParser(文件名反向解析)
      ├── downloader/         下载器层：Protocol 抽象 + qb/mock 实现 + DownloadClient 门面
      ├── network/            HTTP 基础层：共享客户端 + 站点解析(mikan)
      ├── database/           数据层：engine + Database(会话+三 repo) + repo 实现
      ├── models/             SQLModel 模型：Bangumi / RSSItem / Torrent / 配置
      └── conf/               配置单例 + 日志
