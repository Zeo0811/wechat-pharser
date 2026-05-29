from __future__ import annotations

import os
import subprocess

# 自带的免 SIP 4.1 取密钥扫描器源码（codec_ctx 方式）
_NATIVE_DIR = os.path.join(os.path.dirname(__file__), "native")
_CODEC_SRC = os.path.join(_NATIVE_DIR, "find_keys_codec.c")

# (stderr 子串, 人话提示) —— 命中第一个即返回。注意顺序：更具体的放前面。
_ERROR_HINTS = [
    ("没提取到密钥", "没提取到密钥：请确认微信已登录进账号（不是停在二维码/登录界面）后重试。"),
    ("no module named", "wechat-decrypt 解密依赖没装：进入仓库目录 "
                        "`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`"
                        "（见引导页第①步）。"),
    (".venv/bin/python3", "wechat-decrypt 仓库缺 venv：进入仓库目录建 venv 并装 requirements（见引导页第①步）。"),
    ("could not find process", "微信没在运行：请先打开并登录微信 4.x，再重试。"),
    ("task_for_pid", "无法读取微信进程内存：需要先对 WeChat.app 做 ad-hoc 重签名"
                     "（sudo codesign --force --deep --sign - /Applications/WeChat.app），"
                     "并用 sudo 运行扫描器。"),
    ("cc: command not found", "缺少编译器：请先装 Xcode Command Line Tools："
                              "xcode-select --install。"),
    ("not permitted", "权限不足：扫描内存需要 sudo，且 WeChat.app 需已重签名。"),
    ("command not found", "缺少依赖命令：检查是否装了 Xcode Command Line Tools / Python3。"),
]


def macos_steps(repo_dir: str, output_dir: str) -> list[dict]:
    """返回 macOS 上提取密钥→解库→导出→接回本项目的步骤列表。
    每项 {desc, command}。工具不替用户执行（含 sudo），只给确切命令。"""
    return [
        {"desc": "1. 退出微信（释放数据库锁，便于读取内存）",
         "command": "killall WeChat"},
        {"desc": "2. 对微信做 ad-hoc 重签名（允许读取其进程内存）",
         "command": "sudo codesign --force --deep --sign - /Applications/WeChat.app"},
        {"desc": "3. 重新打开微信并登录，然后编译密钥扫描器",
         "command": f"cc -O2 -o {repo_dir}/find_all_keys_macos "
                    f"{repo_dir}/find_all_keys_macos.c -framework Foundation"},
        {"desc": "4. 扫描微信进程内存提取数据库密钥（需 sudo）",
         "command": f"cd {repo_dir} && sudo ./find_all_keys_macos"},
        {"desc": "5. 用提取到的密钥解密所有数据库",
         "command": f"cd {repo_dir} && python3 decrypt_db.py"},
        {"desc": "6. 导出全部聊天为每会话一个 JSON 到输出目录",
         "command": f"cd {repo_dir} && python3 export_all_chats.py {output_dir}"},
        {"desc": "7. 转换成本项目可读的单数组 JSON，然后就能 qun-alpha serve 了",
         "command": f"qun-alpha import-export --src-dir {output_dir} "
                    f"--out-path exported_chats/all.json --groups-only"},
    ]


def classify_error(stderr: str) -> str:
    """把解密相关 stderr 翻成人话提示；未知错误原样带出。"""
    low = stderr.lower()
    for needle, hint in _ERROR_HINTS:
        if needle in low:
            return hint
    return f"未识别的错误，原文：{stderr.strip()}"


def admin_applescript(shell_cmd: str) -> str:
    """把 shell 命令包成可弹 macOS 管理员授权框的 AppleScript（osascript -e 的参数）。"""
    escaped = shell_cmd.replace("\\", "\\\\").replace('"', '\\"')
    return f'do shell script "{escaped}" with administrator privileges'


