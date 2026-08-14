import json
import os
import struct
import subprocess
import sys
import threading
import time

from evdev import InputDevice, ecodes, list_devices

from canvas import Canvas
from config import load_config

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hypr_ipc import move_window_exact_lua

#ruta deseada /home/usuario/scripts/

# Ya no se pasan rutas de dispositivo a mano: se autodetectan por capacidades.
# Uso: infinite_desktop_core.py [speed]
speed = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

DEVICE_RESCAN_INTERVAL = 3.0  # segundos entre escaneos de nuevos/removidos dispositivos

EVENT_SIZE = struct.calcsize('llHHi')
EV_KEY=1; EV_REL=2; REL_X=0; REL_Y=1; REL_WHEEL=8
KEY_LEFTMETA=125; KEY_RIGHTMETA=126
KEY_LEFTALT=56; KEY_RIGHTALT=100
KEY_LEFTCTRL=29; KEY_RIGHTCTRL=97
KEY_LEFT=105; KEY_RIGHT=106
KEY_UP=103; KEY_DOWN=108
KEY_BACKSPACE = 14
BTN_LEFT=272
BTN_RIGHT=273

STATE_FILE = "/tmp/infinite-desktop-state"
PROTECTED_APPS = ['brave-browser', 'chromium', 'chromium-browser', 'google-chrome', 
                  'firefox', 'firefoxdeveloperedition', 'librewolf', 'vivaldi', 
                  'opera', 'microsoft-edge']

lock = threading.Lock()
super_pressed=False; alt_pressed=False; ctrl_pressed=False; btn_left=False; btn_right=False

# Canvas Variables.
config = load_config()
canvas = Canvas(workspace=config["workspace"], monitor=config["monitor"])
INFINITE_WORKSPACE = config["workspace"]
ZOOM_ENABLED = config["zoom"]["enabled"]
ZOOM_BASE_FACTOR = config["zoom"]["base_factor"]
ZOOM_ACCELERATION = config["zoom"]["acceleration"]["enabled"]
ZOOM_ACCELERATION_STRENGTH = config["zoom"]["acceleration"]["strength"]
ZOOM_MOMENTUM = config["zoom"]["momentum"]["enabled"]
ZOOM_MOMENTUM_STRENGTH = config["zoom"]["momentum"]["strength"]
ZOOM_MOMENTUM_DECAY = config["zoom"]["momentum"]["decay"]
PAN_SPEED = config["pan"]["speed"]

acc_x=0.0; acc_y=0.0
mouse_wheel = 0
frame_held_hidden=False  # último estado notificado a quickshell (evita spam de llamadas ipc)

# Variables para arrastre de ventanas
window_drag_active = False
window_resize_active = False
last_window_pos = None
last_window_bounds = None
mouse_rel_x = 0
mouse_rel_y = 0
reset_requested = False

# Paso de movimiento con teclado
KEY_MOVE_STEP = 20

def get_initial_mouse_position():
    try:
        r = subprocess.run(
            ['hyprctl', 'monitors', '-j'],
            capture_output=True,
            text=True,
            timeout=0.1
        )

        monitors = json.loads(r.stdout)

        for monitor in monitors:
            if monitor.get("name") == canvas.monitor:
                return (
                    monitor["x"] + monitor["width"] // 2,
                    monitor["y"] + monitor["height"] // 2
                )

    except Exception:
        pass

    # Fallback only if monitor detection fails
    return 960, 540

def get_cursor_position():
    try:
        r = subprocess.run(
            ['hyprctl', 'cursorpos'],
            capture_output=True,
            text=True,
            timeout=0.1
        )

        x, y = r.stdout.strip().split(',')
        return float(x), float(y)

    except Exception as e:
        print(f"Error getting cursor position: {e}", flush=True)
        return mouse_x, mouse_y

mouse_x, mouse_y = get_initial_mouse_position()

def read_inverted():
    try:
        with open(STATE_FILE) as f:
            return f.read().strip() == 'inverse'
    except:
        return False

