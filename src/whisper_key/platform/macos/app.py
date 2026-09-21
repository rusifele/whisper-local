# platform/macos/app.py
# macOS app lifecycle: runs an NSApplication as an accessory (no Dock icon) and
# pumps its run loop, which Cocoa requires on the MAIN thread — the reason the
# platform layer exposes thread requirements at all.
# Windows mirror: platform/windows/app.py (no such constraint).
from AppKit import NSApplication, NSApplicationActivationPolicyAccessory, NSEventMaskAny, NSDefaultRunLoopMode
from Foundation import NSDate, NSObject, NSOperationQueue, NSThread

class AppDelegate(NSObject):
    def applicationSupportsSecureRestorableState_(self, app):
        return True

_delegate = None

# Keeps a hidden Tk root alive for the whole process. Tk 9.0 on macOS installs
# its own TKApplication *subclass* as the shared NSApplication the first time a
# root window is created. If pyobjc beats Tk to NSApplication.sharedApplication()
# (creating a plain NSApplication instead), every later Tk() call — the first-run
# welcome window, the level overlay — aborts with "-[NSApplication macOSVersion]:
# unrecognized selector". Pre-creating Tk first lets pyobjc and Tk widgets share
# the same TKApplication instance instead of fighting over the class identity.
_tk_preload_root = None


# Establishes Tk's TKApplication as the shared NSApplication before pyobjc
# creates one. Best-effort: if Tk is unavailable we fall back to a plain
# NSApplication and callers that need Tk (welcome window) skip themselves.
def _preload_tk():
    global _tk_preload_root
    try:
        import tkinter as tk
        _tk_preload_root = tk.Tk()
        _tk_preload_root.withdraw()
    except Exception:
        _tk_preload_root = None


def setup():
    global _delegate
    _preload_tk()
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    _delegate = AppDelegate.alloc().init()
    app.setDelegate_(_delegate)

def getch():
    import tty
    import termios
    import sys
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return ch

# Run fn on the main thread, because Cocoa requires every AppKit mutation to
# happen there.
#
# This is not a nicety. Through macOS 26 a background-thread menu-bar write
# only logged a warning; macOS 27 made it a hard trap — BSServiceMainRunLoopQueue's
# barrier assertion raises SIGTRAP and the process dies instantly (issue #13).
# SIGTRAP is not a Python exception, so no try/except at the call site can save
# it; the write simply must not happen off-thread.
#
# Dispatch is async on purpose: the callers are the recording thread and the
# level monitor, and neither may block on the UI. Blocks queued before the run
# loop starts simply run once it does. run_event_loop() below pumps
# NSDefaultRunLoopMode, which services the main queue.
def run_on_ui_thread(fn):
    if NSThread.isMainThread():
        fn()
        return
    NSOperationQueue.mainQueue().addOperationWithBlock_(fn)


def run_event_loop(shutdown_event):
    app = NSApplication.sharedApplication()
    while not shutdown_event.is_set():
        event = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
            NSEventMaskAny,
            NSDate.dateWithTimeIntervalSinceNow_(0.1),
            NSDefaultRunLoopMode,
            True
        )
        if event:
            app.sendEvent_(event)
