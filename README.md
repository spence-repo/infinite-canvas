# infinite-canvas
This is a fork of 'hyprland-infinitie-desktop-v2' by sarodscommits, redesigned around a brand-new persistent world-coordinate and camera system. Infinite canvas introduces additional functionality that includes; cursor-centered zoom, configurable zoom/pan behavior, persistent tracking of window states, and a Canvas reset.
<img width="1920" height="1080" alt="20260509_18h26m44s_grim" src="https://github.com/user-attachments/assets/464fa371-7cc4-4fd5-a06c-55d7b51ba59d" />

**What's New?** 
- Infinite canvas stores windows positions and sizes within its virtual coordinate system that are accurately translated from Hyprland coordinates, and translated back upon window transformations to maintain consistency.
- A virtual camera is now used to display the correct position of the canvas to the screen.
- A new configurable zoom feature that scales the Canvas around the cursor position, making windows appear larger/smaller while maintaining their correct positions.
- Optional configuration options such as disabling/enabling of features and changes to their behavior.
- The option to set Infinite canvas to all workspaces, or to be workspace-specific.
- Canvas reset bind that resets camera position and zoom level.

## Requirements
You need Python 3, jq, bash, python-evdev installed on your system.

### Installation by Distribution:
* **Arch Linux:**
  ```bash
  sudo pacman -S python python-evdev bash jq
    ```
* **Fedora:**
  ```bash
  sudo dnf install python python-evdev bash jq
    ```
* **Ubuntu / Debian:**
  ```bash
  sudo apt install python python-evdev bash jq
    ```
  
## Permissions
1. Add your user to the group
```bash
sudo usermod -aG input $USER
  ```
2. Restart your session
```bash
sudo reboot
  ```

## Installation
1. **Create the directory:**
   All scripts must be stored in a dedicated folder in your home directory:
   ```bash
   mkdir -p ~/scripts
   ```
   
2. **Download the scripts:**
Place all scripts (.py and .sh) inside ~/scripts/

3. **Grant execution permissions:**
  ```bash
  chmod +x ~/scripts/infinite-desktop.sh ~/scripts/floating_tile_toggle.py ~/scripts/move_window_tiled.py ~/scripts/navigate_windows.py ~/scripts/resize_window.py
  ```

## Configuration
**Auto-start**
   Add the following lines to your ~/.config/hypr/hyprland.lua:
   ```bash
    hl.on("hyprland.start", function()
        hl.exec_cmd("python3 ~/scripts/infinite_desktop_core.py 1.6 > /tmp/infinite-desktop.log 2>&1")
   end)
   ```
**Configuration file**
A configuration file will be created within "~/.config/infinite-canvas/config.json" when 'infinite_desktop_core.py' has started.

Configuration options:
- workspace - By default is set to 'null', which applies to ALL workspaces. To be workspace specific, set the appropriate workspace number.
- monitor - Set the monitor that canvas will work on (recommended). 'hyprctl monitors' command can be used to find the name of your monitor.
- zoom - Can be set to enabled/disabled.
- zoom base-factor - Can be set to enabled/disabled. Sets the zoom multiplier for each wheel step.
- zoom acceleration - Can be set to enabled/disabled. Makes larger/faster scroll movements produce larger zoom steps via strength value.
- zoom momentum - Can be set to enabled/disabled. Stops zoom from stopping immediately after scroll wheel movements ceases depending on 'strength' value.
- zoom momentum decay - How quickly momentum fades.
- pan speed - Controls how much Canvas movement is produced from mouse movement.
  
## How to use
 
 **Panning:** Hold ***SUPER + ALT*** and move your mouse to slide the entire desktop.

 **Zoom** Press/hold **SUPER + SCROLL WHEEL UP/DOWN** to zoom all windows in/out

 **Reset** Press **SUPER + BACKSPACE** to reset camera position and zoom level.

 ## Disclaimer
 I am by no means an experienced programmer. This was a fun learning project of mine as part of my ricing journey with Hyprland.