def is_infinite_desktop_workspace():
    try:
        r = subprocess.run(
                ['hyprctl', 'activeworkspace', '-j'],
                capture_output=True, text=True, timeout=1.0
        )
        workspace = json.loads(r.stdout)

        return (
                # Making sure 'is None' is here in case 'id' doesn't exist.
                INFINITE_WORKSPACE is None 
                or workspace.get('id') == INFINITE_WORKSPACE
        )

    except Exception:
        return False

def notify_quickshell_hold(state):
    """Avisa a quickshell (IpcHandler target='frame') que esconda/muestre
    el marco. No bloqueante: se lanza en su propio hilo para no meter
    latencia en el loop de lectura de teclado. Silenciosa si quickshell
    no está corriendo (p.ej. durante un reload)."""
    try:
        subprocess.run(
            ['qs', 'ipc', 'call', 'frame', 'setHeldHidden', 'true' if state else 'false'],
            capture_output=True, timeout=1.0
        )
    except Exception:
        pass

def get_monitor_bounds():
    try:
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        if monitors:
            for m in monitors:
                if m.get('focused', False):
                    return {
                        'left': m['x'],
                        'right': m['x'] + m['width'],
                        'top': m['y'],
                        'bottom': m['y'] + m['height'],
                        'width': m['width'],
                        'height': m['height']
                    }
            m = monitors[0]
            return {
                'left': m['x'],
                'right': m['x'] + m['width'],
                'top': m['y'],
                'bottom': m['y'] + m['height'],
                'width': m['width'],
                'height': m['height']
            }
    except:
        pass
    return {'left': 0, 'right': 1920, 'top': 0, 'bottom': 1080, 'width': 1920, 'height': 1080}

def get_floating_windows(workspace_id):
    try:
        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        clients = json.loads(r.stdout)
        floating = []
        for w in clients:
            if w.get('floating') and w.get('workspace', {}).get('id') == workspace_id:
                floating.append(w)
        return floating
    except:
        return []

def get_focused_window():
    try:
        r = subprocess.run(['hyprctl', 'activewindow', '-j'], capture_output=True, text=True, timeout=0.1)
        return json.loads(r.stdout)
    except:
        return None

def is_protected_app(window):
    if not window:
        return False
    window_class = window.get('class', '').lower()
    return any(app in window_class for app in PROTECTED_APPS)

