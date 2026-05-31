from __future__ import annotations
from typing import Any, Callable, Optional
import json
import typer
from qun_alpha import extractor, notion_writer, orchestrator, wechat_import, decrypt_service, runners, doctor as doctor_mod
from qun_alpha.config import load_config

app = typer.Typer(help="群聊投资机会分析")


def run_pipeline(export_path: str, group_ids: list[str], start: int, end: int,
                 max_messages: int, prompt_version: str,
                 runner: Callable[[str], str],
                 cache_dir: Optional[str],
                 report_dir: Optional[str] = None) -> dict:
    return orchestrator.run_job(
        export_path=export_path, group_ids=group_ids, start=start, end=end,
        max_messages=max_messages, prompt_version=prompt_version,
        runner=runner, cache_dir=cache_dir, report_dir=report_dir,
    )


def _notion_client(cfg):
    from notion_client import Client
    return Client(auth=cfg.notion_token)


@app.command()
def analyze(
    export_path: str = typer.Option(..., help="wechat-decrypt 导出 JSON 路径"),
    groups: str = typer.Option(..., help="逗号分隔的 group_id"),
    start: int = typer.Option(0, help="起始 epoch 秒"),
    end: int = typer.Option(2_000_000_000, help="结束 epoch 秒（默认≈2033，等于无上界）"),
    config_path: str = typer.Option("config.json"),
    out_dir: str = typer.Option(None, "--out-dir",
                                help="报告输出目录（默认 ~/Downloads）"),
    model: str = typer.Option(None, "--model", help="本次用哪个后端: claude / codex"),
):
    """分析指定群的指定时间段，在 ~/Downloads 生成 Word+Markdown 报告。"""
    import os
    cfg = load_config(config_path)
    backend = model or cfg.model_backend
    runners.ensure_available(backend)   # CLI 不在 PATH → 提前人话报错
    report_dir = out_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    result = run_pipeline(
        export_path=export_path,
        group_ids=[g.strip() for g in groups.split(",") if g.strip()],
        start=start, end=end,
        max_messages=cfg.max_messages_per_chunk,
        prompt_version=cfg.prompt_version,
        runner=runners.get_runner(backend),
        cache_dir=cfg.cache_dir,
        report_dir=report_dir,
    )
    typer.echo(f"块={result['chunks']} 原始实体={result['raw_entities']} "
               f"公司={result['companies']} 人物={result['people']} 链接={result['links']}")
    typer.echo(f"已保存报告：{result['report_md']}")
    typer.echo(f"            {result['report_docx']}")


@app.command("init-notion")
def init_notion(config_path: str = typer.Option("config.json")):
    """在配置的父页面下创建 Companies/People/Links 三张数据库，并打印 database_id。"""
    cfg = load_config(config_path)
    client = _notion_client(cfg)
    ids = notion_writer.ensure_databases(client, parent_page_id=cfg.notion_parent_page_id)
    typer.echo("已创建数据库，请把下面的 id 填进 config.json：")
    for key, db_id in ids.items():
        typer.echo(f"  {key}: {db_id}")


def build_app():
    """构造 FastAPI app（供 serve 与测试用）。"""
    from qun_alpha.web import create_app
    return create_app()


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(7800),
    open_browser: bool = typer.Option(True, help="启动后自动开浏览器"),
):
    """启动本地 Web 操作台（localhost）。"""
    import threading
    import webbrowser
    import uvicorn
    application = build_app()
    if open_browser:
        url = f"http://{host}:{port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(application, host=host, port=port)


@app.command("import-export")
def import_export(
    src_dir: str = typer.Option(..., help="wechat-decrypt 导出目录（每会话一个 JSON）"),
    out_path: str = typer.Option("exported_chats/all.json", help="合并输出的单数组 JSON"),
    groups_only: bool = typer.Option(False, help="只导入群聊（跳过单聊）"),
) -> int:
    """把 wechat-decrypt 的导出目录转换成本项目可读的单数组 JSON。"""
    n = wechat_import.convert_export_dir(src_dir, out_path, groups_only=groups_only)
    typer.echo(f"已转换 {n} 个会话 → {out_path}")
    return n


@app.command("decrypt-guide")
def decrypt_guide(
    repo_dir: str = typer.Option("~/wechat-research/ylytdeng-wechat-decrypt",
                                 help="wechat-decrypt 仓库路径"),
    output_dir: str = typer.Option("exported_chats/raw",
                                   help="export_all_chats.py 的导出目录"),
) -> list:
    """打印 macOS 上提取密钥→解库→导出→接回本项目的确切命令（工具不替你跑 sudo）。"""
    import os
    steps = decrypt_service.macos_steps(
        repo_dir=os.path.expanduser(repo_dir), output_dir=output_dir)
    typer.echo("在 Mac 上依次执行（含 sudo 的需你亲自确认）：\n")
    for s in steps:
        typer.echo(s["desc"])
        typer.echo(f"    {s['command']}\n")
    return steps


def model_status(config_path: str = "config.json", set_backend: "str | None" = None) -> dict:
    import os
    available = runners.detect_available()
    if set_backend is not None:
        if set_backend not in runners.BACKENDS:
            raise ValueError(f"未知后端：{set_backend}（支持 {runners.BACKENDS}）")
        cfg = {}
        if os.path.exists(config_path):
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["model_backend"] = set_backend
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return {"available": available, "current": set_backend}
    current = "claude"
    if os.path.exists(config_path):
        from qun_alpha.config import load_config
        current = load_config(config_path).model_backend
    return {"available": available, "current": current}


@app.command()
def model(set: str = typer.Option(None, "--set", help="切换后端: claude / codex"),
          config_path: str = typer.Option("config.json")):
    """查看/切换模型后端（claude / codex）。"""
    info = model_status(config_path=config_path, set_backend=set)
    typer.echo(f"可用后端: {', '.join(info['available']) or '(未检测到 claude/codex)'}")
    typer.echo(f"当前后端: {info['current']}")


def render_doctor(checks) -> tuple[list, bool]:
    lines = []
    for c in checks:
        mark = "✅" if c.ok else "❌"
        line = f"{mark} {c.name}: {c.detail}"
        if not c.ok and c.fix:
            line += f"  → {c.fix}"
        lines.append(line)
    return lines, doctor_mod.all_ok(checks)


@app.command()
def doctor():
    """依赖体检：检查 macOS / Xcode CLT / Python / claude·codex / 安装目录。"""
    checks = doctor_mod.check_all()
    lines, ok = render_doctor(checks)
    for ln in lines:
        typer.echo(ln)
    if not ok:
        typer.echo("\n有阻塞项未满足，请按上面提示修复后重试。")
        raise typer.Exit(1)
    typer.echo("\n✅ 环境就绪。")


if __name__ == "__main__":
    app()
