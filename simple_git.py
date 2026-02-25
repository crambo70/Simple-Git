#!/usr/bin/env python3
"""
Simple Git — A one-button Pull/Push tool for images/portfolio.

Reads config.json for repo settings. On first run, clones the remote
repo using sparse checkout so only images/portfolio is synced to disk.
"""

import json
import subprocess
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from pathlib import Path
from datetime import datetime

CONFIG_FILENAME = "config.json"
TRACKED_PATH = "images/portfolio"


def btn(parent, text, callback, **kwargs):
    return ttk.Button(parent, text=text, command=callback, **kwargs)

DEFAULT_CONFIG = {
    "remote_url": "",
    "repo_path": "",
    "branch": "main",
    "commit_message": "Update portfolio via Simple Git",
}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def find_config():
    return Path(__file__).resolve().parent / CONFIG_FILENAME


def load_config():
    path = find_config()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    with open(path, "r") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    path = find_config()
    with open(path, "w") as f:
        json.dump(cfg, f, indent=4)


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(repo_path, *args, timeout=120):
    """Run a git command inside repo_path. Returns (ok, stdout, stderr)."""
    cmd = ["git", "-C", str(repo_path)] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


def test_remote(remote_url, timeout=15):
    """Test connectivity to remote_url without needing a local repo."""
    cmd = ["git", "ls-remote", "--heads", remote_url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
        if r.returncode == 0:
            return True, "Connection successful"
        return False, r.stderr.strip() or "Connection failed"
    except subprocess.TimeoutExpired:
        return False, "Connection timed out"
    except Exception as e:
        return False, str(e)


def clone_sparse(remote_url, repo_path, branch, tracked_path):
    """Clone using sparse checkout limited to tracked_path."""
    cmd = [
        "git", "clone",
        "--filter=blob:none",
        "--no-checkout",
        remote_url,
        str(repo_path),
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
        if r.returncode != 0:
            return False, r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "Clone timed out"
    except Exception as e:
        return False, str(e)

    ok, _, stderr = git(repo_path, "sparse-checkout", "init", "--no-cone")
    if not ok:
        return False, f"sparse-checkout init failed: {stderr}"

    ok, _, stderr = git(repo_path, "sparse-checkout", "set", tracked_path)
    if not ok:
        return False, f"sparse-checkout set failed: {stderr}"

    ok, _, stderr = git(repo_path, "checkout", branch)
    if not ok:
        return False, f"checkout failed: {stderr}"

    return True, ""


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, config, on_save):
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.config_data = dict(config)
        self.on_save = on_save

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill=tk.BOTH, expand=True)

        fields = [
            ("Remote URL",            "remote_url",     False),
            ("Local Repo Path",       "repo_path",      True),
            ("Branch",                "branch",         False),
            ("Commit Message Prefix", "commit_message", False),
        ]

        self.vars = {}
        for i, (label, key, has_browse) in enumerate(fields):
            ttk.Label(frm, text=label).grid(row=i, column=0, sticky=tk.W, padx=8, pady=4)
            var = tk.StringVar(value=self.config_data.get(key, ""))
            self.vars[key] = var
            entry = ttk.Entry(frm, textvariable=var, width=42)
            entry.grid(row=i, column=1, sticky=tk.EW, padx=8, pady=4)
            if has_browse:
                btn(
                    frm, text="Browse…",
                    callback=lambda v=var: self._browse(v)
                ).grid(row=i, column=2, padx=(0, 8), pady=4)

        frm.columnconfigure(1, weight=1)

        # Test Connection row
        ttk.Separator(frm).grid(row=len(fields), column=0, columnspan=3, sticky=tk.EW, pady=(12, 8))

        test_row = ttk.Frame(frm)
        test_row.grid(row=len(fields) + 1, column=0, columnspan=3, sticky=tk.EW, padx=8)

        self.test_btn = btn(test_row, text="Test Connection", callback=self._test_connection)
        self.test_btn.pack(side=tk.LEFT)

        self.test_result_var = tk.StringVar(value="")
        self.test_result_lbl = ttk.Label(
            test_row, textvariable=self.test_result_var,
            font=("Helvetica", 11), foreground="#555"
        )
        self.test_result_lbl.pack(side=tk.LEFT, padx=(10, 0))

        # Save / Cancel
        btn_frm = ttk.Frame(frm)
        btn_frm.grid(row=len(fields) + 2, column=0, columnspan=3, pady=(14, 0))
        btn(btn_frm, text="Save",   callback=self._save).pack(side=tk.LEFT, padx=4)
        btn(btn_frm, text="Cancel", callback=self.destroy).pack(side=tk.LEFT, padx=4)

        self.transient(parent)
        self.wait_visibility()
        self.focus_set()

    def _browse(self, var):
        path = filedialog.askdirectory(title="Select local repo folder")
        if path:
            var.set(path)

    def _test_connection(self):
        url = self.vars["remote_url"].get().strip()
        if not url:
            self.test_result_var.set("Enter a Remote URL first.")
            self.test_result_lbl.configure(foreground="#D97700")
            return
        self.test_btn.state(["disabled"])
        self.test_result_var.set("Testing…")
        self.test_result_lbl.configure(foreground="#555")
        threading.Thread(target=self._run_test, args=(url,), daemon=True).start()

    def _run_test(self, url):
        ok, msg = test_remote(url)
        self.after(0, self._show_test_result, ok, msg)

    def _show_test_result(self, ok, msg):
        self.test_btn.state(["!disabled"])
        if ok:
            self.test_result_var.set("✓  " + msg)
            self.test_result_lbl.configure(foreground="#2E7D32")
        else:
            self.test_result_var.set("✗  " + msg)
            self.test_result_lbl.configure(foreground="#C62828")

    def _save(self):
        for key, var in self.vars.items():
            self.config_data[key] = var.get().strip()
        self.on_save(self.config_data)
        self.destroy()


