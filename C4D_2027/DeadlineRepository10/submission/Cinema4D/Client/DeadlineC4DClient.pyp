"""
DeadlineC4DClient.pyp  (v3 -- icon injection via RegisterCommandPlugin patch)

Thinkbox's original DeadlineC4DClient.pyp is a bootstrap script: when
Cinema 4D loads it at startup, it calls SubmitC4DToDeadline.main(),
which in turn calls plugins.RegisterCommandPlugin(..., "Submit To
Deadline", 0, None, ...) -- note the None for the icon.

That None is why the command has no icon. We can't replace the
registration with our own CommandData (C4D forbids RegisterCommandPlugin
outside of .pyp load context -> 'cannot find pyp file - plugin
registration failed'), so instead we keep the original bootstrap flow
and monkey-patch RegisterCommandPlugin for the duration of Thinkbox's
call. When Thinkbox passes icon=None for "Submit To Deadline", we swap
in the BaseBitmap loaded from Thinkbox-Deadline-01.png.

Install:
  Place this file AND 'Thinkbox-Deadline-01.png' in
    C:\\Program Files\\Maxon Cinema 4D 2027\\plugins\\
  (admin rights required). Restart Cinema 4D.
"""

from shutil import which
import json
import os
import subprocess
import sys
import traceback

import c4d
from c4d import plugins, bitmaps


# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
ICON_FILENAME       = "Thinkbox-Deadline-01.png"
TARGET_COMMAND_NAME = "Submit To Deadline"   # matches Thinkbox's string exactly

PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_PATH   = os.path.join(PLUGIN_DIR, "DeadlineC4DClient_error.log")

# Keep the BaseBitmap alive for the lifetime of the Cinema 4D session so
# C4D's icon cache doesn't end up pointing at a collected object.
_ICON_BITMAP = None


def _log(msg):
    print("[DeadlineC4DClient] %s" % msg)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Deadline helpers (original logic, unchanged)
# -----------------------------------------------------------------------------
def get_deadlinecommand():
    for env in ("DEADLINE_PATH", "PATH"):
        try:
            env_value = os.environ[env]
        except KeyError:
            continue
        exe = which("deadlinecommand", path=env_value)
        if exe:
            return exe

    if os.path.exists("/Users/Shared/Thinkbox/DEADLINE_PATH"):
        with open("/Users/Shared/Thinkbox/DEADLINE_PATH") as dl_file:
            deadline_bin = dl_file.read().strip()
        exe = which("deadlinecommand", path=deadline_bin)
        if exe:
            return exe

    raise Exception("Deadline could not be found. Please ensure that Deadline is installed.")


def call_deadlinecommand(arguments, format_output_as_json=False):
    command = [get_deadlinecommand()]
    if format_output_as_json:
        command.append('-prettyJSON')
    command.extend(arguments)

    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output, _ = proc.communicate()

    if format_output_as_json:
        json_out = json.loads(output)
        if json_out["ok"]:
            return json_out["result"]
        else:
            raise Exception(json_out["result"])
    else:
        if proc.returncode:
            raise Exception(output)
        return output


def GetC4DSubmissionDir():
    json_out = call_deadlinecommand(
        ["-GetRepositoryPath", "submission/Cinema4D/Main"],
        format_output_as_json=True,
    )
    return json_out.replace("\\", "/")


# -----------------------------------------------------------------------------
# Icon loading + RegisterCommandPlugin patching
# -----------------------------------------------------------------------------
def _load_icon():
    icon_path = os.path.join(PLUGIN_DIR, ICON_FILENAME)
    if not os.path.isfile(icon_path):
        _log("icon not found at %s" % icon_path)
        return None

    bmp = bitmaps.BaseBitmap()
    result, _unused = bmp.InitWith(icon_path)
    if result != c4d.IMAGERESULT_OK:
        _log("InitWith failed for icon (result=%s)" % result)
        return None

    _log("icon loaded OK from %s" % icon_path)
    return bmp


def _make_patched_register(original_register, icon_bitmap):
    """
    Return a drop-in replacement for plugins.RegisterCommandPlugin that
    injects our icon whenever Thinkbox registers TARGET_COMMAND_NAME
    with icon=None. All other calls pass through untouched.

    Thinkbox's call is positional:
        RegisterCommandPlugin(id, str, info, icon, help, dat)
    so args[1] is the name and args[3] is the icon. We also cover the
    kwargs form defensively.
    """
    def _patched(*args, **kwargs):
        try:
            name = kwargs.get("str")
            if name is None and len(args) >= 2:
                name = args[1]

            if name == TARGET_COMMAND_NAME:
                if "icon" in kwargs:
                    if kwargs["icon"] is None:
                        kwargs["icon"] = icon_bitmap
                        _log("injected icon via kwargs for '%s'" % name)
                elif len(args) >= 4 and args[3] is None:
                    args = args[:3] + (icon_bitmap,) + args[4:]
                    _log("injected icon via positional for '%s'" % name)
        except Exception:
            _log("icon injection raised (passing through):\n" + traceback.format_exc())

        return original_register(*args, **kwargs)

    return _patched


# -----------------------------------------------------------------------------
# Main -- mirrors the original plugin, with patch wrapped around Thinkbox
# -----------------------------------------------------------------------------
def main():
    global _ICON_BITMAP
    _ICON_BITMAP = _load_icon()

    original_register = plugins.RegisterCommandPlugin
    if _ICON_BITMAP is not None:
        plugins.RegisterCommandPlugin = _make_patched_register(
            original_register, _ICON_BITMAP
        )

    try:
        try:
            submissionDir = GetC4DSubmissionDir()
        except Exception as e:
            _log("Error: Failed to pull Deadline Integrated submitter: %s" % e)
            raise

        if submissionDir not in sys.path:
            _log('Appending "%s" to system path to import SubmitC4DToDeadline' % submissionDir)
            sys.path.append(submissionDir)
        else:
            _log('"%s" already on sys.path' % submissionDir)

        try:
            import SubmitC4DToDeadline
        except ImportError as e:
            _log("Error: Failed to import SubmitC4DToDeadline: %s" % e)
            raise

        SubmitC4DToDeadline.main(submissionDir)
    finally:
        # Always restore, even if Thinkbox raised, so we don't leave C4D
        # with a patched c4d.plugins API for the rest of the session.
        plugins.RegisterCommandPlugin = original_register


if __name__ == '__main__':
    # Reset the log for this session.
    try:
        if os.path.isfile(LOG_PATH):
            os.remove(LOG_PATH)
    except Exception:
        pass

    try:
        main()
    except Exception:
        _log("main() raised:\n" + traceback.format_exc())
