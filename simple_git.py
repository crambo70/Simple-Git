#!/usr/bin/env python3
"""
Simple Git — A one-button Pull/Push tool for specific files and folders.

Reads config.json to know which repo to target and which paths to sync.
Only the configured files and folders are staged on push; everything else
in the repo is left untouched.
"""

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from datetime import datetime

CONFIG_FILENAME = "config.json"


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def find_config():
    """Return the path to config.json next to this script."""
    return Path(__file__).resolve().parent / CONFIG_FILENAME


def load_config():
    """Load, validate, and return the configuration dict."""
    path = find_config()
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found:\n{path}\n\n"
            f"Create a {CONFIG_FILENAME} file next to this script."
        )

    with open(path, "r") as f:
        cfg = json.load(f)

    if "repo_path" not in cfg:
        raise ValueError("config.json must contain a \"repo_path\" key.")

    repo = Path(cfg["repo_path"]).expanduser().resolve()
    if not repo.exists():
        raise ValueError(f"Repository path does not exist:\n{repo}")
    if not (repo / ".git").exists() and not (repo / ".git").is_file():
        raise ValueError(f"Not a git repository:\n{repo}")

    cfg["repo_path"] = str(repo)
    cfg.setdefault("branch", "main")
    cfg.setdefault("files", [])
    cfg.setdefault("folders", [])
    cfg.setdefault("commit_message", "Update files via Simple Git")
    return cfg


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def git(repo_path, *args, timeout=120):
    """Run a git command. Returns (ok, stdout, stderr)."""
    cmd = ["git", "-C", str(repo_path)] + list(args)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