# ---------------------------------------------------------------------------
# Main application
# ---------------------------------------------------------------------------

class SimpleGitApp:
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.busy = False

        self.root.title("Santina's Tool")
        self.root.geometry("540x600")
        self.root.minsize(440, 500)

        style = ttk.Style()
        for theme in ("aqua", "clam", "default"):
            if theme in style.theme_names():
                style.theme_use(theme)
                break

        self._build_ui()
        self.root.after(100, self._startup_check)

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header row
        header_frame = ttk.Frame(outer)
        header_frame.pack(fill=tk.X)
        ttk.Label(
            header_frame, text="Santina's Tool",
            font=("Helvetica", 20, "bold"),
        ).pack(side=tk.LEFT)
        btn(
            header_frame, text="⚙ Settings",
            callback=self._open_settings,
        ).pack(side=tk.RIGHT, pady=(4, 0))

        # Subtitle + status dot
        sub_frame = ttk.Frame(outer)
        sub_frame.pack(fill=tk.X, pady=(2, 10))

        self.status_dot = tk.Label(
            sub_frame, text="●", font=("Helvetica", 14),
            foreground="#AAAAAA", bg=self.root.cget("bg"),
        )
        self.status_dot.pack(side=tk.LEFT, padx=(0, 6))

        self.subtitle_var = tk.StringVar(value="")
        ttk.Label(
            sub_frame,
            textvariable=self.subtitle_var,
            font=("Helvetica", 12),
            foreground="#555",
        ).pack(side=tk.LEFT)

        ttk.Separator(outer).pack(fill=tk.X, pady=(0, 10))

        # Tracked items list
        lf = ttk.LabelFrame(outer, text="Tracked Items", padding=8)
        lf.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        list_frame = ttk.Frame(lf)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.file_list = tk.Text(
            list_frame,
            font=("Menlo", 12),
            bg="white",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightcolor="#007AFF",
            highlightbackground="#ccc",
            wrap=tk.NONE,
            state=tk.DISABLED,
            cursor="arrow",
            height=5,
        )
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=sb.set)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        self.file_list.tag_configure("ok",      foreground="#333333")
        self.file_list.tag_configure("changed",  foreground="#D97700")
        self.file_list.tag_configure("missing",  foreground="#D32F2F")
        self.file_list.tag_configure("error",    foreground="#999999")

        # Commit message
        mf = ttk.LabelFrame(outer, text="Commit Message", padding=8)
        mf.pack(fill=tk.X, pady=(0, 10))
        self.commit_var = tk.StringVar()
        ttk.Entry(mf, textvariable=self.commit_var, font=("Helvetica", 12)).pack(fill=tk.X)

        # Action buttons
        btn_frame = ttk.Frame(outer)
        btn_frame.pack(fill=tk.X, pady=(0, 10))
        self.pull_btn    = btn(btn_frame, text="⬇  Pull",    callback=self._on_pull)
        self.push_btn    = btn(btn_frame, text="⬆  Push",    callback=self._on_push)
        self.refresh_btn = btn(btn_frame, text="↺  Refresh", callback=self._refresh_status)
        self.pull_btn.pack(   side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))
        self.push_btn.pack(   side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 4))
        self.refresh_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # Log
        log_lf = ttk.LabelFrame(outer, text="Log", padding=4)
        log_lf.pack(fill=tk.BOTH)
        self.log_text = tk.Text(
            log_lf,
            font=("Menlo", 10),
            height=6,
            bg="#1E1E1E",
            fg="#D4D4D4",
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log_text.tag_configure("success", foreground="#4EC94E")
        self.log_text.tag_configure("error",   foreground="#F44747")
        self.log_text.tag_configure("step",    foreground="#9CDCFE")
        self.log_text.tag_configure("warn",    foreground="#CE9178")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ---- Status dot -------------------------------------------------------

    def _set_dot(self, state):
        colors = {"idle": "#AAAAAA", "busy": "#D97700", "ok": "#2E7D32", "error": "#C62828"}
        self.status_dot.configure(foreground=colors.get(state, "#AAAAAA"))

    # ---- Startup ----------------------------------------------------------

    def _startup_check(self):
        repo_path  = self.config.get("repo_path",  "").strip()
        remote_url = self.config.get("remote_url", "").strip()

        if not repo_path or not remote_url:
            self._log("No repo configured. Open ⚙ Settings to get started.", "warn")
            self._update_subtitle()
            self._set_dot("idle")
            return

        repo = Path(repo_path)
        if repo.exists() and (repo / ".git").exists():
            self._update_subtitle()
            self._ensure_sparse_checkout()
        else:
            self._log("Repo not found locally — starting initial clone…", "step")
            self._do_clone()

    def _ensure_sparse_checkout(self):
        repo_path = self.config["repo_path"]
        ok, stdout, _ = git(repo_path, "sparse-checkout", "list")
        if ok and TRACKED_PATH in stdout.splitlines():
            self._set_dot("ok")
            self._refresh_status()
            return

        self._log(
            f"Configuring sparse checkout — trimming repo to {TRACKED_PATH} only…", "step"
        )
        self._set_busy(True)
        threading.Thread(target=self._sparse_worker, daemon=True).start()

    def _sparse_worker(self):
        repo_path = self.config["repo_path"]
        ok, _, stderr = git(repo_path, "sparse-checkout", "init", "--no-cone")
        if not ok:
            self.root.after(0, self._sparse_done, False, f"sparse-checkout init failed: {stderr}")
            return
        ok, _, stderr = git(repo_path, "sparse-checkout", "set", TRACKED_PATH)
        if not ok:
            self.root.after(0, self._sparse_done, False, f"sparse-checkout set failed: {stderr}")
            return
        self.root.after(0, self._sparse_done, True, "")

    def _sparse_done(self, ok, err):
        self._set_busy(False)
        if ok:
            self._log(f"Sparse checkout configured — only {TRACKED_PATH} on disk.", "success")
            self._set_dot("ok")
            self._refresh_status()
        else:
            self._log(f"Sparse checkout setup failed: {err}", "error")
            self._set_dot("error")
            messagebox.showerror("Setup Failed", err)

    def _update_subtitle(self):
        repo_path = self.config.get("repo_path", "")
        branch    = self.config.get("branch", "main")
        repo_name = Path(repo_path).name if repo_path else "—"
        self.subtitle_var.set(f"Repo: {repo_name}   •   Branch: {branch}")

    # ---- Settings ---------------------------------------------------------

    def _open_settings(self):
        SettingsDialog(self.root, self.config, self._on_settings_saved)

    def _on_settings_saved(self, new_config):
        self.config = new_config
        save_config(new_config)
        self._log("Settings saved.", "step")
        self._update_subtitle()
        self._startup_check()

    # ---- Clone ------------------------------------------------------------

    def _do_clone(self):
        self._set_busy(True)
        self._set_dot("busy")
        threading.Thread(target=self._clone_worker, daemon=True).start()

    def _clone_worker(self):
        ok, err = clone_sparse(
            self.config["remote_url"],
            self.config["repo_path"],
            self.config.get("branch", "main"),
            TRACKED_PATH,
        )
        self.root.after(0, self._clone_done, ok, err)

    def _clone_done(self, ok, err):
        self._set_busy(False)
        if ok:
            self._log("Clone complete.", "success")
            self._set_dot("ok")
            self._refresh_status()
        else:
            self._log(f"Clone failed: {err}", "error")
            self._set_dot("error")
            messagebox.showerror("Clone Failed", err or "Unknown error")

    # ---- Helpers ----------------------------------------------------------

    def _default_commit_msg(self):
        prefix = self.config.get("commit_message", "Update portfolio via Simple Git")
        stamp  = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"{prefix} — {stamp}"

    def _log(self, msg, tag=None):
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{stamp}]  {msg}\n", tag or "")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "!disabled"
        self.pull_btn.state([state])
        self.push_btn.state([state])
        self.refresh_btn.state([state])
        if busy:
            self._set_dot("busy")

    def _repo_ready(self):
        repo_path = self.config.get("repo_path", "").strip()
        if not repo_path:
            messagebox.showinfo("Not configured", "Please configure the repo in ⚙ Settings first.")
            return False
        return True

    # ---- Status -----------------------------------------------------------

    def _refresh_status(self):
        repo_path = self.config.get("repo_path", "").strip()
        self.file_list.configure(state=tk.NORMAL)
        self.file_list.delete("1.0", tk.END)

        if not repo_path or not Path(repo_path).exists():
            self.file_list.insert(tk.END, "  No repo configured or repo not found.\n", "error")
            self.file_list.configure(state=tk.DISABLED)
            self._set_dot("error")
            return

        full = Path(repo_path) / TRACKED_PATH
        ok, stdout, _ = git(repo_path, "status", "--porcelain", "--", TRACKED_PATH)

        if not ok:
            tag, status = "error", "unknown"
        elif not full.exists():
            tag, status = "missing", "missing"
        elif stdout:
            n = len([l for l in stdout.splitlines() if l.strip()])
            tag, status = "changed", f"{n} file(s) changed — ready to push"
        else:
            tag, status = "ok", "up to date"

        self.file_list.insert(tk.END, f"  \U0001F4C1  {TRACKED_PATH}  —  {status}\n", tag)
        self.file_list.configure(state=tk.DISABLED)
        self.commit_var.set(self._default_commit_msg())
        self._set_dot("ok" if tag == "ok" else "busy" if tag == "changed" else "error")

    # ---- Pull -------------------------------------------------------------

    def _on_pull(self):
        if self.busy or not self._repo_ready():
            return
        branch = self.config.get("branch", "main")
        self._set_busy(True)
        self._log(f"Pulling from origin/{branch}…", "step")
        threading.Thread(target=self._do_pull, daemon=True).start()

    def _do_pull(self):
        ok, stdout, stderr = git(
            self.config["repo_path"],
            "pull", "origin", self.config.get("branch", "main"),
        )
        self.root.after(0, self._pull_done, ok, stdout, stderr)

    def _pull_done(self, ok, stdout, stderr):
        self._set_busy(False)
        if ok:
            detail = stdout if stdout else "Already up to date."
            self._log(f"Pull complete — {detail}", "success")
            self._set_dot("ok")
            self._refresh_status()
        else:
            self._log(f"Pull failed: {stderr}", "error")
            self._set_dot("error")
            messagebox.showerror("Pull Failed", stderr or "Unknown error")

    # ---- Push -------------------------------------------------------------

    def _on_push(self):
        if self.busy or not self._repo_ready():
            return

        repo_path = self.config["repo_path"]
        ok, stdout, _ = git(repo_path, "status", "--porcelain", "--", TRACKED_PATH)
        if ok and not stdout.strip():
            self._log("Nothing to push — all tracked files are up to date.", "warn")
            return

        branch = self.config.get("branch", "main")
        self._set_busy(True)
        self._log(f"Starting push to origin/{branch}…", "step")
        threading.Thread(target=self._do_push, daemon=True).start()

    def _do_push(self):
        repo_path = self.config["repo_path"]
        branch    = self.config.get("branch", "main")

        # Pull first to avoid rejection if remote is ahead
        self.root.after(0, self._log, f"  Syncing with origin/{branch}…", "step")
        ok, stdout, stderr = git(repo_path, "pull", "origin", branch)
        if not ok:
            self.root.after(0, self._push_done, False, f"Pull failed before push: {stderr}")
            return

        # Stage
        self.root.after(0, self._log, f"  Staging {TRACKED_PATH}…", "step")
        ok, _, stderr = git(repo_path, "add", "--", TRACKED_PATH)
        if not ok:
            self.root.after(0, self._push_done, False, f"Stage failed: {stderr}")
            return

        # Commit
        msg = self.commit_var.get().strip() or self._default_commit_msg()
        self.root.after(0, self._log, f'  Committing: "{msg}"…', "step")
        ok, stdout, stderr = git(repo_path, "commit", "-m", msg)
        if not ok:
            if "nothing to commit" in (stderr + stdout).lower():
                self.root.after(0, self._push_done, True, "Nothing new to commit.")
                return
            self.root.after(0, self._push_done, False, f"Commit failed: {stderr}")
            return

        # Push
        self.root.after(0, self._log, f"  Pushing to origin/{branch}…", "step")
        ok, stdout, stderr = git(repo_path, "push", "origin", branch)
        output = stdout or stderr
        self.root.after(0, self._push_done, ok, output if not ok else "Push complete.")

    def _push_done(self, ok, message):
        self._set_busy(False)
        if ok:
            self._log(message, "success")
            self._set_dot("ok")
            self._refresh_status()
        else:
            self._log(f"Push failed: {message}", "error")
            self._set_dot("error")
            messagebox.showerror("Push Failed", message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    config = load_config()
    root = tk.Tk()
    SimpleGitApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
