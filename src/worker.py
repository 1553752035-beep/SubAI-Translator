# -*- coding: utf-8 -*-
"""任务进程隔离：把 pipeline 跑在独立子进程里。

为什么必须做
------------
本项目重度依赖三套**原生库**：
- CTranslate2（faster-whisper 的推理后端，C++）
- sherpa-onnx（SenseVoice/Paraformer 推理，C++）
- onnxruntime（RapidOCR）

原生库的崩溃（段错误、CUDA 驱动不兼容、内存越界）**不走 Python 异常机制**，
try/except 完全拦不住 —— 进程直接消失。原实现把 run_pipeline 放在
FastAPI 的线程池里跑，意味着：

    一个视频的 ASR 让 CTranslate2 段错误
    → 整个 subai-backend.exe 消失
    → 同时运行的其他任务全部丢失
    → 桌面端 UI 断开连接，用户看到「后端离线」

隔离之后同一个崩溃只是「某个任务失败」，服务继续活着。

设计要点
--------
1. **子进程只做重活，结果通过文件+stdout 回传**。
   不传大对象（字幕行、音频缓冲），避免序列化开销和管道阻塞。
2. **进度靠 stdout 的行协议**。子进程按行输出 `@@PROGRESS\x1f<json>`，
   父进程读 stdout 转发给现有 progress_callback。这样进度条不需要改。
3. **崩溃要能区分「被杀」「段错误」「正常失败」**。
   退出码 -11 是 Linux 段错误，Windows 上是 0xC0000005 转成的大正数；
   两者都要识别成「原生崩溃」并给出可执行提示，而不是笼统的「任务失败」。
4. **取消走 terminate**。子进程里轮询取消标记没有意义（它卡在 C++ 里根本
   回不来），只能杀进程。这也是隔离带来的额外好处：卡死的任务能真的停下来。
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from typing import Callable, Optional

# 子进程与父进程之间的行协议前缀（用 \x1f 分隔，避免和普通日志混淆）
PROGRESS_PREFIX = "@@PROGRESS\x1f"
RESULT_PREFIX = "@@RESULT\x1f"
STATS_PREFIX = "@@STATS\x1f"
ERROR_PREFIX = "@@ERROR\x1f"

# Windows 上原生崩溃会表现为这些 NTSTATUS 值（转成有符号 int 后）
_CRASH_CODES = {
    -11: "SIGSEGV（段错误）",
    -6: "SIGABRT（断言失败/异常终止）",
    -4: "SIGILL（非法指令）",
    -8: "SIGFPE（浮点异常）",
    -1073741819: "STATUS_ACCESS_VIOLATION（访问冲突，常见于原生库崩溃）",
    -1073741571: "STATUS_STACK_OVERFLOW（栈溢出）",
    -1073740791: "STATUS_STACK_BUFFER_OVERRUN",
    -1073741676: "STATUS_INTEGER_DIVIDE_BY_ZERO",
    -1073741510: "STATUS_CONTROL_C_EXIT（被中断）",
    -1073741816: "STATUS_INVALID_HANDLE",
}


def describe_exit(code: Optional[int]) -> str:
    """把退出码翻成人话。识别不出就返回原始值。"""
    if code is None:
        return "未知（进程未返回退出码）"
    c = int(code)
    # Windows 的退出码常以无符号大数呈现（0xC0000005 = 3221225477）
    if c > 0x80000000:
        signed = c - 0x100000000
        if signed in _CRASH_CODES:
            return _CRASH_CODES[signed]
    if c in _CRASH_CODES:
        return _CRASH_CODES[c]
    return "退出码 %d" % c


def is_crash(code: Optional[int], stderr: Optional[str] = None) -> bool:
    """判断是否是原生崩溃（而非 Python 异常导致的正常失败）。

    **必须同时看退出码和 stderr，只靠退出码会漏判。**
    实测（Windows / Python 3.14）：
    - `ctypes.memset(0, 0, 1)` 空指针写 -> 退出码只是 **1**
    - 真正的信号在 stderr：`Windows fatal exception: access violation`
    如果只查退出码表，这类崩溃会被误判成「普通 Python 报错」，
    从而丢掉「原生库崩了，换引擎重试」这条最有用的提示。

    faulthandler 的输出也走 stderr，是判断崩溃最可靠的信号。
    """
    if code is None:
        return True
    c = int(code)
    if c > 0x80000000:
        c = c - 0x100000000
    if c in _CRASH_CODES:
        return True
    if stderr:
        low = stderr.lower()
        for kw in ("windows fatal exception", "fatal exception",
                   "segmentation fault", "access violation",
                   "stack overflow", "abort() has been called"):
            if kw in low:
                return True
    return False


def _worker_main(payload_path: str, result_path: str) -> int:
    """子进程入口。payload/result 都是 JSON 文件。"""
    with open(payload_path, "r", encoding="utf-8") as f:
        payload = json.load(f)

    def _emit(prefix: str, obj) -> None:
        try:
            sys.stdout.write(prefix + json.dumps(obj, ensure_ascii=False) + "\n")
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass

    def progress(p: float, msg: str = "") -> None:
        _emit(PROGRESS_PREFIX, {"progress": p, "message": msg})

    stats: dict = {}
    try:
        from src.pipeline import run_pipeline
        files = run_pipeline(
            video=payload["video"],
            mode=payload.get("mode", "asr"),
            source_lang=payload.get("source_lang"),
            target_lang=payload.get("target_lang", "en"),
            glossary=payload.get("glossary"),
            terms_file=payload.get("terms_file"),
            db_path=payload.get("db_path"),
            output_format=payload.get("output_format", "srt"),
            sample_fps=payload.get("sample_fps"),
            progress_callback=progress,
            stats=stats,
            from_srt=payload.get("from_srt"),
            # [2026-10-25] 逐任务指定 ASR 引擎；缺省 None 表示用全局配置。
            asr_engine=payload.get("asr_engine"),
        )
        _emit(RESULT_PREFIX, {"files": files or []})
        _emit(STATS_PREFIX, stats)
        return 0
    except BaseException as e:  # noqa: BLE001 - 必须兜住，否则退出码说明不了问题
        import traceback
        _emit(ERROR_PREFIX, {
            "type": type(e).__name__,
            "message": str(e)[:2000],
            "traceback": traceback.format_exc()[-4000:],
        })
        return 1


def run_isolated(
    payload: dict,
    progress_callback: Optional[Callable] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    stats_out: Optional[dict] = None,
    timeout: float = 6 * 3600,
    poll_interval: float = 0.2,
) -> list:
    """在独立子进程里跑 pipeline。

    返回输出文件列表；失败抛 RuntimeError（消息里说明是崩溃还是普通失败）。

    参数
    ----
    stats_out : 传入 dict 时，子进程的 stats 会合并进去（与旧调用方式兼容）
    """
    tmpdir = tempfile.mkdtemp(prefix="subai_worker_")
    payload_path = os.path.join(tmpdir, "payload.json")
    result_path = os.path.join(tmpdir, "result.json")
    with open(payload_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"

    # -X faulthandler：原生崩溃时把 Python 栈打到 stderr，便于定位是哪一步
    cmd = [sys.executable, "-X", "faulthandler", "-u", "-c",
           "import sys; sys.path.insert(0, %r); "
           "from src.worker import _worker_main; "
           "sys.exit(_worker_main(%r, %r))"
           % (_project_root(), payload_path, result_path)]

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        # 独立进程组：取消时能连同它 fork 出的子进程一起杀掉
        **_process_group_kwargs(),
    )

    collected = {"files": None, "stats": {}, "error": None}
    stderr_buf: list = []
    cancelled = False

    def _read_stdout() -> None:
        for line in proc.stdout:  # type: ignore[union-attr]
            s = line.rstrip("\n")
            if s.startswith(PROGRESS_PREFIX):
                try:
                    d = json.loads(s[len(PROGRESS_PREFIX):])
                    if progress_callback:
                        progress_callback(d.get("progress", 0.0), d.get("message", ""))
                except Exception:  # noqa: BLE001
                    pass
            elif s.startswith(RESULT_PREFIX):
                try:
                    collected["files"] = json.loads(s[len(RESULT_PREFIX):]).get("files") or []
                except Exception:  # noqa: BLE001
                    pass
            elif s.startswith(STATS_PREFIX):
                try:
                    collected["stats"] = json.loads(s[len(STATS_PREFIX):])
                except Exception:  # noqa: BLE001
                    pass
            elif s.startswith(ERROR_PREFIX):
                try:
                    collected["error"] = json.loads(s[len(ERROR_PREFIX):])
                except Exception:  # noqa: BLE001
                    pass
            else:
                # 普通日志行：原样打出来（用户看日志能对上）
                try:
                    print(s)
                except Exception:  # noqa: BLE001
                    pass

    def _read_stderr() -> None:
        for line in proc.stderr:  # type: ignore[union-attr]
            stderr_buf.append(line)
            if len(stderr_buf) > 400:
                del stderr_buf[:200]

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    deadline = time.time() + timeout
    while True:
        if proc.poll() is not None:
            break
        if should_cancel and should_cancel():
            cancelled = True
            _terminate(proc)
            break
        if time.time() > deadline:
            _terminate(proc)
            raise RuntimeError("任务超时（%.0f 秒），子进程已终止" % timeout)
        time.sleep(poll_interval)

    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        _kill(proc)
    t_out.join(timeout=10)
    t_err.join(timeout=10)

    code = proc.returncode
    _cleanup(tmpdir)

    if stats_out is not None and collected["stats"]:
        try:
            stats_out.update(collected["stats"])
        except Exception:  # noqa: BLE001
            pass

    if cancelled:
        raise RuntimeError("任务已取消")

    if collected["error"]:
        e = collected["error"]
        raise RuntimeError("%s: %s" % (e.get("type", "错误"), e.get("message", "")))

    if code != 0:
        reason = describe_exit(code)
        _all_err = "".join(stderr_buf)
        tail = "".join(stderr_buf[-20:]).strip()
        if is_crash(code, _all_err):
            # 从 stderr 认出具体崩溃类型，比只报退出码有用得多
            _low = _all_err.lower()
            if "access violation" in _low:
                reason = "原生崩溃：访问冲突（access violation）"
            elif "segmentation fault" in _low:
                reason = "原生崩溃：段错误（segmentation fault）"
            elif "stack overflow" in _low:
                reason = "原生崩溃：栈溢出（stack overflow）"
            elif "abort() has been called" in _low:
                reason = "原生崩溃：abort()（断言失败）"
            hint = (
                " 这是**原生库崩溃**（CTranslate2 / sherpa-onnx / onnxruntime 之一），"
                "不是普通报错。已隔离处理，后端服务未受影响。"
                " 建议：① 换 whisper 引擎重试（SUBAI_ASR_ENGINE=whisper）；"
                "② 关闭降噪/说话人分离再试；③ 如果是 CUDA 设备，改用 CPU 重试。"
            )
            raise RuntimeError("任务进程崩溃：%s。%s\n--- stderr 末尾 ---\n%s"
                               % (reason, hint, tail[-1500:]))
        raise RuntimeError("任务进程异常退出：%s\n--- stderr 末尾 ---\n%s"
                           % (reason, tail[-1500:]))

    if collected["files"] is None:
        raise RuntimeError("子进程正常退出但没有返回结果（可能被提前中断）")
    return collected["files"]


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _process_group_kwargs() -> dict:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)}
    return {"start_new_session": True}


def _terminate(proc: subprocess.Popen) -> None:
    """先礼后兵：terminate，超时再 kill。"""
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass


def _kill(proc: subprocess.Popen) -> None:
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def _cleanup(tmpdir: str) -> None:
    import shutil
    try:
        shutil.rmtree(tmpdir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
