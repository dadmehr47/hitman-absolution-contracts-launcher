"""Hitman Absolution Contracts - launcher (Contracts mode version 1 by Dadmehr47).

Starts the contracts server, points the game's hook.ini at it, and starts the game.
"""
import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

import server as srv

SETTINGS_PATH = os.path.join(srv.APP_DIR, "launcher.json")
GUESSES = [
    r"C:\Program Files (x86)\Steam\steamapps\common\Hitman Absolution",
    r"D:\SteamLibrary\steamapps\common\Hitman Absolution",
    r"H:\SteamLibrary\steamapps\common\Hitman Absolution",
]
W, H = 960, 540
RED, RED_HOVER = "#d92b2f", "#f03a3e"
GREY, DARK, DARK_HOVER = "#a0a0a8", "#2b2b31", "#3b3b43"
YELLOW = "#ffd54a"
FONT = "Segoe UI"
CREDIT = "Contracts mode version 1 by Dadmehr47"

# (title, text, highlighted box or None)
TUTORIAL = [
    ("Welcome!", "This quick tour shows what every option does. It takes about 30 seconds.", None),
    ("Game folder", "Where Hitman Absolution is installed. The launcher usually finds it by itself. "
     "If it is empty, press Browse and pick the folder that contains HMA.exe.", (40, 110, 328, 156)),
    ("Unlimited money", "Turn this on to never run out of money in Contracts mode. Money you earn "
     "from finished contracts is still saved.", (40, 172, 328, 216)),
    ("Share contracts online", "Turn this on to play contracts made by other players and let them "
     "play yours. Needs internet. Your Steam name and ID are shared with each contract.",
     (40, 226, 328, 270)),
    ("Skip game launcher", "Hitman shows its own small launcher window before the game starts. "
     "Turn this on to skip it and go straight into the game.", (40, 280, 328, 324)),
    ("PLAY", "Starts the contracts server and then the game. In most cases this is the only "
     "button you need.", (44, 344, 324, 396)),
    ("Server only", "Starts just the server. Use it if you prefer to start Hitman from Steam "
     "yourself.", (44, 406, 324, 438)),
    ("Activity", "Shows what is happening: saved contracts, money earned, and new contracts from "
     "other players.", (686, 40, 926, 478)),
    ("Tutorial button", "You can open this guide again any time with this button. Good hunting, 47!",
     (44, 446, 324, 478)),
]


def load_settings():
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def find_game_dir(saved):
    for p in [saved] + GUESSES:
        if p and os.path.exists(os.path.join(p, "HMA.exe")):
            return p
    return saved or ""


def get_hook_option(game_dir, key):
    """Read a setting from the [hm5] section of hook.ini (None if it is not there)."""
    try:
        text = open(os.path.join(game_dir, "hook.ini"), "rb").read().decode("utf-8-sig")
    except OSError:
        return None
    section = ""
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("["):
            section = s.lower()
        elif section == "[hm5]" and s.lower().replace(" ", "").startswith(key + "="):
            return s.split("=", 1)[1].strip()
    return None


def set_hook_url(game_dir, url):
    set_hook_option(game_dir, "webserviceurl", url)


def set_hook_option(game_dir, key, value):
    """Set a key in the [hm5] section of hook.ini, keeping everything else."""
    path = os.path.join(game_dir, "hook.ini")
    raw = open(path, "rb").read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    nl = "\r\n" if "\r\n" in text else "\n"
    if not os.path.exists(path + ".bak"):
        open(path + ".bak", "wb").write(raw)
    out, section = [], ""
    for ln in text.split(nl):
        s = ln.strip().lower()
        if s.startswith("["):
            section = s
        if section == "[hm5]" and s.replace(" ", "").startswith(key + "="):
            ln = key + "=" + value
        out.append(ln)
    data = nl.join(out).encode("utf-8")
    open(path, "wb").write((b"\xef\xbb\xbf" if bom else b"") + data)