def codesign_steps() -> list[dict]:
    """① 一次性：退出微信 + ad-hoc 重签名。
    /Applications/WeChat.app 通常由当前用户拥有，codesign 不需要 sudo；
    用管理员反而会因 root 环境/取消而失败，故走 plain。"""
    return [
        {"desc": "退出微信", "argv": ["bash", "-lc", "killall WeChat || true"]},
        {"desc": "重签名微信",
         "argv": ["bash", "-lc",
                  "codesign --force --deep --sign - /Applications/WeChat.app"]},
    ]


def decrypt_export_steps(repo_dir: str, raw_out: str, export_path: str) -> list[dict]:
    """② 提密钥→解库→导出→转格式。提密钥需管理员，其余不需。
    用自带的 find_keys_codec（codec_ctx 方式，支持微信 4.1，免 SIP）。"""
    import sys
    # 导出/转格式步会 cd 到 wechat-decrypt 仓库，故输出路径必须绝对，否则会写错位置
    raw_out = os.path.abspath(raw_out)
    export_path = os.path.abspath(export_path)
    return [
        {"desc": "编译密钥扫描器",
         "argv": ["bash", "-lc",
                  f'cc -O2 -o {repo_dir}/find_keys_codec '
                  f'"{_CODEC_SRC}" -framework Foundation']},
        # 读 DB 元数据(salt+page1)用「当前用户身份」跑——用户进程有磁盘访问权限，
        # 能读受 TCC 保护的微信容器；osascript 管理员(root)反而会被 TCC 拦。
        {"desc": "读取数据库元数据",
         "argv": ["bash", "-lc",
                  f'cd {repo_dir} && ./find_keys_codec --dump-meta '
                  f'{repo_dir}/dbmeta.bin {os.path.expanduser("~")}']},
        # 扫内存提密钥需 root（task_for_pid）；只吃元数据文件，不碰 TCC 容器目录。
        {"desc": "提取数据库密钥（管理员，需一两分钟扫内存）",
         "argv": ["osascript", "-e", admin_applescript(
             f"cd {repo_dir} && ./find_keys_codec --scan {repo_dir}/dbmeta.bin")]},
        {"desc": "校验密钥",
         "argv": ["bash", "-lc",
                  f'grep -qE "[0-9a-f]{{16}}" {repo_dir}/all_keys.json '
                  f'|| {{ echo "没提取到密钥：请确认微信已登录进账号"'
                  f'"（不是停在二维码/登录界面）后重试" >&2; exit 7; }}']},
        {"desc": "解密数据库",
         "argv": ["bash", "-lc",
                  f'cd {repo_dir} && "{repo_dir}/.venv/bin/python3" decrypt_db.py']},
        {"desc": "导出聊天记录",
         "argv": ["bash", "-lc",
                  f'cd {repo_dir} && "{repo_dir}/.venv/bin/python3" '
                  f"export_all_chats.py {raw_out}"]},
        # 用 server 自己的 venv python 跑（bash 子进程 PATH 里没有 qun-alpha 命令）
        {"desc": "转换成本项目格式",
         "argv": ["bash", "-lc",
                  f'"{sys.executable}" -m qun_alpha.cli import-export '
                  f"--src-dir {raw_out} --out-path {export_path} --groups-only"]},
    ]


def default_runner(argv: list[str]) -> tuple[int, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=1800)
    return proc.returncode, (proc.stderr or proc.stdout or "")


def run_sequence(steps: list[dict], runner=default_runner, emit=lambda e: None) -> dict:
    """按序跑每步，跑前 emit 进度；任一步非零退出即抛人话错误并停止。"""
    total = len(steps)
    for i, step in enumerate(steps):
        emit({"stage": "decrypt", "current": i + 1, "total": total,
              "message": step["desc"]})
        code, output = runner(step["argv"])
        if code != 0:
            raw = (output or "").strip()
            raise RuntimeError(
                f"「{step['desc']}」失败：{classify_error(raw)}"
                + (f"（原始：{raw[:300]}）" if raw else ""))
    return {"steps": total}
