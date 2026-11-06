from __future__ import annotations

import os
import queue
import subprocess
import threading
from datetime import date
from pathlib import Path
from tkinter import BooleanVar, StringVar, Text, Tk, filedialog, messagebox
from tkinter import ttk

from .errors import AuthRequiredError, InvalidInputError
from .merge import merge_archives
from .presets import ACCOUNT_PRESETS, preset_for_key, preset_for_label
from .redaction import redact_text
from .service import DownloadService
from .utils import parse_iso_date, validate_article_url


class ArchiveGui:
    def __init__(self, root: Tk, initial_preset_key: str | None = None) -> None:
        self.root = root
        self.root.title("微信公众号历史归档器")
        self.root.geometry("900x720")
        self.root.minsize(760, 620)
        self.service = DownloadService()
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.busy = False
        saved = self._load_settings()
        credential_aliases = [item.alias for item in self.service.credentials.summaries()]
        default_alias = (
            str(saved.get("alias") or "")
            or (credential_aliases[0] if len(credential_aliases) == 1 else "default")
        )

        saved_preset = preset_for_label(str(saved.get("preset") or ""))
        self.preset = StringVar(value=saved_preset.label if saved_preset else "自定义")
        self.url = StringVar(value=str(saved.get("url") or ""))
        self.alias = StringVar(value=default_alias)
        self.since = StringVar(value=str(saved.get("since") or "2000-01-01"))
        self.until = StringVar(value=str(saved.get("until") or date.today().isoformat()))
        self.output = StringVar(
            value=str(saved.get("output") or Path.home() / "Downloads" / "WeChatArticles")
        )
        self.merge_target = StringVar(value=str(saved.get("merge_target") or ""))
        self.auth_url = StringVar()
        self.include_temp = BooleanVar(value=bool(saved.get("include_temp", False)))

        self._build()
        launch_preset = preset_for_key(initial_preset_key)
        if launch_preset:
            self.preset.set(launch_preset.label)
            self._apply_preset()
        self.root.after(100, self._drain_events)

    def _build(self) -> None:
        outer = ttk.Frame(self.root, padding=18)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)

        ttk.Label(
            outer,
            text="粘贴任意一篇文章，点一次开始；凭据失效时，在微信内粘贴并打开自动复制的链接。",
            font=("Microsoft YaHei", 13, "bold"),
        ).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )

        ttk.Label(outer, text="常用公众号").grid(
            row=1, column=0, sticky="w", padx=(0, 12), pady=5
        )
        self.preset_box = ttk.Combobox(
            outer,
            textvariable=self.preset,
            state="readonly",
            values=("自定义", *(preset.label for preset in ACCOUNT_PRESETS)),
        )
        self.preset_box.grid(row=1, column=1, columnspan=2, sticky="ew", pady=5)
        self.preset_box.bind("<<ComboboxSelected>>", self._apply_preset)

        self._entry(outer, 2, "文章链接", self.url)
        self._entry(outer, 3, "凭据别名", self.alias)
        self._entry(outer, 4, "开始日期", self.since)
        self._entry(outer, 5, "结束日期", self.until)
        self._path_entry(outer, 6, "下载目录", self.output)
        self._path_entry(outer, 7, "合并到旧归档（可留空）", self.merge_target)

        options = ttk.Frame(outer)
        options.grid(row=8, column=1, columnspan=2, sticky="w", pady=(2, 10))
        ttk.Checkbutton(options, text="高级：常规目录失败时也扫描 Temp", variable=self.include_temp).pack(side="left")

        auth_frame = ttk.LabelFrame(
            outer,
            text="仅当凭据失效时：链接会自动复制，请发送到微信“文件传输助手”并在微信内打开",
            padding=10,
        )
        auth_frame.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(4, 10))
        auth_frame.columnconfigure(0, weight=1)
        self.auth_entry = ttk.Entry(auth_frame, textvariable=self.auth_url, state="readonly")
        self.auth_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(auth_frame, text="复制链接", command=self._copy_auth_url).grid(row=0, column=1, padx=(8, 0))

        controls = ttk.Frame(outer)
        controls.grid(row=10, column=0, columnspan=3, sticky="ew", pady=(0, 10))
        self.start_button = ttk.Button(controls, text="一键开始 / 继续归档", command=self._start)
        self.start_button.pack(side="left")
        self.open_button = ttk.Button(controls, text="打开输出目录", command=self._open_output)
        self.open_button.pack(side="left")
        ttk.Button(controls, text="清空日志", command=lambda: self.log.delete("1.0", "end")).pack(side="right")

        self.progress = ttk.Progressbar(outer, mode="indeterminate")
        self.progress.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(0, 8))

        self.log = Text(outer, wrap="word", height=18, font=("Microsoft YaHei UI", 10))
        self.log.grid(row=12, column=0, columnspan=3, sticky="nsew")
        outer.rowconfigure(12, weight=1)

        ttk.Label(
            outer,
            text="安全边界：不安装证书、不修改系统代理、不注入微信进程；凭据只保存在 Windows 凭据管理器。",
            foreground="#555555",
        ).grid(row=13, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def _apply_preset(self, _event: object | None = None) -> None:
        preset = preset_for_label(self.preset.get())
        if preset is None:
            return
        self.url.set(preset.sample_url)
        self.alias.set(preset.credential_alias)
        self.since.set("2000-01-01")
        if not self.output.get().strip():
            self.output.set(str(Path.home() / "Downloads" / "WeChatArticles"))
        self._append(
            f"已载入「{preset.label}」：入口文章、凭据别名和完整历史范围已填好。"
            "首次运行请在微信内完成一次授权。"
        )

    def _entry(self, parent: ttk.Frame, row: int, label: str, value: StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(parent, textvariable=value).grid(row=row, column=1, columnspan=2, sticky="ew", pady=5)

    def _path_entry(self, parent: ttk.Frame, row: int, label: str, value: StringVar) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        ttk.Entry(parent, textvariable=value).grid(row=row, column=1, sticky="ew", pady=5)
        ttk.Button(parent, text="选择…", command=lambda: self._choose_dir(value)).grid(
            row=row, column=2, padx=(8, 0), pady=5
        )

    def _choose_dir(self, value: StringVar) -> None:
        selected = filedialog.askdirectory(initialdir=value.get() or str(Path.home()))
        if selected:
            value.set(selected)

    def _copy_auth_url(self) -> None:
        value = self.auth_url.get().strip()
        if not value:
            messagebox.showinfo("尚无链接", "请先点击“一键开始 / 继续归档”。")
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._append("授权链接已复制。")

    def _prepare_auth_link(self, value: str) -> None:
        self.auth_url.set(value)
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self._append("授权链接已复制，并已尝试打开微信。请在微信“文件传输助手”中粘贴、发送并点击。")
        self._open_wechat()

    def _start(self) -> None:
        if self.busy:
            return
        url = self.url.get().strip()
        if not url:
            messagebox.showwarning("缺少输入", "请输入任意一篇目标公众号文章链接。")
            return
        output = self.output.get().strip()
        if not output:
            messagebox.showwarning("缺少输出目录", "请选择下载目录。")
            return
        try:
            validate_article_url(url)
            since = parse_iso_date(self.since.get().strip() or "2000-01-01", "开始日期")
            until = parse_iso_date(self.until.get().strip(), "结束日期")
            if since and until and since > until:
                raise InvalidInputError("开始日期不能晚于结束日期。")
        except InvalidInputError as exc:
            messagebox.showwarning("请检查输入", str(exc))
            return
        try:
            self._save_settings()
        except OSError:
            messagebox.showerror("无法保存设置", "请检查本地配置目录的写入权限。")
            return
        self._set_busy(True)
        self._append("开始检测。有效凭据将直接复用。")
        run_options = {
            "alias": self.alias.get().strip() or "default",
            "include_temp": self.include_temp.get(),
            "since": self.since.get().strip() or "2000-01-01",
            "until": self.until.get().strip() or None,
        }
        threading.Thread(
            target=self._run_archive,
            args=(url, output, self.merge_target.get().strip(), run_options),
            daemon=True,
        ).start()

    def _run_archive(
        self,
        url: str,
        output: str,
        merge_target: str,
        options: dict[str, object],
    ) -> None:
        try:
            alias = str(options["alias"])
            guide = self.service.auth_guide(url, alias)
            try:
                validation = self.service.validate_credential(url, alias)
            except AuthRequiredError:
                self.events.put(("auth_ready", str(guide["home_url"])))
                self.events.put(("log", "已保存凭据不存在或已失效，正在等待微信内授权。"))
                self.service.auth_capture(
                    url,
                    alias=alias,
                    watch_seconds=300,
                    since_minutes=15,
                    include_temp=bool(options["include_temp"]),
                    progress=lambda event: self.events.put(("log", self._capture_text(event))),
                )
            else:
                self.events.put(
                    ("log", f"已复用有效凭据 {validation['alias']}，无需重新打开微信。")
                )
            result = self.service.download_account(
                url,
                credential_alias=alias,
                since=options["since"],
                until=options["until"],
                max_pages=200,
                formats="html,md,json",
                output_dir=output,
                include_assets=True,
                progress=lambda event: self.events.put(("log", self._history_text(event))),
                resume=True,
            )
            self.events.put(("log", f"本轮结束：发现 {len(result.get('discovered', []))} 篇，"
                                     f"本次下载 {len(result.get('downloads', []))} 篇，"
                                     f"已有跳过 {result.get('resume', {}).get('skipped_existing', 0)} 篇。"))
            if merge_target:
                self.events.put(("log", "正在合并到旧归档……"))
                merged = merge_archives(Path(output), Path(merge_target))
                self.events.put(
                    (
                        "log",
                        f"合并完成：新增 {merged['added']}，已存在 {merged['already_present']}，"
                        f"冲突 {len(merged['conflicts'])}，报告已写入目标目录。",
                    )
                )
            self.events.put(("done", result))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("error", redact_text(str(exc))))

    def _capture_text(self, event: dict[str, object]) -> str:
        return (
            f"扫描 {event.get('scanned_files', 0)} 个近期文件，"
            f"发现 {event.get('candidate_count', 0)} 个候选。"
        )

    def _history_text(self, event: dict[str, object]) -> str:
        if event.get("phase") == "history_page":
            return f"历史第 {event.get('page')} 页：本页 {event.get('items')} 条。"
        if event.get("phase") == "download_article":
            action = "已有，跳过" if event.get("resumed") else "下载"
            return f"{action} {event.get('index')}/{event.get('total')}：{event.get('title')}"
        return str(event)

    def _drain_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append(str(payload))
                elif kind == "auth_url":
                    self.auth_url.set(str(payload))
                elif kind == "auth_ready":
                    self._prepare_auth_link(str(payload))
                elif kind == "done":
                    self._set_busy(False)
                    title, message, complete = completion_message(payload)
                    self._append(message)
                    if complete:
                        messagebox.showinfo(title, message)
                    else:
                        messagebox.showwarning(title, message)
                elif kind == "error":
                    self._set_busy(False)
                    self._append(f"失败：{payload}")
                    messagebox.showerror("操作失败", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)

    def _set_busy(self, value: bool) -> None:
        self.busy = value
        state = "disabled" if value else "normal"
        self.start_button.configure(state=state)
        if value:
            self.progress.start(12)
        else:
            self.progress.stop()

    def _open_output(self) -> None:
        path = Path(self.output.get()).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def _open_wechat(self) -> None:
        candidates = [
            Path(os.environ.get("PROGRAMFILES", "")) / "Tencent" / "Weixin" / "Weixin.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Tencent" / "Weixin" / "Weixin.exe",
        ]
        for path in candidates:
            if path.is_file():
                subprocess.Popen([str(path)])
                return
        try:
            os.startfile("weixin://")  # type: ignore[attr-defined]
        except OSError:
            self._append("未能自动打开微信，请手动打开桌面端。")

    def _settings_path(self) -> Path:
        return self.service.data_dir / "gui-settings.json"

    def _load_settings(self) -> dict[str, object]:
        from .utils import read_json

        value = read_json(self._settings_path(), {})
        return value if isinstance(value, dict) else {}

    def _save_settings(self) -> None:
        from .utils import atomic_write_json

        atomic_write_json(
            self._settings_path(),
            {
                "url": self.url.get().strip(),
                "preset": self.preset.get(),
                "alias": self.alias.get().strip() or "default",
                "since": self.since.get().strip(),
                "until": self.until.get().strip(),
                "output": self.output.get().strip(),
                "merge_target": self.merge_target.get().strip(),
                "include_temp": self.include_temp.get(),
            },
        )

    def _append(self, message: str) -> None:
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")


def main() -> None:
    root = Tk()
    ArchiveGui(root, initial_preset_key=os.environ.get("WECHAT_ARCHIVE_PRESET"))
    root.mainloop()


def completion_message(result: dict[str, object]) -> tuple[str, str, bool]:
    complete = bool(result.get("ok")) and bool(result.get("history_scan", {}).get("complete"))
    failures = len(result.get("failures", []))
    if complete and not failures:
        return "完成", "所选日期范围的公众号历史归档完成。HTML、Markdown、JSON 和图片已保存。", True
    return (
        "尚未全部完成",
        f"本轮下载失败 {failures} 篇。历史分页或文章下载尚未全部完成，请点击“一键开始 / 继续归档”重试。",
        False,
    )


if __name__ == "__main__":
    main()
