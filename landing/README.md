# Railway 落地页（静态）

纯静态引导页，模式 X 的线上入口。本地工具的真实 UI 在用户机器的 `qun-alpha serve`（localhost），此页只负责引导安装与跑通。

## 部署到 Railway（静态）

1. 新建 Railway 项目，指向本仓库。
2. 用任意静态服务器托管 `landing/` 目录，例如设置启动命令：
   ```
   npx serve landing -l $PORT
   ```
   或用 Railway 的 Static Site 模板，root 设为 `landing/`。
3. 此页不含后端、不接触任何微信数据。

> 后续若做模式 Y（线上操作台远程驱动本地 agent），再在此基础上加鉴权与本地 agent 配对。