class Toggle:
    """A small on/off switch drawn on the canvas."""

    def __init__(self, app, x, y, title, hint, on, command):
        self.app, self.x, self.y, self.on, self.command = app, x, y, on, command
        cv = app.cv
        self.track = app.rrect(x, y, x + 44, y + 22, 11, fill="#4a4a52", outline="")
        self.knob = cv.create_oval(x + 3, y + 3, x + 19, y + 19, fill="white", outline="")
        t1 = cv.create_text(x + 58, y + 6, text=title, anchor="w", fill="white",
                            font=(FONT, 11, "bold"))
        t2 = cv.create_text(x + 58, y + 24, text=hint, anchor="w", fill=GREY, font=(FONT, 8))
        for item in (self.track, self.knob, t1, t2):
            cv.tag_bind(item, "<Button-1>", self.click)
            cv.tag_bind(item, "<Enter>", lambda e: cv.config(cursor="hand2"))
            cv.tag_bind(item, "<Leave>", lambda e: cv.config(cursor=""))
        self.paint()

    def paint(self):
        cv = self.app.cv
        cv.itemconfig(self.track, fill=RED if self.on else "#4a4a52")
        dx = 25 if self.on else 3
        cv.coords(self.knob, self.x + dx, self.y + 3, self.x + dx + 16, self.y + 19)

    def set(self, on):
        self.on = on
        self.paint()

    def click(self, _e=None):
        if self.app.tut_active:
            return
        self.set(not self.on)
        self.command(self.on)


