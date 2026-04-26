from __future__ import annotations

import os
import time
import tkinter

from core.logger import colorize_log

from launcher._constants import (
    ICO_PATH,
    SPLASH_BG_COLOR,
    SPLASH_BORDER_COLOR,
    SPLASH_FONT_FAMILY,
    SPLASH_LOADING_GIF_PATH,
    SPLASH_LOGO_PATH,
    SPLASH_TEXT_COLOR,
)
from launcher.fonts import get_native_ui_font_family


__all__ = ["LauncherSplash"]


class LauncherSplash:
    WINDOW_WIDTH = 360
    WINDOW_HEIGHT = 220
    FRAME_DELAY_MS = 50
    MIN_VISIBLE_SECONDS = 1.5
    FONT_FALLBACKS = ("Segoe UI", "TkDefaultFont")

    def __init__(self):
        self.root = None
        self.canvas = None
        self._shown_at = None
        self._registered_font_paths = []
        self._logo_image = None
        self._spinner_frames = []
        self._spinner_image_id = None
        self._spinner_frame_index = 0
        self._spinner_anim_job = None

    def show(self):
        if self.root is not None:
            return

        try:
            self.root = tkinter.Tk()
            try:
                self.root.iconbitmap(ICO_PATH)
            except Exception:
                pass

            self.root.withdraw()
            self.root.overrideredirect(True)
            self.root.attributes("-topmost", True)
            try:
                self.root.wm_attributes("-toolwindow", True)
            except Exception:
                pass

            self.root.configure(bg=SPLASH_BG_COLOR)
            self.root.resizable(False, False)

            self.canvas = tkinter.Canvas(
                self.root,
                width=self.WINDOW_WIDTH,
                height=self.WINDOW_HEIGHT,
                bg=SPLASH_BG_COLOR,
                bd=0,
                highlightthickness=0,
            )
            self.canvas.pack(fill="both", expand=True)

            self._draw_background()
            font_family = self._resolve_font_family()
            self._draw_logo()
            self._draw_loading_row(font_family)
            self._draw_border()
            self._center_window()

            self.root.deiconify()
            self.root.lift()
            self._shown_at = time.time()
            self._schedule_spinner_frame()
            self.pump()
            print(colorize_log("[launcher] Startup splash shown."))
        except Exception as e:
            print(colorize_log(
                f"[launcher] Failed to initialize startup splash: {e}"
            ))
            self.close(ensure_minimum=False)

    def pump(self):
        if self.root is None:
            return

        try:
            self.root.update_idletasks()
            self.root.update()
            self.root.lift()
            self.root.attributes("-topmost", True)
        except tkinter.TclError:
            self._cleanup_registered_fonts()
            self.root = None

    def close(self, ensure_minimum=True):
        if self.root is None:
            return

        if ensure_minimum and self._shown_at is not None:
            deadline = self._shown_at + self.MIN_VISIBLE_SECONDS
            while time.time() < deadline and self.root is not None:
                self.pump()
                time.sleep(0.01)

        try:
            if self._spinner_anim_job is not None:
                self.root.after_cancel(self._spinner_anim_job)
        except Exception:
            pass

        try:
            self.root.destroy()
            print(colorize_log("[launcher] Startup splash closed."))
        except Exception:
            pass
        finally:
            self.root = None
            self.canvas = None
            self._spinner_anim_job = None
            self._spinner_frames = []
            self._cleanup_registered_fonts()

    def _draw_background(self):
        self.canvas.create_rectangle(
            0,
            0,
            self.WINDOW_WIDTH,
            self.WINDOW_HEIGHT,
            fill=SPLASH_BG_COLOR,
            outline="",
        )

    def _draw_logo(self):
        if not os.path.exists(SPLASH_LOGO_PATH):
            return

        try:
            logo_image = tkinter.PhotoImage(file=SPLASH_LOGO_PATH)
            max_dimension = max(logo_image.width(), logo_image.height())
            scale = max(1, round(max_dimension / 90))
            if scale > 1:
                logo_image = logo_image.subsample(scale, scale)

            self._logo_image = logo_image
            self.canvas.create_image(
                self.WINDOW_WIDTH // 2,
                (self.WINDOW_HEIGHT // 2) - 20,
                image=self._logo_image,
                anchor="center",
            )
        except Exception as e:
            print(colorize_log(f"[launcher] Could not load splash logo: {e}"))

    def _draw_loading_row(self, font_family):
        self._spinner_frames = self._load_gif_frames(SPLASH_LOADING_GIF_PATH)
        spinner = self._spinner_frames[0] if self._spinner_frames else None
        spinner_width = spinner.width() if spinner else 24
        spinner_height = spinner.height() if spinner else 24

        bottom_padding = 18
        spinner_x = 18
        spinner_y = self.WINDOW_HEIGHT - bottom_padding
        text_x = spinner_x + spinner_width + 10
        text_y = spinner_y - (spinner_height // 2)

        if spinner is not None:
            self._spinner_image_id = self.canvas.create_image(
                spinner_x,
                spinner_y,
                image=spinner,
                anchor="sw",
            )

        self.canvas.create_text(
            text_x,
            text_y,
            text="Loading...",
            fill=SPLASH_TEXT_COLOR,
            anchor="w",
            font=(font_family, 10),
        )

    def _draw_border(self):
        self.canvas.create_rectangle(
            1,
            1,
            self.WINDOW_WIDTH - 2,
            self.WINDOW_HEIGHT - 2,
            outline=SPLASH_BORDER_COLOR,
            width=8,
        )

    def _load_gif_frames(self, gif_path):
        if not os.path.exists(gif_path):
            return []

        frames = []
        frame_index = 0

        while True:
            try:
                frames.append(
                    tkinter.PhotoImage(
                        file=gif_path, format=f"gif -index {frame_index}"
                    )
                )
                frame_index += 1
            except tkinter.TclError:
                break
            except Exception as e:
                print(colorize_log(
                    f"[launcher] Could not decode splash GIF frame "
                    f"{frame_index}: {e}"
                ))
                break

        if frames:
            return frames

        try:
            return [tkinter.PhotoImage(file=gif_path)]
        except Exception as e:
            print(colorize_log(f"[launcher] Could not load splash GIF: {e}"))
            return []

    def _schedule_spinner_frame(self):
        if (
            self.root is None
            or self._spinner_image_id is None
            or len(self._spinner_frames) < 2
        ):
            return

        self._spinner_frame_index = (
            self._spinner_frame_index + 1
        ) % len(self._spinner_frames)
        self.canvas.itemconfigure(
            self._spinner_image_id,
            image=self._spinner_frames[self._spinner_frame_index],
        )
        self._spinner_anim_job = self.root.after(
            self.FRAME_DELAY_MS, self._schedule_spinner_frame
        )

    def _center_window(self):
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - self.WINDOW_WIDTH) // 2
        y = (self.root.winfo_screenheight() - self.WINDOW_HEIGHT) // 2
        self.root.geometry(
            f"{self.WINDOW_WIDTH}x{self.WINDOW_HEIGHT}+{x}+{y}"
        )

    def _resolve_font_family(self):
        if self.root is None:
            return self.FONT_FALLBACKS[0]

        family = get_native_ui_font_family(self.root, self.FONT_FALLBACKS)
        if family == SPLASH_FONT_FAMILY:
            print(colorize_log(
                f"[launcher] Loaded startup splash font family: {family}"
            ))
        elif family not in self.FONT_FALLBACKS:
            print(colorize_log(
                f"[launcher] Loaded startup splash font family: {family}"
            ))
        else:
            print(colorize_log(
                f"[launcher] Splash font fallback in use. "
                f"('{SPLASH_FONT_FAMILY}' not found in Tk font list)"
            ))
        return family

    def _cleanup_registered_fonts(self):
        self._registered_font_paths.clear()