def get_window_center(window):
    return (window['at'][0] + window['size'][0] // 2,
            window['at'][1] + window['size'][1] // 2)

def get_window_bounds(window):
    x, y = window['at'][0], window['at'][1]
    w, h = window['size'][0], window['size'][1]
    return {
        'left': x,
        'right': x + w,
        'top': y,
        'bottom': y + h,
        'center_x': x + w // 2,
        'center_y': y + h // 2
    }

def windows_overlap_horizontally(bounds1, bounds2):
    return not (bounds1['right'] <= bounds2['left'] or bounds1['left'] >= bounds2['right'])

def windows_overlap_vertically(bounds1, bounds2):
    return not (bounds1['bottom'] <= bounds2['top'] or bounds1['top'] >= bounds2['bottom'])

def pan_other_windows(excluded_addr, dx, dy, workspace_id):
    """Move all windows EXCEPT the specified one in a single batch"""
    
    if dx == 0 and dy == 0:
        return
    
    try:
        canvas.pan(dx, dy, excluded_addr)

    except Exception as e:
        print(f"Canvas pan error: {e}", flush=True)
    
def get_monitor_center():
    """Devuelve el centro del monitor enfocado."""
    try:
        r = subprocess.run(['hyprctl', 'monitors', '-j'], capture_output=True, text=True, timeout=0.1)
        monitors = json.loads(r.stdout)
        for m in monitors:
            if m.get('focused', False):
                return m['x'] + m['width'] // 2, m['y'] + m['height'] // 2
    except:
        pass
    return 960, 540

def hyprland_window_address(address):
    """Returns the address of a Hyprland window object."""
    try:
        r = subprocess.run(
                ['hyprctl', 'clients', '-j'],
                capture_output=True, 
                text=True, 
                timeout=0.1
            )
           
        clients = json.loads(r.stdout)

        for window in clients:
            if window.get("address") == address:
                return window

    except Exception as e:
        print(f"Error finding window (address): {e}", flush=True)
        
    return None

def monitor_window_drag():
    """Monitors Super+mouse window drag/resize.

    Super + Left Click  = drag window
    Super + Right Click = resize window

    Mouse movement is accumulated by mouse_reader_device()
    and consumed here.
    """

    global window_drag_active
    global window_resize_active
    global mouse_rel_x
    global mouse_rel_y

    dragged_window_addr = None
    resized_window_addr = None

    last_super = False
    last_btn_left = False
    last_btn_right = False

    while True:

        canvas_active = is_infinite_desktop_workspace()

        try:

            # READ CURRENT INPUT STATE
            with lock:

                current_super = super_pressed
                current_alt = alt_pressed
                current_ctrl = ctrl_pressed

                current_btn_left = btn_left
                current_btn_right = btn_right

                mouse_dx = mouse_rel_x
                mouse_dy = mouse_rel_y

                mouse_rel_x = 0
                mouse_rel_y = 0

            # DETERMINE MODES
            is_dragging = (
                current_super
                and canvas_active
                and current_btn_left
                and not current_alt
                and not current_ctrl
            )

            is_resizing = (
                current_super
                and canvas_active
                and current_btn_right
                and not current_alt
                and not current_ctrl
            )

            # START DRAG
            if is_dragging and not window_drag_active:


                focused = get_focused_window()

                if focused and focused.get("address"):

                    dragged_window_addr = (
                        focused["address"]
                    )

                    window_drag_active = True

                    print(
                    f"\nDragging window {dragged_window_addr}...",
                    flush=True
                )

            # END DRAG
            if (
                not is_dragging
                and window_drag_active
            ):

                print(
                    f"Finished dragging window {dragged_window_addr}.",
                    flush=True
                )

                if dragged_window_addr:

                    window = hyprland_window_address(
                        dragged_window_addr
                    )

                    if window:

                        canvas.update_window(
                            window
                        )

                window_drag_active = False
                dragged_window_addr = None

            # START RESIZE
            if (
                is_resizing
                and not window_resize_active
            ):

                print(
                    "\n>>> RESIZE START",
                    flush=True
                )

                focused = get_focused_window()

                if (
                    focused
                    and focused.get("address")
                ):

                    resized_window_addr = (
                        focused["address"]
                    )

                    window_resize_active = True

                    print(
                        f">>> RESIZE WINDOW: "
                        f"{resized_window_addr}",
                        flush=True
                    )

                    print(
                        ">>> RESIZE INITIAL SCREEN:",
                        focused.get("at"),
                        "SIZE:",
                        focused.get("size"),
                        flush=True
                    )

            # END RESIZE
            if (
                not is_resizing
                and window_resize_active
            ):

                print(
                    ">>> RESIZE END",
                    flush=True
                )

                if resized_window_addr:

                    window = hyprland_window_address(
                        resized_window_addr
                    )

                    if window:

                        print(
                            ">>> RESIZE FINAL:",
                            flush=True
                        )

                        print(
                            ">>> ADDRESS =",
                            window.get("address"),
                            flush=True
                        )

                        print(
                            ">>> SCREEN  =",
                            window.get("at"),
                            flush=True
                        )

                        print(
                            ">>> SIZE    =",
                            window.get("size"),
                            flush=True
                        )

                        print(
                            ">>> FLOATING =",
                            window.get("floating"),
                            flush=True
                        )

                        canvas.update_window(
                            window
                        )

                window_resize_active = False
                resized_window_addr = None

            # ACTIVE DRAG / EDGE PUSH
            if (
                window_drag_active
                and dragged_window_addr
            ):

                window = hyprland_window_address(
                    dragged_window_addr
                )

                if window:

                    current_bounds = (
                        get_window_bounds(window)
                    )

                    monitor = (
                        get_monitor_bounds()
                    )

                    MARGIN = 10

                    touch_left = (
                        current_bounds["left"]
                        <= monitor["left"] + MARGIN
                    )

                    touch_right = (
                        current_bounds["right"]
                        >= monitor["right"] - MARGIN
                    )

                    touch_top = (
                        current_bounds["top"]
                        <= monitor["top"] + MARGIN
                    )

                    touch_bottom = (
                        current_bounds["bottom"]
                        >= monitor["bottom"] - MARGIN
                    )

                    if (
                        (
                            touch_left
                            or touch_right
                            or touch_top
                            or touch_bottom
                        )
                        and (
                            mouse_dx != 0
                            or mouse_dy != 0
                        )
                    ):

                        pan_dx = 0
                        pan_dy = 0

                        # Horizontal edge
                        if (
                            touch_right
                            and mouse_dx > 0
                        ) or (
                            touch_left
                            and mouse_dx < 0
                        ):

                            pan_dx = mouse_dx

                        # Vertical edge
                        if (
                            touch_bottom
                            and mouse_dy > 0
                        ) or (
                            touch_top
                            and mouse_dy < 0
                        ):

                            pan_dy = mouse_dy

                        # PAN DESKTOP
                        if (
                            pan_dx != 0
                            or pan_dy != 0
                        ):

                            try:

                                r = subprocess.run(
                                    [
                                        "hyprctl",
                                        "activeworkspace",
                                        "-j"
                                    ],
                                    capture_output=True,
                                    text=True,
                                    timeout=0.1
                                )

                                ws = json.loads(
                                    r.stdout
                                )

                                workspace_id = ws["id"]

                                pan_other_windows(
                                    dragged_window_addr,
                                    int(pan_dx),
                                    int(pan_dy),
                                    workspace_id
                                )

                            except Exception as e:

                                print(
                                    "Error getting "
                                    "workspace for edge pan:",
                                    e,
                                    flush=True
                                )

            # =================================================
            # LOOP
            # =================================================

            time.sleep(0.016)

        except Exception as e:

            print(
                f"[WINDOW MONITOR ERROR] "
                f"{e}",
                flush=True
            )

            time.sleep(0.1)

def move_active_window(direction):
    """Moves the active window by KEY_MOVE_STEP px in the indicated direction.
    If it hits the edge of the monitor, it pushes the other windows in the opposite direction.
    """
    try:
        r = subprocess.run(
            ['hyprctl', 'activeworkspace', '-j'],
            capture_output=True,
            text=True,
            timeout=0.1
        )

        ws = json.loads(r.stdout)
        workspace_id = ws['id']

        window = get_focused_window()

        if not window or not window.get('floating'):
            return

        monitor = get_monitor_bounds()
        addr = window['address']

        dx, dy = 0, 0

        if direction == 'left':
            dx = -KEY_MOVE_STEP

        elif direction == 'right':
            dx = KEY_MOVE_STEP

        elif direction == 'up':
            dy = -KEY_MOVE_STEP

        elif direction == 'down':
            dy = KEY_MOVE_STEP

        new_x = window['at'][0] + dx
        new_y = window['at'][1] + dy

        # Detectar si toca borde DESPUÉS del movimiento
        new_bounds_left = new_x
        new_bounds_right = new_x + window['size'][0]
        new_bounds_top = new_y
        new_bounds_bottom = new_y + window['size'][1]

        hits_left = new_bounds_left <= monitor['left']
        hits_right = new_bounds_right >= monitor['right']
        hits_top = new_bounds_top <= monitor['top']
        hits_bottom = new_bounds_bottom >= monitor['bottom']

        hitting_edge = (
            (dx < 0 and hits_left)
            or (dx > 0 and hits_right)
            or (dy < 0 and hits_top)
            or (dy > 0 and hits_bottom)
        )

        # Mover la ventana activa
        move_window_exact_lua(
            new_x,
            new_y,
            addr
        )

        # Mantener Canvas sincronizado con el nuevo screen position
        canvas.move_window_screen(
            addr,
            new_x,
            new_y
        )

        # Si toca borde, empujar las demás ventanas
        if hitting_edge:
            pan_other_windows(
                addr,
                -dx,
                -dy,
                workspace_id
            )

    except Exception as e:
        print(
            f"Error en move_active_window: {e}",
            flush=True
        )

def classify_device(path):
    """Devuelve 'mouse', 'keyboard' o None segun las capacidades reales del dispositivo,
    sin importar el nombre/marca. Esto es lo que permite que funcione con cualquier
    mouse o teclado (alambrico, inalambrico, el que sea)."""
    try:
        dev = InputDevice(path)
        caps = dev.capabilities()
        dev.close()
    except Exception:
        return None

    keys = set(caps.get(ecodes.EV_KEY, []))
    rels = set(caps.get(ecodes.EV_REL, []))

    is_mouse = (ecodes.REL_X in rels and ecodes.REL_Y in rels and ecodes.BTN_LEFT in keys)
    if is_mouse:
        return 'mouse'

    # Un teclado "real" tiene el rango completo de teclas alfanumericas y las teclas Meta,
    # esto excluye las interfaces auxiliares (Consumer Control, System Control) que
    # muchos recievers 2.4G tambien exponen.
    is_keyboard = (
        ecodes.KEY_A in keys and ecodes.KEY_Z in keys and ecodes.KEY_LEFTSHIFT in keys
        and (ecodes.KEY_LEFTMETA in keys or ecodes.KEY_RIGHTMETA in keys)
    )
    if is_keyboard:
        return 'keyboard'

    return None

def scan_devices():
    keyboards, mice = [], []
    for path in list_devices():
        kind = classify_device(path)
        if kind == 'mouse':
            mice.append(path)
        elif kind == 'keyboard':
            keyboards.append(path)
    return keyboards, mice

def kbd_reader_device(path):
    """Lee eventos de UN teclado especifico."""

    global super_pressed
    global alt_pressed
    global ctrl_pressed
    global frame_held_hidden
    global reset_requested
    
    try:
        fd = open(path, 'rb')
    except Exception as e:
        print(
            f"[KBD ERROR] Cannot open {path}: {e}",
            flush=True
        )
        return

    print(
        f"[KBD READER STARTED] {path}",
        flush=True
    )

    while True:

        try:
            data = fd.read(EVENT_SIZE)
        except Exception as e:
            print(
                f"[KBD READ ERROR] {path}: {e}",
                flush=True
            )
            break

        if not data or len(data) < EVENT_SIZE:
            print(
                f"[KBD DISCONNECTED] {path}",
                flush=True
            )
            break

        _, _, etype, code, value = struct.unpack('llHHi', data)

        if etype != EV_KEY:
            continue

        # Ignore key-repeat for state transitions.
        # value=2 means the key is being held.
        if value == 2:

            if code in (
                KEY_LEFTMETA,
                KEY_RIGHTMETA
            ):

                continue

        notify_state = None

        with lock:

            # SUPER
            if code in (
                KEY_LEFTMETA,
                KEY_RIGHTMETA
            ):

                super_pressed = (
                    value == 1
                )

            # ALT
            elif code in (
                KEY_LEFTALT,
                KEY_RIGHTALT
            ):

                alt_pressed = (
                    value == 1
                )

            # CTRL
            elif code in (
                KEY_LEFTCTRL,
                KEY_RIGHTCTRL
            ):

                ctrl_pressed = (
                    value == 1
                )

            # BACKSPACE
            elif code == KEY_BACKSPACE and value == 1 and super_pressed:
                reset_requested = True

        # -------------------------------------------------
        # Quickshell IPC OUTSIDE LOCK
        # -------------------------------------------------

        if notify_state is not None:

            threading.Thread(
                target=notify_quickshell_hold,
                args=(notify_state,),
                daemon=True
            ).start()

    try:
        fd.close()
    except Exception:
        pass

def mouse_reader_device(path):
    """Lee eventos de UN mouse especifico.
    Se lanza un hilo por cada mouse detectado.
    """

    global acc_x, acc_y
    global btn_left, btn_right
    global mouse_rel_x, mouse_rel_y
    global mouse_wheel, mouse_x, mouse_y

    try:
        fd = open(path, 'rb')
    except Exception as e:
        print(
            f"[MOUSE ERROR] Cannot open {path}: {e}",
            flush=True
        )
        return

    while True:
        try:
            data = fd.read(EVENT_SIZE)
        except Exception as e:
            print(
                f"[MOUSE READ ERROR] {path}: {e}",
                flush=True
            )
            break

        if not data or len(data) < EVENT_SIZE:
            print(
                f"[MOUSE DISCONNECTED] {path}",
                flush=True
            )
            break

        _, _, etype, code, value = struct.unpack('llHHi', data)

        # -------------------------------------------------
        # BUTTON EVENTS
        # -------------------------------------------------
        if etype == EV_KEY:

            with lock:

                # value:
                # 0 = release
                # 1 = press
                # 2 = repeat/hold
                #
                # For button state we only care whether
                # the button is physically held.

                if code == BTN_LEFT:

                    if value == 0:
                        btn_left = False

                    elif value in (1, 2):
                        btn_left = True

                elif code == BTN_RIGHT:

                    if value == 0:
                        btn_right = False

                    elif value in (1, 2):
                        btn_right = True

        # -------------------------------------------------
        # RELATIVE MOUSE MOVEMENT
        # -------------------------------------------------
        elif etype == EV_REL:

            with lock:

                if code == REL_X:

                    mouse_rel_x += value
                    mouse_x += value

                elif code == REL_Y:

                    mouse_rel_y += value
                    mouse_y += value

                elif code == REL_WHEEL:

                    mouse_wheel += value

                # -----------------------------------------
                # SUPER + ALT = DESKTOP DRAG
                # -----------------------------------------

                if super_pressed and alt_pressed:

                    sign = (
                        -1
                        if read_inverted()
                        else 1
                    )

                    if code == REL_X:
                        acc_x += (
                            value *
                            speed *
                            sign
                        )

                    elif code == REL_Y:
                        acc_y += (
                            value *
                            speed *
                            sign
                        )

                else:
                    acc_x = 0.0
                    acc_y = 0.0

    try:
        fd.close()
    except Exception:
        pass

_active_kbd_threads = {}
_active_mouse_threads = {}

print(
    "[DEVICE MANAGER] Thread registries initialized",
    flush=True
)

def device_manager():
    """Escanea periodicamente /dev/input buscando teclados y mouses nuevos
    (o reconectados) y lanza un hilo lector para cada uno. Si un dispositivo
    se desconecta, su hilo simplemente termina solo al fallar el read().

    Los primeros segundos (WARMUP_DURATION) escanea mucho mas seguido
    (WARMUP_INTERVAL) porque justo al iniciar sesion, dongles inalambricos
    a veces tardan unos segundos en terminar de enumerar sus interfaces USB.
    Despues de ese periodo baja al intervalo normal para no gastar CPU."""
    WARMUP_DURATION = 20.0
    WARMUP_INTERVAL = 0.5
    start_time = time.time()

    while True:
        try:
            keyboards, mice = scan_devices()

            for path in keyboards:
                t = _active_kbd_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=kbd_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_kbd_threads[path] = nt
                    print(f"[+] Keyboard detected: {path}", flush=True)

            for path in mice:
                t = _active_mouse_threads.get(path)
                if t is None or not t.is_alive():
                    nt = threading.Thread(target=mouse_reader_device, args=(path,), daemon=True)
                    nt.start()
                    _active_mouse_threads[path] = nt
                    print(f"[+] Mouse detected: {path}", flush=True)
        
        except Exception as e:
            print(f"Error en device_manager: {e}", flush=True)

        elapsed = time.time() - start_time
        interval = WARMUP_INTERVAL if elapsed < WARMUP_DURATION else DEVICE_RESCAN_INTERVAL
        time.sleep(interval)

# PRECARGAR
print("Preloading...", flush=True)
try:
    subprocess.run(['hyprctl', 'activeworkspace', '-j'], capture_output=True, text=True, timeout=0.5)
    subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.5)