class SimpleGitApp:
    def __init__(self, root, config):
        self.root = root
        self.config = config
        self.repo_path = config["repo_path"]
        self.branch = config["branch"]
        self.files = config["files"]
        self.folders = config["folders"]
        self.busy = False

        self.root.title("Simple Git")
        self.root.geometry("540x640")
        self.root.minsize(440, 520)

        # Use a native-looking theme
        style = ttk.Style()
        available = style.theme_names()
        for theme in ("aqua", "clam", "default"):
            if theme in available:
                style.theme_use(theme)
                break

        self._build_ui()
        self.root.after(100, self._refresh_status)

    # ---- UI ---------------------------------------------------------------

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # -- Header --
        ttk.Label(
            outer, text="Simple Git",
            font=("Helvetica", 20, "bold"),
        ).pack(anchor=tk.W)

        repo_name = Path(self.repo_path).name
        ttk.Label(
            outer,
            text=f"Repo: {repo_name}   •   Branch: {self.branch}",
            font=("Helvetica", 12),
            foreground="#555",
        ).pack(anchor=tk.W, pady=(2, 10))

        ttk.Separator(outer).pack(fill=tk.X, pady=(0, 10))

        # -- File list --
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
            height=10,
        )
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_list.yview)
        self.file_list.configure(yscrollcommand=sb.set)
        self.file_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)

        # Tag styles for the text widget
        self.file_list.tag_configure("ok", foreground="#333333")
        self.file_list.tag_configure("changed", foreground="#D97700")
        self.file_list.tag_configure("missing", foreground="#D32F2F")
        self.file_list.tag_configure("error", foreground="#999999")

        # -- Commit message --
        mf = ttk.LabelFrame(outer, text="Commit Message", padding=8)
        mf.pack(fill=tk.X, pady=(0, 10))

        self.commit_var = tk.StringVar()
        self.commit_entry = ttk.Entry(mf, textvariable=self.commit_var, font=("Helvetica", 12))
        self.commit_entry.pack(fill=tk.X)

        # -- Buttons --
        btn_frame = ttk.Frame(outer)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        self.pull_btn = ttk.Button(btn_frame, text="Pull", command=self._on_pull)
        self.pull_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 4))

        self.push_btn = ttk.Button(btn_frame, text="Push", command=self._on_push)
        self.push_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 4))

        self.refresh_btn = ttk.Button(btn_frame, text="Refresh", command=self._refresh_status)
        self.refresh_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(4, 0))

        # -- Log --
        log_lf = ttk.LabelFrame(outer, text="Log", padding=4)
        log_lf.pack(fill=tk.X)

        self.log_text = tk.Text(
            log_lf,
            font=("Menlo", 10),
            height=4,
            bg="#FAFAFA",
            relief=tk.FLAT,
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log_text.pack(fill=tk.X)

    # ---- Helpers ----------------------------------------------------------

    def _tracked_paths(self):
        """All configured file and folder paths."""
        return list(self.files) + list(self.folders)

    def _default_commit_msg(self):
        prefix = self.config["commit_message"]
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        return f"{prefix} — {stamp}"

    def _log(self, msg):
        """Append a line to the log widget."""
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[{stamp}]  {msg}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "!disabled"
        self.pull_btn.state([state])
        self.push_btn.state([state])
        self.refresh_btn.state([state])

    # ---- Status -----------------------------------------------------------

    def _refresh_status(self):
        """Show the status of each tracked path."""
        paths = self._tracked_paths()
        self.file_list.configure(state=tk.NORMAL)
        self.file_list.delete("1.0", tk.END)

        if not paths:
            self.file_list.insert(tk.END, "  No files or folders configured.\n", "error")
            self.file_list.configure(state=tk.DISABLED)
            return

        for path in paths:
            is_folder = path in self.folders
            full = Path(self.repo_path) / path
            icon = "\U0001F4C1" if is_folder else "\U0001F4C4"  # folder / page

            ok, stdout, _ = git(self.repo_path, "status", "--porcelain", "--", path)

            if not ok:
                tag, status = "error", "unknown"
            elif not full.exists():
                tag, status = "missing", "missing"
            elif stdout:
                lines = [l for l in stdout.splitlines() if l.strip()]
                if is_folder:
                    tag, status = "changed", f"{len(lines)} file(s) changed"
                else:
                    code = lines[0][:2].strip() if lines else ""
                    labels = {
                        "M": "modified", "A": "new file",
                        "D": "deleted", "??": "untracked",
                    }
                    tag, status = "changed", labels.get(code, "changed")
            else:
                tag, status = "ok", "up to date"

            self.file_list.insert(tk.END, f"  {icon}  {path}  —  {status}\n", tag)

        self.file_list.configure(state=tk.DISABLED)
        self.commit_var.set(self._default_commit_msg())

    # ---- Pull -------------------------------------------------------------

    def _on_pull(self):
        if self.busy:
            return
        self._set_busy(True)
        self._log("Pulling...")
        threading.Thread(target=self._do_pull, daemon=True).start()

    def _do_pull(self):
        ok, stdout, stderr = git(self.repo_path, "pull", "origin", self.branch)
        self.root.after(0, self._pull_done, ok, stdout, stderr)

    def _pull_done(self, ok, stdout, stderr):
        self._set_busy(False)
        if ok:
            self._log("Pull complete.")
            self._refresh_status()
        else:
            self._log(f"Pull failed: {stderr}")
            messagebox.showerror("Pull Failed", stderr or "Unknown error")

    # ---- Push -------------------------------------------------------------

    def _on_push(self):
        if self.busy:
            return

        paths = self._tracked_paths()
        if not paths:
            messagebox.showinfo("Nothing to push", "No files or folders are configured.")
            return

        # Quick check: anything changed?
        has_changes = False
        for p in paths:
            ok, stdout, _ = git(self.repo_path, "status", "--porcelain", "--", p)
            if ok and stdout.strip():
                has_changes = True
                break

        if not has_changes:
            self._log("Nothing to push — all tracked files are up to date.")
            return

        self._set_busy(True)
        self._log("Pushing...")
        threading.Thread(target=self._do_push, daemon=True).start()

    def _do_push(self):
        paths = self._tracked_paths()

        # Stage
        ok, _, stderr = git(self.repo_path, "add", "--", *paths)
        if not ok:
            self.root.after(0, self._push_done, False, f"Stage failed: {stderr}")
            return

        # Commit
        msg = self.commit_var.get().strip() or self._default_commit_msg()
        ok, stdout, stderr = git(self.repo_path, "commit", "-m", msg)
        if not ok:
            # "nothing to commit" is not a real failure
            if "nothing to commit" in (stderr + stdout).lower():
                self.root.after(0, self._push_done, True, "Nothing new to commit.")
                return
            self.root.after(0, self._push_done, False, f"Commit failed: {stderr}")
            return

        # Push
        ok, stdout, stderr = git(self.repo_path, "push", "origin", self.branch)
        output = stdout or stderr
        self.root.after(0, self._push_done, ok, output if not ok else "Push complete.")

    def _push_done(self, ok, message):
        self._set_busy(False)
        if ok:
            self._log(message)
            self._refresh_status()
        else:
            self._log(f"Push failed: {message}")
            messagebox.showerror("Push Failed", message)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    try:
        config = load_config()
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Configuration Error", str(e))
        root.destroy()
        sys.exit(1)

    root = tk.Tk()
    SimpleGitApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
