"""中文 GUI for the Hololive Dreams rhythm release.

首版只提供单曲打歌的安全封装和多人流程的明确占位状态。多人流程尚未
实现，因此 GUI 不会替用户点击成员、选曲、确认或结算按钮。
"""
from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

try:
    from .engine_runner import bundle_root, run_rhythm_session
except ImportError:
    from engine_runner import bundle_root, run_rhythm_session


class HololiveDreamsApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("hololive Dreams · 安全发布版")
        self.root.geometry("760x620")
        self.root.minsize(700, 560)
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.mode = tk.StringVar(value="single")
        self.duration = tk.StringVar(value=str(self._default_timeout()))
        self.live_ack = tk.BooleanVar(value=False)
        self.target_rounds = tk.StringVar(value="1")
        self.status = tk.StringVar(value="就绪：尚未接管游戏窗口")
        self.engine_status = tk.StringVar(value="引擎：复用现有 rhythm_game.run；未启动")
        self._build()
        self.root.after(100, self._drain_messages)
        self.root.protocol("WM_DELETE_WINDOW", self._close)

    def _config_path(self) -> Path:
        return bundle_root() / "domains" / "hololive_dreams" / "models" / "rhythm" / "rhythm_game_config.json"

    def _default_timeout(self) -> int:
        try:
            data = json.loads(self._config_path().read_text(encoding="utf-8-sig"))
            return int(float(data.get("timeout", 0)))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return 0

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="hololive Dreams 自动打歌", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, text="首版发布壳：单曲打歌可复用现有引擎；多人演出循环仍未实现。", foreground="#555").pack(anchor="w", pady=(2, 14))
        mode_box = ttk.LabelFrame(outer, text="功能")
        mode_box.pack(fill="x", pady=(0, 10))
        ttk.Radiobutton(mode_box, text="单曲打歌（已接入）", variable=self.mode, value="single", command=self._render_mode).pack(side="left", padx=12, pady=10)
        ttk.Radiobutton(mode_box, text="多人演出流程（未实现）", variable=self.mode, value="multi", command=self._render_mode).pack(side="left", padx=12, pady=10)

        self.single = ttk.LabelFrame(outer, text="单曲打歌")
        self.single.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(self.single)
        row.pack(fill="x", padx=12, pady=10)
        ttk.Label(row, text="会话时长（秒，0=不限时）").pack(side="left")
        ttk.Entry(row, textvariable=self.duration, width=10).pack(side="left", padx=(10, 24))
        ttk.Label(row, text="首版沿用当前配置，其余算法参数不在 GUI 修改").pack(side="left")
        ttk.Checkbutton(self.single, text="我已关闭游戏 AUTO，并确认实时打歌会发送按键", variable=self.live_ack, command=self._update_buttons).pack(anchor="w", padx=12, pady=(0, 10))
        buttons = ttk.Frame(self.single)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        self.dry_button = ttk.Button(buttons, text="开始观察/干跑（不发送按键）", command=lambda: self._start(False))
        self.dry_button.pack(side="left")
        self.live_button = ttk.Button(buttons, text="开始实时打歌（发送按键）", command=lambda: self._start(True))
        self.live_button.pack(side="left", padx=10)
        self.stop_button = ttk.Button(buttons, text="停止并释放按键", command=self._stop, state="disabled")
        self.stop_button.pack(side="right")

        self.multi = ttk.LabelFrame(outer, text="多人演出流程编排（状态占位）")
        ttk.Label(self.multi, text="未实现：演出 → GRADE → 等人 → Pickup → 沿用设置 → 打歌 → 多层奖励 → 玩同一个游戏。\n当前不会点击“决定成员/确认成员”，不会点选曲、结算或续玩按钮。", justify="left").pack(anchor="w", padx=12, pady=12)
        multi_row = ttk.Frame(self.multi)
        multi_row.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Label(multi_row, text="目标局数（仅预算字段）").pack(side="left")
        ttk.Entry(multi_row, textvariable=self.target_rounds, width=8).pack(side="left", padx=10)
        ttk.Button(multi_row, text="编排接口尚未可运行", state="disabled").pack(side="left", padx=10)

        status_box = ttk.LabelFrame(outer, text="运行状态")
        status_box.pack(fill="both", expand=True)
        ttk.Label(status_box, textvariable=self.status, wraplength=680).pack(anchor="w", padx=12, pady=(12, 5))
        ttk.Label(status_box, textvariable=self.engine_status, wraplength=680).pack(anchor="w", padx=12, pady=(0, 5))
        self.log = tk.Text(status_box, height=12, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._render_mode()
        self._update_buttons()

    def _render_mode(self) -> None:
        parent = self.single.master
        if self.mode.get() == "single":
            self.multi.pack_forget()
            self.single.pack(fill="x", pady=(0, 10), before=parent.winfo_children()[-1])
        else:
            self.single.pack_forget()
            self.multi.pack(fill="x", pady=(0, 10), before=parent.winfo_children()[-1])
        self._update_buttons()

    def _update_buttons(self) -> None:
        running = self.worker is not None and self.worker.is_alive()
        single = self.mode.get() == "single"
        self.dry_button.configure(state="disabled" if running or not single else "normal")
        self.live_button.configure(state="disabled" if running or not single or not self.live_ack.get() else "normal")
        self.stop_button.configure(state="normal" if running else "disabled")

    def _append_log(self, line: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", line.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self, live: bool) -> None:
        if live and not self.live_ack.get():
            messagebox.showwarning("需要确认", "请先确认已关闭 AUTO，并理解实时模式会发送按键。")
            return
        try:
            duration = float(self.duration.get().strip())
        except ValueError:
            messagebox.showerror("参数错误", "时长必须是数字；0 表示不限时。")
            return
        if duration < 0 or (duration != 0 and not 1 <= duration <= 1800):
            messagebox.showerror("参数错误", "时长必须为 0（不限时）或 1..1800 秒。")
            return
        self.stop_event.clear()
        self.pause_event.clear()
        self.status.set(("实时打歌" if live else "观察/干跑") + "：正在查找唯一 hololive-Dreams 窗口")
        self.engine_status.set("引擎：启动中；多人菜单控制器未加载")
        self._append_log(("开始实时打歌" if live else "开始观察/干跑") + f"，时长={duration:g}s")
        self.worker = threading.Thread(target=self._worker, args=(live, duration), daemon=True)
        self.worker.start()
        self._update_buttons()

    def _worker(self, live: bool, duration: float) -> None:
        try:
            result = run_rhythm_session(live=live, duration=duration, stop_event=self.stop_event, pause_event=self.pause_event, progress=lambda text: self.messages.put(("progress", text)))
            self.messages.put(("done", result))
        except Exception as error:
            self.messages.put(("error", str(error)))

    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self.messages.get_nowait()
                if kind == "progress":
                    self.engine_status.set("引擎：" + str(payload))
                    self._append_log(str(payload))
                elif kind == "done":
                    result = payload
                    self.status.set("已结束：" + str(result.get("reason", "unknown")))
                    self.engine_status.set("引擎：已清理输入调度并释放按键；结果仍为 unknown，未证明游戏判定")
                    self._append_log(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
                elif kind == "error":
                    self.status.set("运行失败/停止：" + str(payload))
                    self.engine_status.set("引擎：未完成；请查看日志，不要据此推断命中结果")
                    self._append_log("ERROR: " + str(payload))
        except queue.Empty:
            pass
        self._update_buttons()
        self.root.after(100, self._drain_messages)

    def _stop(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self.status.set("正在停止：等待引擎清理并释放按键")
            self.stop_event.set()
            self._append_log("已请求停止；等待现有引擎 finally 清理")

    def _close(self) -> None:
        if self.worker is not None and self.worker.is_alive():
            self._stop()
            self.root.after(100, self._close)
            return
        self.root.destroy()


def main() -> None:
    app_root = tk.Tk()
    HololiveDreamsApp(app_root)
    app_root.mainloop()


if __name__ == "__main__":
    main()