except:
    pass

threading.Thread(target=device_manager, daemon=True).start()
threading.Thread(target=monitor_window_drag, daemon=True).start()
print("Infinite Desktop active", flush=True)
print("Super+click: Drag window", flush=True)
print("Super+Alt+mouse: Drag the entire desktop", flush=True)
print("Super+arrow keys: Navigation via Hyprland bind", flush=True)
print("Super+Shift+arrow keys: Move active window via Hyprland bind", flush=True)
print("Super+Backspace keys: Reset camera and zoom level", flush=True)


def get_cached_workspace_id():
    global _cached_workspace_id, _last_workspace_check
    now = time.time()
    if _cached_workspace_id is None or (now - _last_workspace_check) > WORKSPACE_CACHE_TTL:
        try:
            r = subprocess.run(['hyprctl', 'activeworkspace', '-j'],
                               capture_output=True, text=True, timeout=0.1)
            ws = json.loads(r.stdout)
            _cached_workspace_id = ws['id']
            _last_workspace_check = now
        except:
            pass
    return _cached_workspace_id


def get_infinite_desktop_windows():
    try:
        r = subprocess.run(['hyprctl', 'clients', '-j'], capture_output=True, text=True, timeout=0.1)
        
        clients = json.loads(r.stdout)

        windows = []

        for w in clients:
            workspace = w.get("workspace", {})
            workspace_id = workspace.get('id', -1)

            if workspace_id == INFINITE_WORKSPACE or INFINITE_WORKSPACE is None:
                windows.append(w)

        return windows
    
    except Exception:
        return []