class App:
    def __init__(self, root):
        self.root = root
        self.cfg = srv.load_config()
        if not os.path.exists(srv.CONFIG_PATH):
            srv.save_config(self.cfg)
        self.settings = load_settings()
        self.httpd = None
        self.sync_stop = None
        self.tut_active = False
        self.step = 0
        self.q = queue.Queue()

        root.title("Hitman Absolution - Contracts Launcher")
        root.geometry("%dx%d" % (W, H))
        root.resizable(False, False)
        self.cv = tk.Canvas(root, width=W, height=H, highlightthickness=0, bg="#1a0b0d")
        self.cv.pack()
        try:
            self.bg = tk.PhotoImage(file=os.path.join(srv.RES_DIR, "background.png"))
            self.cv.create_image(0, 0, image=self.bg, anchor="nw")
        except tk.TclError:
            self.rrect(24, 24, 344, 516, 18, fill="#111113", outline="")
            self.rrect(676, 24, 936, 516, 18, fill="#111113", outline="")

        cv = self.cv
        cv.create_text(44, 52, text="HITMAN ABSOLUTION", anchor="w", fill="white",
                       font=(FONT, 17, "bold"))
        cv.create_text(44, 78, text="CONTRACTS LAUNCHER", anchor="w", fill=RED,
                       font=(FONT, 9, "bold"))

        cv.create_text(44, 114, text="GAME FOLDER", anchor="w", fill=GREY, font=(FONT, 8, "bold"))
        self.game_dir = tk.StringVar(value=find_game_dir(self.settings.get("game_dir", "")))
        cv.create_window(44, 126, window=self.entry(self.game_dir), anchor="nw", width=200, height=26)
        self.button(252, 126, 324, 152, "Browse", self.browse, DARK, DARK_HOVER, (FONT, 9, "bold"))

        self.unlimited = Toggle(self, 44, 178, "Unlimited money", "Your wallet never runs out",
                                bool(self.cfg["unlimited_money"]), self.on_unlimited)
        self.share = Toggle(self, 44, 232, "Share contracts online",
                            "Play contracts made by other players",
                            bool(self.cfg["share_online"]), self.on_share)

        skip_now = get_hook_option(self.game_dir.get(), "skiplauncher")
        skip_on = (skip_now.lower() == "true") if skip_now is not None \
            else bool(self.settings.get("skip_launcher"))
        self.skip = Toggle(self, 44, 286, "Skip game launcher", "Go straight into the game",
                           skip_on, self.on_skip)

        self.button(44, 344, 324, 396, "\u25B6   PLAY", self.play, RED, RED_HOVER, (FONT, 14, "bold"))
        self.srv_btn = self.button(44, 406, 324, 438, "Start server only", self.toggle_server,
                                   DARK, DARK_HOVER, (FONT, 10, "bold"))
        self.button(44, 446, 324, 478, "?   Tutorial", self.start_tutorial, DARK, DARK_HOVER,
                    (FONT, 10, "bold"))
        self.dot = cv.create_oval(44, 490, 54, 500, fill="#666", outline="")
        self.status = cv.create_text(62, 495, text="Server stopped", anchor="w", fill=GREY,
                                     font=(FONT, 9))

        cv.create_text(694, 46, text="ACTIVITY", anchor="w", fill=GREY, font=(FONT, 8, "bold"))
        self.logbox = tk.Text(root, bg="#101012", fg="#d6d6db", font=("Consolas", 9), relief="flat",
                              wrap="word", state="disabled", highlightthickness=0, padx=6, pady=6,
                              cursor="arrow")
        cv.create_window(692, 62, window=self.logbox, anchor="nw", width=228, height=410)
        cv.create_text(806, 494, text=CREDIT, fill=GREY, font=(FONT, 8))

        root.protocol("WM_DELETE_WINDOW", self.close)
        self.pump()
        if not self.settings.get("tutorial_done"):
            root.after(500, self.start_tutorial)

    # ---- drawing helpers ---------------------------------------------------
    def rrect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def entry(self, var):
        return tk.Entry(self.root, textvariable=var, bg="#1c1c20", fg="white",
                        insertbackground="white", relief="flat", highlightthickness=1,
                        highlightbackground="#3a3a42", highlightcolor=RED, font=(FONT, 9))

    def button(self, x1, y1, x2, y2, text, command, fill, hover, font, tags="", always=False):
        cv = self.cv
        shape = self.rrect(x1, y1, x2, y2, 10, fill=fill, outline="", tags=tags)
        label = cv.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=text, fill="white", font=font,
                               tags=tags)

        def clicked(_e):
            if always or not self.tut_active:
                command()

        for item in (shape, label):
            cv.tag_bind(item, "<Enter>", lambda e: (cv.itemconfig(shape, fill=hover), cv.config(cursor="hand2")))
            cv.tag_bind(item, "<Leave>", lambda e: (cv.itemconfig(shape, fill=fill), cv.config(cursor="")))
            cv.tag_bind(item, "<Button-1>", clicked)
        return label

    # ---- tutorial ------------------------------------------------------------
    def start_tutorial(self):
        self.tut_active = True
        self.step = 0
        self.show_step()

    def show_step(self):
        cv = self.cv
        cv.delete("tut")
        title, body, box = TUTORIAL[self.step]
        last = self.step == len(TUTORIAL) - 1
        bx, bw, bh = 372, 260, 170
        if box:
            x1, y1, x2, y2 = box
            ty = (y1 + y2) // 2
            by = max(30, min(ty - 85, H - 30 - bh))
        else:
            by = (H - bh) // 2
        self.rrect(bx, by, bx + bw, by + bh, 14, fill="#141418", outline=YELLOW, width=2, tags="tut")
        cv.create_text(bx + 16, by + 22, text=title, anchor="w", fill="white",
                       font=(FONT, 12, "bold"), tags="tut")
        cv.create_text(bx + bw - 16, by + 22, text="%d / %d" % (self.step + 1, len(TUTORIAL)),
                       anchor="e", fill=GREY, font=(FONT, 8), tags="tut")
        cv.create_text(bx + 16, by + 42, text=body, anchor="nw", fill="#e6e6ea", width=bw - 32,
                       font=(FONT, 9), tags="tut")
        self.button(bx + 14, by + bh - 44, bx + 94, by + bh - 14, "Skip", self.end_tutorial,
                    DARK, DARK_HOVER, (FONT, 9, "bold"), tags="tut", always=True)
        self.button(bx + bw - 114, by + bh - 44, bx + bw - 14, by + bh - 14,
                    "Finish" if last else "Next  \u2192", self.next_step, RED, RED_HOVER,
                    (FONT, 9, "bold"), tags="tut", always=True)
        if box:
            self.rrect(x1, y1, x2, y2, 10, fill="", outline=YELLOW, width=2, tags="tut")
            on_right = x1 > 600
            sx = bx + bw if on_right else bx
            ex = x1 - 4 if on_right else x2 + 4
            sy = max(by + 25, min(ty, by + bh - 25))
            cv.create_line(sx, sy, ex, ty, fill=YELLOW, width=3, arrow="last",
                           arrowshape=(14, 16, 6), tags="tut")

    def next_step(self):
        if self.step >= len(TUTORIAL) - 1:
            self.end_tutorial()
        else:
            self.step += 1
            self.show_step()

    def end_tutorial(self):
        self.cv.delete("tut")
        self.tut_active = False
        self.settings["tutorial_done"] = True
        self.save_settings()

    # ---- small things --------------------------------------------------------
    def say(self, msg):
        self.q.put(msg)

    def save_settings(self):
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(self.settings, f)
        except OSError:
            pass

    def pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self.logbox.config(state="normal")
                self.logbox.insert("end", "\u2022 " + msg + "\n")
                self.logbox.see("end")
                self.logbox.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self.pump)

    def browse(self):
        p = filedialog.askdirectory(title="Select the Hitman Absolution folder")
        if p:
            self.game_dir.set(os.path.normpath(p))

    def commit(self):
        self.cfg["hub_url"] = self.cfg.get("hub_url") or srv.DEFAULT_HUB
        self.cfg["share_online"] = self.share.on
        self.cfg["unlimited_money"] = self.unlimited.on
        srv.save_config(self.cfg)

    def on_unlimited(self, on):
        self.commit()
        self.say("Unlimited money: %s" % ("ON" if on else "OFF"))

    def on_share(self, on):
        self.commit()
        self.say("Online sharing: %s" % ("ON" if on else "OFF"))
        if on and self.httpd:
            threading.Thread(target=self.httpd.RequestHandlerClass.store.sync, daemon=True).start()

    def on_skip(self, on):
        self.settings["skip_launcher"] = on
        self.save_settings()
        gdir = self.game_dir.get().strip()
        if os.path.exists(os.path.join(gdir, "hook.ini")):
            try:
                set_hook_option(gdir, "skiplauncher", "true" if on else "false")
            except OSError as e:
                messagebox.showerror("hook.ini", "Could not update hook.ini:\n%s" % e)
                return
        self.say("Skip game launcher: %s" % ("ON" if on else "OFF"))

    def set_status(self, running):
        self.cv.itemconfig(self.dot, fill="#3ecf6e" if running else "#666")
        self.cv.itemconfig(self.status, text=("Server running  \u00B7  localhost:%s" % self.cfg["port"])
                           if running else "Server stopped")
        self.cv.itemconfig(self.srv_btn, text="Stop server" if running else "Start server only")

    # ---- server --------------------------------------------------------------
    def start_server(self):
        if self.httpd:
            return True
        self.commit()
        try:
            self.httpd = srv.make_server(self.cfg, self.say)
        except OSError:
            messagebox.showerror("Port busy", "Port %s is already in use.\n\nClose the old "
                                 "HM5.Server.exe (or any other copy) and try again." % self.cfg["port"])
            return False
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.sync_stop = srv.start_sync_loop(self.httpd)
        self.set_status(True)
        self.say("Server started")
        return True

    def stop_server(self):
        if self.sync_stop:
            self.sync_stop.set()
            self.sync_stop = None
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
            self.say("Server stopped")
        self.set_status(False)

    def toggle_server(self):
        self.stop_server() if self.httpd else self.start_server()

    # ---- game ----------------------------------------------------------------
    def play(self):
        gdir = self.game_dir.get().strip()
        exe = os.path.join(gdir, "HMA.exe")
        if not os.path.exists(exe):
            messagebox.showerror("Game not found", "HMA.exe was not found in:\n%s\n\nUse Browse to "
                                 "pick the Hitman Absolution folder." % gdir)
            return
        if not self.start_server():
            return
        try:
            set_hook_url(gdir, "http://localhost:%s/hm5" % self.cfg["port"])
            set_hook_option(gdir, "skiplauncher", "true" if self.skip.on else "false")
        except OSError as e:
            messagebox.showerror("hook.ini", "Could not update hook.ini:\n%s" % e)
            return
        self.settings["game_dir"] = gdir
        self.save_settings()
        self.say("Starting the game...")
        subprocess.Popen([exe], cwd=gdir)

    def close(self):
        self.stop_server()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
