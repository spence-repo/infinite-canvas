import json
import subprocess

from config import load_config
from hypr_ipc import (
    batch_async,
    move_window_exact_lua,
    resize_window_exact_lua,
)

"""
Naming conventions:
    
    window - A raw Hyprland window object that consists of window data in raw JSON format.
             Derived from 'hyprctl clients -j'.

    geometry - A simplified rectangle containing; 
               width, height, x, y attributes of a window object seperated from JSON format.

    world - A windows position and size within the infinite desktop coordinate system.

    screen - The final rendered position of a window on the physical display monitor after camera
             and zoom transforms.

"""

class Canvas:

    def __init__(self, workspace, monitor):
        """
        Create a virtual desktop canvas.

        The Canvas is responsible for storing the relationship between
        Hyprland windows and their positions inside the infinite world.

        workspace:
            Hyprland workspace this canvas controls.

        monitor:
            Monitor where the canvas is displayed.

        world_windows:
            Stores each window's position in world coordinates.
        """

        self.workspace = workspace
        self.monitor = monitor

        self.zoom_level = 1.0
        
        # Original Hyprland geometry before transformations
        self.original_geometry = {}
        
        # Infinite desktop coordinate storage
        self.world_windows = {}

        # Camera coordinates
        self.camera_x = 0
        self.camera_y = 0

    
    def hyprland_windows(self):
        """
        Return all windows currently belonging to this canvas workspace.

        Queries Hyprland for existing clients and filters only windows that
        belong to this Canvas workspace.
        """

        # Captures output from this command, which returns text.
        result = subprocess.run(
                # Command returns data in json 'form' but is read by Python as a string.
                ['hyprctl', 'clients', '-j'],
                capture_output=True,
                text = True
        )
    
        # 'json.loads' reads the json string and converts text into readable objects within a list.
        clients = json.loads(result.stdout)

        windows = []

        # Stores each object to window.
        for window in clients:
            workspace_id = window["workspace"]["id"]
            
            if (
                self.workspace is None
                or workspace_id == self.workspace
            ):
                windows.append(window)

        return windows
 

    def window_geometry(self, window):
        """
        Extract a window's gemotry from Hyprland data.
        
        Returns a dictionary containing:
            x position
            y position
            width
            height

        This converts Hyprlands JSON data into a format that can be used by Canvas.
        """

        return {
                "x": window["at"][0],
                "y": window["at"][1],
                "width": window["size"][0],
                "height": window["size"][1],
        }
    

    def monitor_center(self):
        """
        Calculate the center point of the canvas display monitor.

        This position is used as the anchor point for operations such
        as zooming, where windows expand or shrink around the monitor center.
        """
        
        result = subprocess.run(
                ["hyprctl", "monitors", "-j"],
                capture_output=True,
                text=True
        )
        
        monitors = json.loads(result.stdout)

        for monitor in monitors:
            if monitor["name"] == self.monitor:

                return (
                        monitor["x"] + monitor["width"] / 2,
                        monitor["y"] + monitor["height"] / 2,
            )

        raise Exception(f"Monitor {self.monitor} not found")


    def window_center(self, window):
        """
        Calculate the center point of a Hyprland window.

        Accepts a raw Hyprland window object and converts it
        into internal geometry format before calculating the center.

        This helper is useful when working directly with Hyprland
        window data.
        """
        
        geo = self.window_geometry(window)

        return self.geometry_center(geo)


    def geometry_center(self, geo):
        """
        Calculate the center point of a geometry dictionary.

        Used internally when transforming stored window geometry.
        """

        return (
                geo["x"] + geo["width"] / 2,
                geo["y"] + geo["height"] / 2,
        )


    def capture_layout(self):
        """
        Save the current window layout.

        Stores the current position and size of every window.

        This snapshot is used as the reference point for transformations
        such as zooming.
        """

        self.original_geometry.clear()

        for window in self.hyprland_windows():
            self.original_geometry[window["address"]] = self.window_geometry(window)
                

    def pan(self, dx, dy, excluded_addr=None):
        """
        Pan the camera across the infinite desktop.

        Moves the camera through world space, then redraws every
        registered window at its corresponding screen position.
        """

        # Discover new windows.
        self.refresh_world_windows()
        
        # Move camera.
        self.camera_x += dx
        self.camera_y += dy

        # Convert every window to correct screen position and render windows to screen.
        self.render(resize=False, excluded_addr=excluded_addr)


    def zoom(self, factor, cursor_x, cursor_y):

        """
        Change the camera zoom level.

        The world coordinates remain unchanged.
        Windows are converted from world space to screen space
        using the current camera transform.
        """

        self.refresh_world_windows()

        # Save the world position underneath the cursor.
        anchor_world_x, anchor_world_y = self.screen_to_world(cursor_x, cursor_y) 

        self.zoom_level *= factor

        # Prevents zoom levels below 0.25.
        self.zoom_level = max(self.zoom_level, 0.25)

        # Prevents zoom levels above 3.0.
        self.zoom_level = min(self.zoom_level, 3.0)
        
        # Calculate where the same world position now appears on screen.
        anchor_screen_x, anchor_screen_y = self.world_to_screen(anchor_world_x, anchor_world_y)
        
        # Calculate how far the world point drifted from the cursor.
        screen_drift_x = anchor_screen_x - cursor_x
        screen_drift_y = anchor_screen_y - cursor_y

        # Moves the camera to fix drift.
        self.camera_x += screen_drift_x / self.zoom_level
        self.camera_y += screen_drift_y / self.zoom_level

        self.render(resize=True)

    def register_window(self, address, x, y, width, height):
        """
        Add a window to the world coordinate system.

        address:
            Unique Hyprland window identifier.

        x, y:
            Position inside the infinite world.

        width, height:
            Window dimensions.

        This creates the Canvas representation of a Hyprland window.
        """

        self.world_windows[address] = {
                "x": x,
                "y": y,
                "width": width,
                "height": height,
        }


    def get_world(self, address):
        """
        Retrieve a window's world coordinate state.

        Returns the stored position and size of a window
        inside the infinite desktop world.
        """
        return self.world_windows[address]


    def set_world(self, address, x, y):
        """
        Update a window's world position.

        Used when a window needs to be moved directly
        to a new location in the virtual desktop.
        """

        self.world_windows[address]["x"] = x
        self.world_windows[address]["y"] = y


    def world_center(self, world):
        """
        Calculate the center point of a window in world coordinates.
        """

        return (
                world["x"] + world["width"] / 2,
                world["y"] + world["height"] /2,
        )


    def world_to_screen(self, x, y):
        """
        Convert a world position into a screen position.

        World coordinates desrcibe where an object exists inside the infinite desktop. 
        Screen coordinates describe where that object should appear on the user's monitor.

        The conversion applies the camera transform in three stages:

        1. Translate the world relative to the camera.
        2. Scale the result by the current zoom level.
        3. Offset the position into the monitor's coordinate system.

        Returns:
            (screen_x, screen_y)
                The position where the object should be rendered.

        """

        monitor_center_x, monitor_center_y = self.monitor_center()

        screen_x = (
                (x - self.camera_x) * self.zoom_level
                + monitor_center_x
            )

        screen_y = (
                (y - self.camera_y) * self.zoom_level
                + monitor_center_y
            )

        return screen_x, screen_y


    def screen_to_world(self, x, y):
        """
        Convert a screen position into a world position.

        Screen coordinates represent a location on the user's monitor,
        such as the mouse cursor. World coordinates represent the
        corresponding position inside the infinite desktop.

        This performs the inverse of world_to_screen():

            1. Remove the monitor offset.
            2. Undo the zoom scaling.
            3. Translate back into world space using the camera position.

        Returns:
            (world_x, world_y)
                The location inside the infinite desktop that corresponds
                to the supplied screen position.
        """

        monitor_center_x, monitor_center_y = self.monitor_center()
        
        world_x = (
                (x - monitor_center_x) / self.zoom_level
                + self.camera_x
            )

        world_y = (
            (y - monitor_center_y) / self.zoom_level
            + self.camera_y
            )

        return world_x, world_y


    def move_world(self, address, dx, dy):
        """
        Move a window inside the world coordinate system.

        This updates Canvas state only.

        It does not immediately move the real Hyprland window.
        A later rendering step will translate the world position
        into a screen position.
        """

        state = self.world_windows[address]
        state["x"] += dx
        state["y"] += dy


    def refresh_world_windows(self):
        """
        Refresh which windows belong to Canvas.world_windows.

        - Adds new Hyprland windows that are not yet in Canvas state.
        - Removes windows that no longer exist on this workspace.
        - Does NOT change the world position or size of existing windows.
        """

        print(
        "\nRefreshing World...",
        flush=True
    )

        self.remove_stale_windows()

        for window in self.hyprland_windows():

            address = window["address"]

            # Print debug for showing windows that already exist.
            if address in self.world_windows:
                print(f"{address} already exists.", flush=True)
                continue

            # If current window(s) isn't part of Canvas state, add it.
            if address not in self.world_windows:

                geo = self.window_geometry(window)

                world_x, world_y = self.screen_to_world(
                        geo["x"],
                        geo["y"],
                    )

                # Adds window into Canvas state (world_windows)
                self.register_window(
                    address,
                    world_x,
                    world_y,
                    geo["width"] / self.zoom_level,
                    geo["height"] / self.zoom_level,
                )
    

    def update_window(self, window):
        """
        Update one Canvas window using its current Hyprland geometry.

        - Reads the window's current screen position and size.
        - Converts that screen geometry into world coordinates.
        - Replaces the window's stored world position and size.

        This changes the existing world state of this specific window.
        """

        old = self.world_windows.get(window["address"])

        geo = self.window_geometry(window)

        world_x, world_y = self.screen_to_world(
                geo["x"],
                geo["y"],
        )

        print(
        f"\nUpdating Window {window['address']}...\n",
        f"OLD WORLD       = {old}\n",
        f"NEW WORLD       = {world_x}, {world_y}\n",
        f'SCREEN          = (x; {geo["x"]}, y; {geo["y"]}), (width; {geo["width"]}, height; {geo["height"]})\n',
        f"ZOOM            = {self.zoom_level}",
        flush=True,
            )

        self.world_windows[window["address"]] = {
                "x": world_x,
                "y": world_y,
                "width": geo["width"] / self.zoom_level,
                "height": geo["height"] / self.zoom_level,
        }
        
        screen = self.screen_geometry(
        self.world_windows[window["address"]]
        )

        print(
            f" WORLD to SCREEN = ({screen['x']}, {screen['y']})\n "
            f"RENDER SIZE     = ({screen['width']}, {screen['height']})",
            flush=True
        )


    def update_all_windows(self):
        """
        Update every Canvas window using its current Hyprland geometry.

        - Reads the current screen position and size of every Hyprland window.
        - Converts each window's screen geometry into world coordinates.
        - Replaces the stored world position and size for every window.

        This does not specifically add or remove windows from Canvas state.
        """

        for window in self.hyprland_windows():
            self.update_window(window)


    def move_window_screen(self, address, screen_x, screen_y):
        """
        Move a window to a new screen position.

        Converts the screen position into world coordinates
        and updates the Canvas world model.

        Does not directly move the Hyprland window.
        """

        world_x, world_y = self.screen_to_world(
                screen_x,
                screen_y,
        )

        self.set_world(
                address,
                world_x,
                world_y,
        )

    def move_window_world(self, address, dx, dy):
        """
        Move a window inside the infinite world.
        
        Updates canvas state and renders the result.
        """
        
        self.move_world(address, dx, dy)

        print(
        "WORLD AFTER:",
        self.world_windows[address],
        flush=True,
        )

        self.render()


    def reset(self):
        """
        Resets zoom level and camera position.
        """
            
        self.camera_x = 0
        self.camera_y = 0
        self.zoom_level = 1.0

        self.render(resize=True)


    def screen_geometry(self, world):
        """
        Convert a window from world space into screen space.

        Returns the position and size the window should occupy
        after applying the current camera transform and zoom.
        """
        
        screen_x, screen_y = self.world_to_screen(
                world["x"],
                world["y"],
            )
        
        return {
                "x": int(screen_x),
                "y": int(screen_y),
                "width": int(world["width"] * self.zoom_level),
                "height": int(world["height"] * self.zoom_level),
            }


    def render(self, resize=True, excluded_addr=None):
        """Renders all windows to screen."""

        current_windows = {
        window["address"]: window
        for window in self.hyprland_windows()
        }
        
        exprs = []

        for address, world in self.world_windows.items():

            if address == excluded_addr:
                continue

        # Do not render windows that are no longer
        # part of this Canvas's workspace.
            if address not in current_windows:
                continue
            

            screen = self.screen_geometry(world)

            exprs.append(
                move_window_exact_lua(
                    screen["x"],
                    screen["y"],
                    address,
                )
         )

            if resize:
                exprs.append(
                    resize_window_exact_lua(
                        screen["width"],
                        screen["height"],
                        address,
                    )
                )   
        
        batch_async(exprs)


    def remove_stale_windows(self):
        """
        Remove windows from self.world_windows that no 
        longer exist on the Canvas workspace.
        """

        current_addresses = {
                window["address"]
                for window in self.hyprland_windows()
        }

        stale_addresses = [
                address
                for address in self.world_windows
                if address not in current_addresses
            ]

        for address in stale_addresses:
            print(
                f"REMOVING {address} from Canvas state...:",
                flush=True
            )

            del self.world_windows[address]

    
    def test_transform(self):
        """
        Checks that world_to_screen and screen_to_world
        are inverse operations.

        A world point should return to the same position
        after being converted to screen space and back.
        """

        test_world_x = 500
        test_world_y = -300

        print("Original world:")
        print(test_world_x, test_world_y)

        # Convert world -> screen
        screen_x, screen_y = self.world_to_screen(
            test_world_x,
            test_world_y
        )

        print("Converted screen:")
        print(screen_x, screen_y)

        # Convert screen -> world
        world_x, world_y = self.screen_to_world(
            screen_x,
            screen_y
        )

        print("Returned world:")
        print(world_x, world_y)
    

        
# Test
#canvas = Canvas(8, "DP-3")

#print(canvas.camera_x, canvas.camera_y)
#canvas.register_window("test", 0, 0, 800, 600)
#canvas.render()

#canvas.pan(100,0)
#canvas.zoom(2, 960, 540)