# Main loop for desktop dragging
zoom_momentum = 0.0
while True:
    time.sleep(0.008)

    canvas_active = is_infinite_desktop_workspace()
    
    with lock:        
        
        canvas_zoom = canvas_active and super_pressed and not alt_pressed
        active_drag = super_pressed and alt_pressed

        dx = acc_x
        dy = acc_y
        wheel = mouse_wheel

        reset = reset_requested
        reset_requested = False

        acc_x = 0.0
        acc_y = 0.0
        mouse_wheel = 0

    if reset:
        zoom_momentum = 0.0
        canvas.reset()
        continue

    if canvas_zoom and ZOOM_ENABLED and wheel != 0:

        wheel_amount = abs(wheel)

        # Adds acceleration to the scroll wheel zoom.
        if ZOOM_ACCELERATION:

            acceleration = (
                    1.0
                    + ZOOM_ACCELERATION_STRENGTH
                    * max(0, wheel_amount - 1)
            )

            zoom_factor = (
                    ZOOM_BASE_FACTOR
                    ** acceleration
            )
    
        else: zoom_factor = ZOOM_BASE_FACTOR

        # Adds momentum to the scroll wheel zoom.
        if ZOOM_MOMENTUM:

            zoom_momentum += (
                    wheel
                    * wheel_amount
                    * ZOOM_MOMENTUM_STRENGTH
            )

        # Applies wheel input.
        if wheel > 0:

            canvas.zoom(zoom_factor,
                        mouse_x,
                        mouse_y,
            )

        else:

            canvas.zoom(
                    1 / zoom_factor,
                    mouse_x,
                    mouse_y
            )

    # Apply stored momentum.
    if ZOOM_MOMENTUM and zoom_momentum !=0:

        momentum_factor = (
                ZOOM_BASE_FACTOR
                ** abs(zoom_momentum)
        )

        if zoom_momentum > 0:

            canvas.zoom(
                    momentum_factor,
                    mouse_x,
                    mouse_y,
            )

        else:
            canvas.zoom(
                    1 / momentum_factor,
                    mouse_x,
                    mouse_y,
            )

    # Decay.
    zoom_momentum *= ZOOM_MOMENTUM_DECAY

    # Prevents floating-point values from continuing forever.
    if abs(zoom_momentum) < 0.001:

        zoom_momentum = 0.0

    # Pan.
    if not active_drag:
        continue

    idx = int(round(dx * PAN_SPEED))
    idy = int(round(dy * PAN_SPEED))

    if idx == 0 and idy == 0:
        continue

    try:
        canvas.pan(idx, idy)

    except Exception as e:
        print(e, flush=True)

