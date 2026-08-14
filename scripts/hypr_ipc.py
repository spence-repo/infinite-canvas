#!/usr/bin/env python3

"""
hypr_ipc.py
Capa de compatibilidad con hyprctl para Hyprland >= 0.55 (config Lua).

POR QUE EXISTE ESTE ARCHIVO
----------------------------
Desde Hyprland 0.55, `hyprctl dispatch <dispatcher> <args...>` (la sintaxis
posicional vieja de hyprlang, ej. `dispatch togglefloating address:0x123`)
ya NO funciona. hyprctl ahora parsea el argumento de `dispatch` como una
expresion Lua real y la ejecuta contra el namespace hl.dsp.*.

No es un bug ni algo especifico de tu hyprland.lua: es un cambio de diseño
deliberado, confirmado por el mantenedor de Hyprland (vaxerski) como
"expected behavior" cuando alguien reporto exactamente este problema.
Ver: github.com/hyprwm/Hyprland/discussions/14255

Sintaxis nueva (confirmada contra wiki.hypr.land/Configuring/Basics/Dispatchers):

    hyprctl dispatch 'hl.dsp.window.float({ action = "toggle" })'

en vez de:

    hyprctl dispatch togglefloating

Este modulo centraliza TODAS las llamadas a `hyprctl dispatch` para que,
cuando Hyprland vuelva a cambiar la API (va a pasar, esto es -git de hace
semanas), solo haya que tocar un archivo.

QUE ESTA CONFIRMADO
---------------------
Todo lo de este archivo esta confirmado contra la wiki oficial Y contra
pruebas en vivo con hyprctl (2026-07-01): toggle_floating, focus_window,
move_focus, move_window_tiled, exec_cmd, y tambien las dos funciones que
antes estaban marcadas como sin confirmar: move_window_exact_lua y
resize_window_exact_lua.

La wiki no publica el nombre de campo para posicionamiento/tamano exacto
por pixel, asi que se descubrio disparando la llamada a proposito y leyendo
el mensaje de error de Hyprland, que lista los argumentos esperados:

    $ hyprctl dispatch 'hl.dsp.window.move({ window = "activewindow", coords = {100,100} })'
    error: hl.window.move: unrecognized arguments.
           Expected one of: direction, x+y(+relative), workspace, into_group, out_of_group

    $ hyprctl dispatch 'hl.dsp.window.resize({ window = "activewindow", x = 100, y = 100 })'
    ok   # -> ventana redimensionada a 100x100px, confirmado visualmente

Osea: tanto window.move como window.resize usan los campos "x" / "y"
sueltos (no "coords" ni "size" como tabla), con "relative" opcional que
por defecto se comporta como absoluto (relative = false).
"""
import subprocess
import json


def _run(args, timeout=2):
    return subprocess.run(["hyprctl"] + args, capture_output=True, text=True, timeout=timeout)


def hyprctl_json(args, timeout=2):
    """Llamadas de solo lectura (clients, activewindow, monitors, etc).
    Estas NO pasan por el parser de dispatch, siguen funcionando igual
    que antes en Lua config."""
    r = _run(args + ["-j"], timeout=timeout)
    return json.loads(r.stdout) if r.stdout.strip() else None


def dispatch(lua_expr, timeout=2):
    """Ejecuta hyprctl dispatch '<lua_expr>'.
    lua_expr debe ser una llamada completa a hl.dsp.*(...)"""
    return _run(["dispatch", lua_expr], timeout=timeout)


def dispatch_async(lua_expr):
    subprocess.Popen(["hyprctl", "dispatch", lua_expr],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def batch(lua_exprs, timeout=5):
    """lua_exprs: lista de llamadas completas a hl.dsp.*(...)"""
    cmd = " ; ".join(f"dispatch {e}" for e in lua_exprs)
    return subprocess.run(["hyprctl", "--batch", cmd], capture_output=True, timeout=timeout)


def batch_async(lua_exprs):
    if not lua_exprs:
        return
    cmd = " ; ".join(f"dispatch {e}" for e in lua_exprs)
    subprocess.Popen(["hyprctl", "--batch", cmd],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ─────────────────────────────────────────────────────────────
# Confirmado contra la wiki oficial
# ─────────────────────────────────────────────────────────────

def toggle_floating_lua(address=None):
    w = f', window = "address:{address}"' if address else ""
    return f'hl.dsp.window.float({{ action = "toggle"{w} }})'

def toggle_floating(address=None):
    return dispatch(toggle_floating_lua(address))


def focus_window_lua(address):
    return f'hl.dsp.focus({{ window = "address:{address}" }})'

def focus_window(address):
    return dispatch(focus_window_lua(address))


def move_focus_lua(direction_lud):  # 'l' | 'r' | 'u' | 'd'
    return f'hl.dsp.focus({{ direction = "{direction_lud}" }})'

def move_focus(direction_lud):
    return dispatch(move_focus_lua(direction_lud))


def move_window_tiled_lua(direction_lud):
    return f'hl.dsp.window.move({{ direction = "{direction_lud}" }})'

def move_window_tiled(direction_lud):
    return dispatch(move_window_tiled_lua(direction_lud))


def exec_cmd_lua(cmd):
    escaped = cmd.replace('\\', '\\\\').replace('"', '\\"')
    return f'hl.dsp.exec_cmd("{escaped}")'


# ─────────────────────────────────────────────────────────────
# Confirmado en vivo contra hyprctl (2026-07-01). Equivalentes de:
#     dispatch movewindowpixel exact X Y,address:ADDR
#     dispatch resizewindowpixel exact W H,address:ADDR
# ─────────────────────────────────────────────────────────────

def move_window_exact_lua(x, y, address):
    return (f'hl.dsp.window.move({{ window = "address:{address}", '
            f'x = {int(x)}, y = {int(y)}, relative = false }})')

def move_window_exact(x, y, address, timeout=2):
    return dispatch(move_window_exact_lua(x, y, address), timeout=timeout)

def move_window_exact_async(x, y, address):
    dispatch_async(move_window_exact_lua(x, y, address))


def resize_window_exact_lua(w, h, address):
    return (f'hl.dsp.window.resize({{ window = "address:{address}", '
            f'x = {int(w)}, y = {int(h)}, relative = false }})')

def resize_window_exact(w, h, address, timeout=2):
    return dispatch(resize_window_exact_lua(w, h, address), timeout=timeout)
